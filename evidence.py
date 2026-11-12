"""Cold verification, evidence retention and publication eligibility."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import time
import review_policy
from check_paths import referenced_paths
from path_safety import checked_path
from skill_inventory import skill_files
from egm import validate_handoff
from verification_policy import validate_policy, validate_evidence
from cold_workspace import clone_candidate, env_for_checks

from runtime import FactoryError, changed_entries, command, config, config_hash, diff_paths, dirty, git, invoke, protected, within


def sha_file(path):
    try:
        path = checked_path(path)
    except ValueError as exc:
        raise FactoryError(str(exc)) from exc
    if not path.is_file():
        raise FactoryError('Missing or symlinked evidence: ' + str(path))
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()



def toolchain_identity(c):
    """Pin direct external executables/scripts/skills, not transitive dependencies."""
    files = {}
    specs = list(c['commands'].values()) + [{'argv': x} for x in c['checks']] + c.get('verification', {}).get('checks', [])
    specs += [x['negative_control'] for x in c.get('verification', {}).get('checks', [])
              if 'negative_control' in x]
    for spec in specs:
        for i, arg in enumerate(spec.get('argv', [])):
            if '{' in arg:
                continue
            path = Path(shutil.which(arg) or arg) if i == 0 else Path(arg)
            if path.is_absolute() and path.is_file():
                path = path.resolve()
                files[str(path)] = sha_file(path)
        skill = spec.get('primary_skill')
        if skill and Path(skill).is_file():
            path = Path(skill).resolve();files[str(path)] = sha_file(path)
        for helper in spec.get('support_skills', {}).values():
            files.update(skill_files(helper))
    return files


def acceptance_items(ticket):
    values = list(ticket['acceptance'])
    for section in ('ui', 'api', 'data', 'cross_cutting'):
        values.extend(ticket['spec'][section].get('acceptance', []))
    return values


def cold_checks(checkout, logs, c, ticket, base, head, checks):
    logs.mkdir(parents=True, exist_ok=False)
    evidence = {'version': 2, 'head': head, 'base': base,
                'tree': git(checkout, 'rev-parse', 'HEAD^{tree}'),
                'policy': config_hash(c), 'ticket': config_hash(ticket),
                'files': diff_paths(checkout, base, head),
                'acceptance': acceptance_items(ticket), 'checks': [], 'artifacts': {}, 'trusted_tools': toolchain_identity(c)}
    diff = logs / 'candidate.diff'
    diff.write_bytes(subprocess.check_output(['git', '-C', str(checkout), 'diff', '--binary', '--no-renames', base, head], timeout=60))
    evidence['artifacts'][str(diff)] = sha_file(diff)
    env = env_for_checks(checkout, logs.name + '-' + str(time.time_ns()))
    # Preliminary commands are rerun too; ignored builder files cannot supply their inputs.
    for n, argv in enumerate(c['checks']):
        log = logs / f'preflight-{n}.log'
        invoke(command({'argv': argv}, {'worktree': checkout}), checkout, log, c['timeout_seconds'], env=env)
        evidence['artifacts'][str(log)] = sha_file(log)
    for check in checks:
        check_logs = logs / 'checks' / check['id']
        check_logs.mkdir(parents=True)
        report = check_logs / 'reports' / check['report']
        report.parent.mkdir(parents=True, exist_ok=True)
        if report.exists() or report.is_symlink():
            raise FactoryError('Cold report already exists')
        log = check_logs / 'positive.log'
        argv = command(check, {'worktree': checkout, 'report': report, 'test_mode': 'pass'})
        started = time.monotonic()
        invoke(argv, checkout, log, c['timeout_seconds'], env=env)
        counts = validate_evidence(report, check)
        negative = negative_control(checkout, check_logs, c, base, head, check, counts, evidence['artifacts'])
        evidence['checks'].append({'id': check['id'], 'kind': check['kind'], 'argv': argv,
                                   'counts': counts, 'report': str(report), 'negative_control': negative,
                                   'seconds': round(time.monotonic() - started, 6)})
        evidence['artifacts'][str(log)] = sha_file(log)
        evidence['artifacts'][str(report)] = sha_file(report)
        if dirty(checkout) or git(checkout, 'rev-parse', 'HEAD') != head:
            raise FactoryError('Cold check modified the candidate checkout')
    if dirty(checkout) or git(checkout, 'rev-parse', 'HEAD') != head:
        raise FactoryError('Cold verification changed candidate')
    evidence['digest'] = config_hash(evidence)
    (logs / 'manifest.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    return evidence


def negative_control(source, logs, c, base, head, check, passing, artifacts):
    """Apply a trusted defect in a separate clone; rerun the identical test command.

    Only declared assertion failures count. Crashes, collection errors, missing
    tests, a surviving mutation or a changed test inventory all block readiness.
    """
    checkout = logs / ('negative-' + check['id'])
    clone_candidate(source, checkout, head, base)
    env = env_for_checks(checkout, 'negative-' + check['id'])
    for n, argv in enumerate(c['checks']):
        log = logs / f"{check['id']}-negative-preflight-{n}.log"
        invoke(command({'argv': argv}, {'worktree': checkout}), checkout, log, c['timeout_seconds'], env=env)
        artifacts[str(log)] = sha_file(log)
    if dirty(checkout) or git(checkout, 'rev-parse', 'HEAD') != head:
        raise FactoryError('Negative-control preflight changed candidate')
    tracked = set(git(checkout, 'ls-tree', '-r', '--name-only', '-z', head).split('\0'))
    check_inputs = referenced_paths(c, checkout, tracked - {''}, source)
    mutation = check['negative_control']
    mutation_log = logs / (check['id'] + '-mutation.log')
    mutation_argv = command(mutation, {'worktree': checkout})
    invoke(mutation_argv, checkout, mutation_log, c['timeout_seconds'], env=env)
    paths = dirty(checkout)
    if not paths or git(checkout, 'rev-parse', 'HEAD') != head:
        raise FactoryError('Negative control must modify production files without changing HEAD')
    for path in paths:
        if any(p == '.' or within(path, p) for p in check_inputs):
            raise FactoryError('Negative control changed a configured check input: ' + path)
        is_test, is_config = verification_sensitive(path)
        if protected(path) or is_test or is_config or any(within(path, p) for p in c.get('protected_paths', [])):
            raise FactoryError('Negative control changed a test or protected input: ' + path)
    refuse_links(checkout, head)
    for path in paths:
        target = checkout / path
        try:
            checked_path(target, root=checkout)
        except ValueError as exc:
            raise FactoryError('Negative control introduced an unsafe path') from exc
    diff = logs / (check['id'] + '-mutation.diff')
    diff.write_bytes(subprocess.check_output(['git', '-C', str(checkout), 'diff', '--binary', head], timeout=60))
    # Retain untracked additions/deletions as well as the tracked patch.
    mutation_files = {path: sha_file(checkout / path) if (checkout / path).is_file() else None for path in paths}
    report = logs / 'negative-reports' / check['report']
    report.parent.mkdir(parents=True, exist_ok=True)
    if report.exists() or report.is_symlink():
        raise FactoryError('Negative-control report already exists')
    log = logs / (check['id'] + '-negative.log')
    argv = command(check, {'worktree': checkout, 'report': report, 'test_mode': 'fail'})
    invoke(argv, checkout, log, c['timeout_seconds'], env=env)
    failing = validate_evidence(report, check, expect_failure=True)
    validate_negative_result(check, passing, failing)
    if (git(checkout, 'rev-parse', 'HEAD') != head or set(dirty(checkout)) != set(paths) or
            mutation_files != {path: sha_file(checkout / path) if (checkout / path).is_file() else None for path in paths}):
        raise FactoryError('Negative test command changed the controlled mutation')
    for path in (mutation_log, diff, report, log):
        artifacts[str(path)] = sha_file(path)
    return {'head': head, 'base': base, 'argv': argv, 'mutation_argv': mutation_argv,
            'mutation_files': mutation_files, 'diff': str(diff), 'report': str(report), 'counts': failing}


def validate_negative_result(check, passing, failing):
    positive_ids = {t['id'] for t in passing['tests']}
    negative_ids = {t['id'] for t in failing['tests']}
    failed_ids = {t['id'] for t in failing['tests'] if t['status'] == 'failed'}
    expected = set(check['negative_control']['expected_failures'])
    if not expected or positive_ids != negative_ids or failed_ids != expected:
        raise FactoryError('Negative control did not fail exactly the declared tests in the passing inventory')


def check_evidence_files(evidence):
    if not isinstance(evidence, dict) or not evidence.get('artifacts') or not evidence.get('checks'):
        raise FactoryError('Cold evidence missing')
    payload = dict(evidence)
    digest = payload.pop('digest', None)
    if digest != config_hash(payload):
        raise FactoryError('Cold evidence digest mismatch')
    for path, expected in {**evidence['artifacts'], **evidence.get('trusted_tools', {})}.items():
        if sha_file(path) != expected:
            raise FactoryError('Cold evidence artifact changed: ' + path)


def validate_review_evidence(review, evidence, ticket):
    if review.get('verdict') != 'PASS':
        return
    expected = list(range(len(acceptance_items(ticket))))
    covered = review.get('acceptance_covered')
    if (review.get('evidence_digest') != evidence.get('digest') or
            review.get('tests_confirmed') is not True or
            not isinstance(covered, list) or any(type(x) is not int for x in covered) or sorted(covered) != expected or
            not isinstance(review.get('covered_files'), list) or
            sorted(review['covered_files']) != evidence.get('files')):
        raise FactoryError('Review lacks complete file/acceptance/test evidence attestation')
    observed = {(check['id'], test['id']) for check in evidence.get('checks', [])
                for test in check['counts']['tests'] if test['status'] == 'passed'}
    mappings = review.get('acceptance_tests')
    if not isinstance(mappings, list) or len(mappings) != len(expected):
        raise FactoryError('Review must map every acceptance criterion to named tests')
    indices = set()
    for mapping in mappings:
        if (not isinstance(mapping, dict) or set(mapping) != {'acceptance', 'tests'} or
                type(mapping['acceptance']) is not int or mapping['acceptance'] not in expected or
                mapping['acceptance'] in indices or not isinstance(mapping['tests'], list) or not mapping['tests']):
            raise FactoryError('Invalid or duplicate acceptance-to-test mapping')
        indices.add(mapping['acceptance'])
        references = set()
        for reference in mapping['tests']:
            if (not isinstance(reference, dict) or set(reference) != {'check', 'test'} or
                    not all(isinstance(v, str) for v in reference.values())):
                raise FactoryError('Invalid test reference')
            key = (reference['check'], reference['test'])
            if key not in observed or key in references:
                raise FactoryError('Review cites an unknown, non-passing or duplicate test')
            references.add(key)


def refuse_links(repo, rev):
    for line in git(repo, 'ls-tree', '-r', rev).splitlines():
        if line.startswith(('120000 ', '160000 ')):
            raise FactoryError('Symlinks/submodules require an isolated runner; local mode refuses this repository: '
                               + line.split('\t', 1)[-1])


MANIFESTS = {'package.json', 'package-lock.json', 'npm-shrinkwrap.json', 'pnpm-lock.yaml', 'pnpm-workspace.yaml',
             'bun.lockb', '.npmrc', '.yarnrc', '.yarnrc.yml', 'pyproject.toml', 'pytest.ini', 'tox.ini', 'setup.cfg',
             'setup.py', 'conftest.py', 'noxfile.py', 'pipfile', 'go.mod', 'go.sum', 'cargo.toml', 'gemfile',
             'pom.xml', 'build.gradle', 'build.gradle.kts', 'settings.gradle', 'composer.json', '.gitignore',
             '.gitattributes', '.gitmodules', 'makefile', 'dockerfile', 'justfile', 'taskfile.yml'}


TEST_DIRS = {'tests', 'test', '__tests__', '__snapshots__', 'e2e', 'cypress'}


def verification_sensitive(path):
    """(is_test, is_config) by name heuristics. Not exhaustive: add project-specific
    runners, wrappers and fixtures to protected_paths."""
    name = PurePosixPath(path).name.lower()
    stem = name.split('.', 1)[0]
    parts = [x.lower() for x in PurePosixPath(path).parts]
    test = (any(x in TEST_DIRS for x in parts) or name.startswith('test_') or stem.endswith(('_test', '-test'))
            or any(x in name for x in ('.test.', '.spec.', '.e2e.', '.snap')))
    config_file = (name in MANIFESTS or '.config.' in name or name.endswith('.lock') or name.startswith(('requirements', 'tsconfig', 'jsconfig', 'docker-compose', '.eslintrc', '.babelrc', '.env')))
    return test, config_file


def guard_verification_inputs(repo, ticket, base, head, c, source_repo=None):
    """Existing tests and runners require a separate policy-maintenance workflow.

    This is regression resistance, not protection from a malicious OS peer.
    """
    tracked = set(git(repo, 'ls-tree', '-r', '--name-only', '-z', base).split('\0'))
    tracked.update(git(repo, 'ls-tree', '-r', '--name-only', '-z', head).split('\0'))
    tracked.discard('')
    check_paths = referenced_paths(c, repo, tracked, source_repo)
    for status, path in changed_entries(repo, base, head):
        if any(p == '.' or within(path, p) for p in check_paths):
            raise FactoryError('Configured check input requires separate policy review: ' + path)
        test, config_file = verification_sensitive(path)
        if config_file or (test and status != 'A') or any(within(path, p) for p in c.get('protected_paths', [])):
            raise FactoryError('Verification-sensitive change requires separate policy review: ' + path)
    refuse_links(repo, head)



def verify_candidate(repo, c, row, require_pass=True, require_approval=True):
    head, base, branch = row['head_sha'], row['base_sha'], row['branch']
    work = Path(row['worktree'])
    if row['config_hash'] != config_hash(c) or config_hash(config(repo)) != config_hash(c):
        raise FactoryError('Configuration changed since verification; fresh review/checks required')
    if git(repo, 'rev-parse', c['base_ref']) != base or git(repo, 'rev-parse', 'HEAD') != base or dirty(repo, True):
        raise FactoryError('Base changed or is dirty; fresh review/checks required')
    if git(repo, 'rev-parse', 'refs/heads/' + branch) != head or git(work, 'rev-parse', 'HEAD') != head or dirty(work):
        raise FactoryError('Candidate changed or is dirty')
    review, checks = json.loads(row['review_json']), json.loads(row['checks_json'])
    if (require_pass and review.get('verdict') != 'PASS') or review.get('reviewed_head') != head or review.get('base') != base:
        raise FactoryError('Review does not match candidate')
    ticket = json.loads(row['ticket'])
    guard_verification_inputs(work, ticket, base, head, c, source_repo=repo)
    files = diff_paths(work, base, head)
    policy = c.get('review_policy', {})
    if set(review.get('lenses', {})) != set(review_policy.lenses(policy, files)):
        raise FactoryError('Required review lenses differ from candidate evidence')
    for lens in review['lenses']:
        r = review.get('lenses', {}).get(lens, {})
        if ((require_pass and (r.get('verdict') != 'PASS' or r.get('findings') != [])) or
                r.get('reviewed_head') != head or r.get('base') != base):
            raise FactoryError('Every required exact-head review lens must pass')
    ticket = json.loads(row['ticket'])
    validate_handoff(work, ticket, required=c.get('workflow') == 'egm')
    validate_handoff(repo, ticket, required=c.get('workflow') == 'egm')
    selected_checks = validate_policy(c, ticket)
    for r in review['lenses'].values():
        artifact = r.get('artifact')
        if artifact:
            if sha_file(artifact['file']) != artifact['sha256']:
                raise FactoryError('Review result artifact changed')
            raw = json.loads(Path(artifact['file']).read_text(encoding='utf-8'))
            if raw != {k: v for k, v in r.items() if k not in ('artifact', 'evidence', 'routing')}:
                raise FactoryError('Review differs from original result artifact')
        elif c.get('repair_policy') is not None:
            raise FactoryError('Repair requires retained raw review artifacts; run fresh verification')
        for receipt in (r.get('routing'),):
            if receipt and sha_file(receipt['file']) != receipt['sha256']:
                raise FactoryError('Routing evidence changed')
        evidence = r.get('evidence', {})
        validate_review_evidence(r, evidence, ticket)
        if evidence.get('head') != head or evidence.get('base') != base or evidence.get('policy') != config_hash(c):
            raise FactoryError('Cold evidence identity changed')
        check_evidence_files(evidence)
        if evidence.get('version') != 2 or evidence.get('ticket') != config_hash(ticket):
            raise FactoryError('Legacy or mismatched evidence requires fresh verification')
        if [x['id'] for x in evidence['checks']] != [x['id'] for x in selected_checks]:
            raise FactoryError('Evidence check inventory differs from policy')
        for check, receipt in zip(selected_checks, evidence['checks']):
            negative = receipt.get('negative_control', {})
            if negative.get('head') != head or negative.get('base') != base:
                raise FactoryError('Missing or stale negative control')
            for result, expect_failure in ((receipt, False), (negative, True)):
                report = result.get('report')
                if report not in evidence['artifacts'] or validate_evidence(report, check, expect_failure) != result['counts']:
                    raise FactoryError('Retained named report differs from manifest')
            validate_negative_result(check, receipt['counts'], negative['counts'])
    expected = {'head': head, 'policy': config_hash(c), 'cold': {k: v['evidence']['digest'] for k, v in review['lenses'].items()}}
    if checks != expected:
        raise FactoryError('Missing or stale cold check evidence')
    if policy.get('risk') is not None:
        risk = review_policy.check_risk(review.get('risk'), policy, files, head, base, ticket['role'] == 'critical')
        receipt = risk.get('routing')
        if receipt and sha_file(receipt['file']) != receipt['sha256']:
            raise FactoryError('Risk routing evidence changed')
        if require_approval and not review_policy.approved(review, head, config_hash(c)):
            raise FactoryError('Independent risk assessment requires exact-candidate human approval')
    return review

