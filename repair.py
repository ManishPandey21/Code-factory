"""Bounded explicit repairs using controller reviews or allowlisted GitHub CI."""
import json
from pathlib import Path
import re
import subprocess
import time


def validate_policy(policy):
    if policy is None:
        return
    if (not isinstance(policy, dict) or set(policy) - {'max_repairs', 'github'} or
            type(policy.get('max_repairs')) is not int or not 1 <= policy['max_repairs'] <= 2):
        raise ValueError('repair_policy requires max_repairs between 1 and 2')
    github = policy.get('github')
    if github is not None:
        if (not isinstance(github, dict) or set(github) != {'repository', 'workflow_ids'} or
                not isinstance(github['repository'], str) or
                not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', github['repository']) or
                not isinstance(github['workflow_ids'], list) or not github['workflow_ids'] or
                any(type(x) is not int or x <= 0 for x in github['workflow_ids'])):
            raise ValueError('GitHub repair requires repository and positive workflow_ids allowlist')


def api(path):
    # gh inherits the operator's existing authentication; no tokens are persisted.
    result = subprocess.run(['gh', 'api', path], capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError('GitHub API request failed; no repair started')
    if len(result.stdout) > 4 * 1024 * 1024:
        raise ValueError('GitHub response exceeds repair evidence limit')
    return json.loads(result.stdout)


def github_findings(policy, run_id, head, fetch=api):
    if type(run_id) is not int or run_id <= 0:
        raise ValueError('GitHub repair needs a positive --run-id')
    repo = policy['repository']
    path = f'repos/{repo}/actions/runs/{run_id}'
    run = fetch(path)
    def identity(r):
        return {k: r.get(k) for k in ('id', 'head_sha', 'workflow_id', 'repository', 'head_repository',
                                    'event', 'status', 'conclusion', 'run_attempt', 'updated_at')}
    if (run.get('id') != run_id or run.get('head_sha') != head or
            run.get('workflow_id') not in policy['workflow_ids'] or
            run.get('repository', {}).get('full_name', '').lower() != repo.lower() or
            run.get('head_repository', {}).get('full_name', '').lower() != repo.lower() or
            run.get('event') not in ('push', 'pull_request') or run.get('status') != 'completed' or
            run.get('conclusion') not in ('failure', 'timed_out') or
            type(run.get('run_attempt')) is not int or run['run_attempt'] < 1):
        raise ValueError('CI source is not an allowed failed workflow for the exact candidate')
    jobs, pages = [], []
    for page in range(1, 11):
        response = fetch(path + f"/attempts/{run['run_attempt']}/jobs?per_page=100&page={page}")
        batch = response.get('jobs')
        if not isinstance(batch, list):
            raise ValueError('Malformed CI jobs response')
        pages.append(response)
        for job in batch:
            if (job.get('head_sha') != head or job.get('run_id') != run_id or
                    job.get('run_attempt') != run['run_attempt'] or job.get('status') != 'completed'):
                raise ValueError('CI job identity or completion mismatch')
            if job.get('conclusion') in ('failure', 'timed_out'):
                jobs.append({'job': job.get('name'), 'conclusion': job['conclusion'],
                             'steps': [s.get('name') for s in job.get('steps', [])
                                       if s.get('conclusion') in ('failure', 'timed_out')]})
        if len(batch) < 100:
            break
    else:
        raise ValueError('CI run exceeds bounded job pagination')
    if not jobs or identity(fetch(path)) != identity(run):
        raise ValueError('CI run changed while fetching, or has no failed jobs')
    return {'source': 'github', 'head': head, 'repository': repo, 'run_id': run_id,
            'run_attempt': run['run_attempt'], 'workflow_id': run['workflow_id'], 'findings': jobs}, {'run': run, 'pages': pages}


def repair_candidate(f, repo, home, c, args):
    """Caller holds coordinator lock. One fresh attempt per explicit invocation."""
    policy = c.get('repair_policy')
    validate_policy(policy)
    if policy is None:
        raise ValueError('Configure repair_policy before requesting repair')
    with f.connect(home) as con:
        f.require_unheld(con, args.ticket)
        row = con.execute('SELECT * FROM tickets WHERE id=?', (args.ticket,)).fetchone()
        rows = [dict(r) for r in con.execute('SELECT * FROM tickets')]
        for other in rows:
            other.update(f.control(con, other['id']))
    if not row or row['state'] not in ('BLOCKED', 'READY', 'AWAITING_HUMAN') or row['head_sha'] != args.head:
        raise ValueError('Repair requires the exact inactive candidate head')
    if row['attempts'] >= min(f.MAX_ATTEMPTS, policy['max_repairs'] + 1):
        raise ValueError('Repair/attempt budget exhausted; history cannot be reset')
    ticket = json.loads(row['ticket'])
    for other in rows:
        if other['id'] == args.ticket:
            continue
        if other['state'] in ('RUNNING', 'REVIEWING'):
            raise ValueError('Recover stale in-flight work before repair')
        if ((other['state'] in ('READY', 'AWAITING_HUMAN') or other['hold_reason'] is not None) and
                f.overlap(ticket['paths'], json.loads(other['ticket'])['paths'])):
            raise ValueError('Repair paths overlap another reserved ticket')
    review = f.verify_candidate(repo, c, row, require_pass=False, require_approval=False)
    raw = None
    if args.source == 'review':
        if args.run_id is not None:
            raise ValueError('--run-id applies only to GitHub sources')
        if review.get('verdict') != 'CHANGES_REQUIRED':
            raise ValueError('Repair requires a recorded CHANGES_REQUIRED review')
        findings = [{'lens': name, 'findings': r['findings']} for name, r in review['lenses'].items()
                    if r['verdict'] == 'CHANGES_REQUIRED' and r['findings']]
        if not findings:
            raise ValueError('No actionable recorded review findings')
        evidence = {'source': 'review', 'head': args.head, 'findings': findings,
                    'review_digest': f.config_hash(review)}
    else:
        if not policy.get('github'):
            raise ValueError('GitHub repair requires an explicit workflow allowlist')
        evidence, raw = github_findings(policy['github'], args.run_id, args.head)
    f.validate_policy(c, ticket)
    f.validate_handoff(repo, ticket, required=c.get('workflow') == 'egm')
    for spec in [c['commands'][f.builder_key(c, ticket)], f.reviewer_spec_for(c, ticket, 'standards'),
                 f.reviewer_spec_for(c, ticket, 'spec')] + [c['commands'][r] for r in
                 f.review_policy.required_commands(c.get('review_policy', {}))]:
        f.command(spec, {})
    print(json.dumps({'dry_run': not args.execute, 'ticket': args.ticket, 'candidate': args.head,
                      'source': args.source, 'attempts_used': row['attempts'], 'findings': evidence['findings']}), flush=True)
    if not args.execute:
        return 0
    # Recheck immediately before consuming a repair; fetching remote CI can take time.
    f.verify_candidate(repo, c, row, require_pass=False, require_approval=False)
    if f.config_hash(f.config(repo)) != f.config_hash(c):
        raise ValueError('Configuration changed during repair preflight')
    receipt = home / 'logs' / ('repair-' + str(time.time_ns()) + '.json')
    receipt.parent.mkdir(exist_ok=True)
    receipt.write_text(json.dumps({'evidence': evidence, 'github': raw}, indent=2))
    with f.connect(home) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS repair_requests (
            ticket_id TEXT NOT NULL, head TEXT NOT NULL, receipt TEXT NOT NULL,
            PRIMARY KEY(ticket_id,head))''')
        con.execute('INSERT INTO repair_requests VALUES(?,?,?)', (args.ticket, args.head, str(receipt)))
        f.record(con, args.ticket, row['state'], {'action': 'repair', 'head': args.head,
                 'source': args.source, 'receipt': str(receipt), 'sha256': f.sha_file(receipt)})
    f.execute_ticket(repo, home, c, ticket, row['base_sha'], repair=evidence)
    with f.connect(home) as con:
        state = con.execute('SELECT state FROM tickets WHERE id=?', (args.ticket,)).fetchone()[0]
    print(json.dumps({'ticket': args.ticket, 'state': state}))
    return 0 if state in ('READY', 'AWAITING_HUMAN') else 1
