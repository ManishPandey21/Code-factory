"""Ticket selection, worker routing and execution orchestration."""
from __future__ import annotations
import concurrent.futures
import json
import os
from pathlib import Path
import socket
import time
from instructions import builder_prompt, reviewer_prompt, risk_prompt

import review_policy
from egm import validate_handoff
from verification_policy import validate_policy, validate_spec
from cold_workspace import clone_candidate

from runtime import FactoryError, GIT_LOCK, VERIFY_LOCK, assert_committed_scope, attempt_limit, config, config_hash, diff_paths, dirty, git, overlap, reserved, run_agent, scoped
from records import connect, record, update
from evidence import check_evidence_files, cold_checks, guard_verification_inputs, sha_file, toolchain_identity, validate_review_evidence


def builder_key(c, ticket):
    """Builder command for a ticket: by risk (role critical) and complexity, not only by layer.

    Configurations that define builder_routine / builder_complex / builder_critical route on those;
    older configurations without them keep using commands[role].
    """
    if ticket['role'] == 'critical':
        tier = 'builder_critical'
    else:
        tier = 'builder_' + ticket.get('complexity', 'routine')
    return tier if tier in c['commands'] else ticket['role']


def reviewer_spec_for(c, ticket, lens):
    """Reviewer command for a lens; critical tickets may escalate to a dedicated reviewer command."""
    commands = c['commands']
    if ticket.get('role') == 'critical' and 'reviewer_' + lens + '_critical' in commands:
        return commands['reviewer_' + lens + '_critical']
    return commands.get('reviewer_' + lens, commands.get('reviewer'))


def strict_routing(spec):
    return isinstance(spec, dict) and '--strict-routing' in spec.get('argv', [])


def routing_evidence(result_path, spec):
    """The bridge's routing evidence for one agent run; required when the command pins routing."""
    path = Path(result_path).with_name(Path(result_path).stem + '.routing.json')
    if path.is_symlink() or not path.is_file():
        if strict_routing(spec):
            raise FactoryError(f'Missing routing evidence {path.name} for a strict-routing command')
        return None
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('outcome') != 'ok':
        raise FactoryError(f'Routing evidence {path.name} does not record a successful run')
    if strict_routing(spec):
        if data.get('schema') != 1 or type(data.get('exit_code')) is not int or data['exit_code'] != 0:
            raise FactoryError('Invalid routing evidence schema or exit status')
        for field, expected in (('provider', spec.get('provider')), ('requested_model', spec.get('model')),
                                ('requested_effort', spec.get('effort'))):
            if not expected or data.get(field) != expected:
                raise FactoryError('Routing evidence does not match configured ' + field)
    return {'file': str(path), 'sha256': sha_file(path), 'provider': data.get('provider'),
            'requested_model': data.get('requested_model'), 'requested_effort': data.get('requested_effort'),
            'served_models': data.get('served_models'),
            'served_models_verified': data.get('served_models_verified', False), 'total_cost_usd': data.get('total_cost_usd'),
            'duration_ms': data.get('duration_ms'), 'num_turns': data.get('num_turns')}


def execute_ticket(repo, home, c, ticket, base, repair=None, repair_request=None):
    tid = ticket['id']
    validate_handoff(repo, ticket, required=c.get('workflow') == 'egm')
    selected_checks = validate_policy(c, ticket)
    tools_before = toolchain_identity(c)
    with connect(home) as con:
        previous = dict(con.execute('SELECT * FROM tickets WHERE id=?', (tid,)).fetchone())
    stamp = str(time.time_ns())
    work = home / 'worktrees' / (tid + '-' + stamp)
    review_work = home / 'worktrees' / (tid + '-review-' + stamp)
    logs = home / 'logs' / (tid + '-' + stamp)
    logs.mkdir(parents=True)
    branch = 'infra-factory/' + tid + '-' + stamp
    try:
        if previous['attempts'] >= attempt_limit(c):
            raise FactoryError('Maximum attempt budget reached: ' + str(attempt_limit(c)))
        update(home, tid, 'RUNNING', repair_request=repair_request, branch=branch, worktree=str(work), base_sha=base,
               owner_pid=os.getpid(), owner_host=socket.gethostname(), error=None, config_hash=config_hash(c),
               attempts=previous['attempts'] + 1, head_sha=None, review_json=None, checks_json=None, pr_url=None)
        with GIT_LOCK:
            git(repo, 'worktree', 'add', '-b', branch, str(work), base)
        builder_spec = c['commands'][builder_key(c, ticket)]
        prompt = builder_prompt(c, ticket, previous, home, repair, builder_spec)
        run_agent(builder_spec, work, logs / 'builder-prompt.txt', logs / 'builder-result.json',
                  logs / 'builder.log', c['timeout_seconds'], prompt)
        builder_routing = routing_evidence(logs / 'builder-result.json', builder_spec)
        if builder_routing:
            with connect(home) as con:
                record(con, tid, 'RUNNING', {'action': 'builder_routing', 'command': builder_key(c, ticket),
                                             'routing': builder_routing})
        if not scoped(work, ticket, base):
            raise FactoryError('Builder produced no changes')
        with GIT_LOCK:
            git(work, 'add', '--all')
            # An empty hooks directory plus --no-verify: repository hooks must not restage
            # or amend the candidate. Scope is still checked with rename detection off.
            empty_hooks = home / 'empty-hooks'
            empty_hooks.mkdir(exist_ok=True)
            git(work, '-c', 'core.hooksPath=' + str(empty_hooks), 'commit', '--no-verify', '-m', f"{tid}: {ticket['title']}")
        head = git(work, 'rev-parse', 'HEAD')
        if dirty(work):
            raise FactoryError('Candidate checkout is dirty after commit')
        # Hooks must not introduce commits or edits outside the declared paths.
        if git(work, 'rev-parse', 'HEAD^') != base:
            raise FactoryError('Candidate is not exactly one commit above base')
        assert_committed_scope(work, ticket, base, head)
        guard_verification_inputs(work, ticket, base, head, c, source_repo=repo)
        validate_handoff(work, ticket, required=c.get('workflow') == 'egm')
        update(home, tid, 'REVIEWING', head_sha=head)
        files = diff_paths(work, base, head)
        policy = c.get('review_policy', {})
        selected_lenses = review_policy.lenses(policy, files)
        def review_lens(lens):
            checkout = Path(str(review_work) + '-' + lens)
            clone_candidate(repo, checkout, head, base)
            with VERIFY_LOCK:
                evidence = cold_checks(checkout, logs / ('cold-' + lens), c, ticket, base, head, selected_checks)
            result = logs / ('review-' + lens + '-result.json')
            prompt = reviewer_prompt(head, base, lens, policy, result, ticket, evidence)
            reviewer_spec = reviewer_spec_for(c, ticket, lens)
            run_agent(reviewer_spec, checkout, logs / ('review-' + lens + '-prompt.txt'), result,
                      logs / ('review-' + lens + '.log'), c['timeout_seconds'], prompt)
            reviewer_routing = routing_evidence(result, reviewer_spec)
            review = json.loads(result.read_text(encoding='utf-8'))
            if review.get('verdict') not in ('PASS', 'CHANGES_REQUIRED', 'INCONCLUSIVE') or not isinstance(review.get('findings'), list):
                raise FactoryError('Malformed review result')
            if review.get('reviewed_head') != head or review.get('base') != base:
                raise FactoryError('Review identity does not match exact candidate/base')
            if review['verdict'] == 'PASS' and review['findings']:
                raise FactoryError('PASS must have an empty findings array; unresolved findings require a non-PASS verdict')
            validate_review_evidence(review, evidence, ticket)
            check_evidence_files(evidence)
            if dirty(checkout) or git(checkout, 'rev-parse', 'HEAD') != head:
                raise FactoryError('Reviewer altered review checkout')
            review['artifact'] = {'file': str(result), 'sha256': sha_file(result)}
            review['evidence'] = evidence
            if reviewer_routing:
                review['routing'] = reviewer_routing
            return review
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as reviewers:
            jobs = {lens: reviewers.submit(review_lens, lens) for lens in selected_lenses}
            reviews = {lens: job.result() for lens, job in jobs.items()}
        verdicts = {r['verdict'] for r in reviews.values()}
        review = {'verdict': 'PASS' if verdicts == {'PASS'} else 'CHANGES_REQUIRED' if 'CHANGES_REQUIRED' in verdicts else 'INCONCLUSIVE',
                  'reviewed_head': head, 'base': base, 'findings': [f for r in reviews.values() for f in r['findings']], 'lenses': reviews}
        if policy.get('risk') is not None:
            checkout = Path(str(review_work) + '-risk')
            clone_candidate(repo, checkout, head, base)
            result = logs / 'risk-result.json'
            prompt = risk_prompt(head, base, result, ticket, files)
            spec = c['commands']['risk_assessor']
            run_agent(spec, checkout, logs / 'risk-prompt.txt', result, logs / 'risk.log', c['timeout_seconds'], prompt)
            risk = review_policy.assess(policy, json.loads(result.read_text(encoding='utf-8')), files, head, base, ticket['role'] == 'critical')
            routing = routing_evidence(result, spec)
            if routing:
                risk['routing'] = routing
            risk['artifact'] = {'file': str(result), 'sha256': sha_file(result)}
            risk['digest'] = config_hash(risk)
            if dirty(checkout) or git(checkout, 'rev-parse', 'HEAD') != head:
                raise FactoryError('Risk assessor altered checkout')
            review['risk'] = risk
        if dirty(work) or git(work, 'rev-parse', 'HEAD') != head:
            raise FactoryError('Builder checkout changed during review')
        if git(repo, 'rev-parse', c['base_ref']) != base or dirty(repo, allow_config=True):
            raise FactoryError('Base checkout/ref changed during execution')
        if toolchain_identity(c) != tools_before:
            raise FactoryError('External commands or skill content changed during execution')
        if config_hash(config(repo)) != config_hash(c):
            raise FactoryError('Configuration changed during execution')
        checks = json.dumps({'head': head, 'policy': config_hash(c), 'cold': {k: v['evidence']['digest'] for k, v in reviews.items()}})
        if review['verdict'] != 'PASS':
            update(home, tid, 'BLOCKED', review_json=json.dumps(review), checks_json=checks, error='Review verdict: ' + review['verdict'])
        else:
            state = 'READY' if review_policy.approved(review, head, config_hash(c)) else 'AWAITING_HUMAN'
            update(home, tid, state, review_json=json.dumps(review), checks_json=checks, error=None)
    except Exception as exc:
        update(home, tid, 'BLOCKED', error=f'{type(exc).__name__}: {exc}')


def select_tickets(rows, limit, waiting=None):
    """Pick dispatchable tickets; explain every PENDING ticket left behind in waiting."""
    waiting = {} if waiting is None else waiting
    states = {r['id']: r['state'] for r in rows}
    # An unmerged candidate still owns its paths: a second candidate from the same
    # base over the same files would be reviewed against code that is about to change.
    held = {r['id']: json.loads(r['ticket']).get('paths', []) for r in rows
            if reserved(r)}
    selected = []
    for row in rows:
        if row['state'] != 'PENDING':
            continue
        if row.get('hold_reason') is not None:
            waiting[row['id']] = 'ticket is held: ' + row['hold_reason']
            continue
        t = json.loads(row['ticket'])
        try:
            validate_spec(t)
        except ValueError as exc:
            waiting[row['id']] = f'invalid ticket ({exc}); add a corrected ticket that declares "supersedes": ["{row["id"]}"]'
            continue
        # Dependencies must actually be merged into the base, not merely reviewed.
        unmet = [d + '=' + str(states.get(d)) for d in t['depends_on'] if states.get(d) != 'MERGED']
        if unmet:
            waiting[row['id']] = 'dependencies not merged into base: ' + ', '.join(unmet)
            continue
        clash = [i for i, paths in held.items() if overlap(t['paths'], paths)] + [x['id'] for x in selected if overlap(t['paths'], x['paths'])]
        if clash:
            waiting[row['id']] = 'paths overlap unmerged/in-flight ticket(s): ' + ', '.join(clash)
            continue
        if len(selected) == limit:
            waiting[row['id']] = 'parallel limit reached'
            continue
        selected.append(t)
    return selected

