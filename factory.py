#!/usr/bin/env python3
"""CLI entry point and guarded draft publication."""
from __future__ import annotations
import argparse
import concurrent.futures
import json
import re
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import review_policy
from runtime_requirements import require_git_version
from ticket_controls import control, require_unheld, change_control
from skill_inventory import helper_prompt
from egm import validate_handoff
from verification_policy import validate_policy

from runtime import ACTIVE, CLI_SLOTS, COMPLEXITIES, FactoryError, GIT_LOCK, MAX_ATTEMPTS, STOP, TransientError, VERIFY_LOCK, alive, assert_committed_scope, attempt_limit, changed_entries, command, config, config_hash, default_config, diff_paths, dirty, git, interrupt, invoke, kill_tree, locations, lock, overlap, protected, reserved, run_agent, scoped, within
from records import add_ticket, connect, inherited_attempts, initialize_db, record, reject_dependency_cycle, update, validate_ticket
from dispatch import builder_key, execute_ticket, reviewer_spec_for, routing_evidence, select_tickets, strict_routing
from evidence import MANIFESTS, TEST_DIRS, acceptance_items, check_evidence_files, cold_checks, guard_verification_inputs, refuse_links, sha_file, toolchain_identity, validate_review_evidence, verification_sensitive, verify_candidate


def publish(repo, home, c, ticket_id, execute):
    with connect(home) as con:
        require_unheld(con, ticket_id)
        row = con.execute('SELECT * FROM tickets WHERE id=?', (ticket_id,)).fetchone()
        from issue_intake import issue_link
        source_issue = issue_link(con, ticket_id)
    if source_issue:
        from issue_intake import origin_repository
        if origin_repository(repo) != source_issue['repository']:
            raise FactoryError('Linked issue repository no longer matches origin')
    if not row or row['state'] != 'READY':
        raise FactoryError('Only READY tickets may be published')
    review = verify_candidate(repo, c, row)
    checks = json.loads(row['checks_json'])
    head, base, branch = row['head_sha'], row['base_sha'], row['branch']
    work = Path(row['worktree'])
    print(json.dumps({'dry_run': not execute, 'ticket': ticket_id, 'head': head, 'base': base, 'branch': branch, 'draft': True,
                      'source_issue': source_issue['url'] if source_issue else None}), flush=True)
    if not execute:
        return 0
    logs = home / 'logs' / ('publish-' + ticket_id + '-' + str(time.time_ns()))
    logs.mkdir(parents=True)
    pushed = False
    try:
        def remote(args, output):
            # stdout is parsed, so stderr (SSH host-key warnings, gh update notices) is kept apart.
            try:
                invoke(args, repo, output, c['timeout_seconds'], split_stderr=True)
            except (FactoryError, OSError, subprocess.SubprocessError) as exc:
                raise TransientError(f'{args[0]} {args[1]} failed: {exc}') from exc
        def verify_remote_base(label):
            output = logs / ('remote-base-' + label + '.txt')
            remote_ref = c['base_ref'] if c['base_ref'].startswith('refs/heads/') else 'refs/heads/' + c['base_ref']
            remote(['git', 'ls-remote', '--exit-code', 'origin', remote_ref], output)
            lines = output.read_text(encoding='utf-8').splitlines()
            expected = base + '\t' + remote_ref
            if lines != [expected]:
                raise FactoryError('Origin base differs from reviewed base; fresh checks/review required')
        verify_remote_base('before')
        # Revalidate all risk, approval, review and test artifacts after remote access.
        verify_candidate(repo, c, row)
        if dirty(work) or git(work, 'rev-parse', 'HEAD') != head or git(repo, 'rev-parse', c['base_ref']) != base:
            raise FactoryError('Snapshot changed during publication checks')
        remote(['git', 'push', 'origin', head + ':refs/heads/' + branch], logs / 'push.log')
        pushed = True
        verify_remote_base('after-push')
        gh_repository = ['--repo', 'github.com/' + source_issue['repository']] if source_issue else []
        def lookup_pr(filename):
            output = logs / filename
            remote(['gh', 'pr', 'list', '--state', 'open', '--head', branch, '--base', c['base_ref'],
                    '--json', 'url,isDraft,headRefOid', *gh_repository], output)
            results = json.loads(output.read_text(encoding='utf-8'))
            if source_issue and (not isinstance(results, list) or any(
                    not isinstance(pr, dict) or not isinstance(pr.get('url'), str) or
                    not re.fullmatch(r'https://github\.com/' + re.escape(source_issue['repository']) +
                                     r'/pull/[1-9][0-9]*', pr['url'], re.I) for pr in results)):
                raise FactoryError('Draft PR repository differs from linked issue/origin')
            return results
        prs = lookup_pr('pr-lookup.json')
        if prs:
            if len(prs) != 1 or not prs[0]['isDraft'] or prs[0]['headRefOid'] != head:
                raise FactoryError('Existing PR is not a unique draft at the reviewed commit')
            url = prs[0]['url']
        else:
            t = json.loads(row['ticket'])
            body = logs / 'pr-body.md'
            body.write_text(f"Ticket: {ticket_id}\n\nCandidate: {head}\nBase: {base}\n\n"
                            'LOCAL verification only: independently executed policy-selected tests and every policy-selected cold review passed on this exact commit.\n\n'
                            'Evidence digests: ' + ', '.join(checks['cold'].values()) + '\n\n'
                            'This draft requires human review and merge. No automatic merge is enabled.\n' +
                            ('\nRefs ' + source_issue['url'] + '\n' if source_issue else ''), encoding='utf-8')
            remote(['gh', 'pr', 'create', '--draft', '--base', c['base_ref'], '--head', branch,
                    '--title', (ticket_id + ': ' + t['title']).replace('\n', ' ')[:200], '--body-file', str(body), *gh_repository],
                   logs / 'pr-create.log')
            prs = lookup_pr('pr-verify.json')
            if len(prs) != 1 or not prs[0]['isDraft'] or prs[0]['headRefOid'] != head:
                raise FactoryError('Draft creation result could not be verified')
            url = prs[0]['url']
        verify_remote_base('after-pr')
        if dirty(work) or git(work, 'rev-parse', 'HEAD') != head or git(repo, 'rev-parse', c['base_ref']) != base:
            raise FactoryError('Local snapshot changed during publication; remote draft may exist')
        verify_candidate(repo, c, row)
        update(home, ticket_id, 'READY', pr_url=url, error=None)
        print(json.dumps({'draft_pr': url, 'head': head}))
        return 0
    except TransientError as exc:
        # A network/auth/CLI failure says nothing about the candidate. Keep READY so the
        # owner can fix the transport and rerun publish, which re-validates everything.
        message = ('Publication incomplete: branch was pushed but the draft PR is unconfirmed; rerun publish. ' if pushed
                   else 'Publication did not start. ') + str(exc) + ' Local verification retained.'
        update(home, ticket_id, 'READY', error=message)
        raise TransientError(message)
    except Exception as exc:
        message = ('Publication partial: branch was pushed; inspect remote/PR before retry. ' if pushed else 'Publication failed before confirmed push. ') + str(exc)
        update(home, ticket_id, 'BLOCKED', error=message)
        raise FactoryError(message)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='action', required=True)
    for name in ('init', 'add', 'status', 'run', 'recover', 'unlock', 'publish', 'retry', 'reject', 'hold', 'release', 'approve', 'repair', 'events', 'dashboard', 'intake', 'link-issue'):
        p = subs.add_parser(name)
        p.add_argument('--repo', required=True)
        if name == 'init':
            p.add_argument('--apply', action='store_true')
        if name in ('add', 'recover', 'publish', 'retry', 'reject', 'hold', 'release', 'approve', 'repair', 'intake', 'link-issue'):
            p.add_argument('--ticket', required=True)
        if name in ('intake', 'link-issue'):
            p.add_argument('--issue', required=True, help='Canonical GitHub Issue URL')
        if name == 'add':
            p.add_argument('--idempotent', action='store_true')
        if name in ('hold', 'release'):
            p.add_argument('--hold-version', type=int, required=True)
            p.add_argument('--reason', required=True)
        if name in ('run', 'publish', 'repair', 'intake', 'link-issue'):
            p.add_argument('--execute', action='store_true')
        if name in ('approve', 'repair'):
            p.add_argument('--head', required=True)
        if name == 'approve':
            p.add_argument('--risk-digest', required=True)
            p.add_argument('--reviewer', required=True)
            p.add_argument('--note', required=True)
        if name == 'repair':
            p.add_argument('--source', choices=('review', 'github'), required=True)
            p.add_argument('--run-id', type=int)
        if name == 'events':
            p.add_argument('--after', type=int, default=0)
            p.add_argument('--limit', type=int, default=100)
            p.add_argument('--follow', action='store_true')
        if name == 'dashboard':
            p.add_argument('--port', type=int, default=8765)
        if name == 'run':
            p.add_argument('--limit', type=int, default=2)
    args = parser.parse_args(argv)
    require_git_version()
    repo, home = locations(args.repo)
    from usage_trace import traced
    return traced(home, args, lambda: dispatch_command(args, repo, home))


def dispatch_command(args, repo, home):
    git(repo, 'rev-parse', '--verify', 'HEAD')
    cfg = repo / '.infra-factory/config.json'
    if args.action == 'init':
        if not args.apply:
            print(json.dumps({'dry_run': True, 'config': str(cfg), 'state_directory': str(home), 'defaults': default_config(repo)}, indent=2))
            return 0
        home.mkdir(parents=True, exist_ok=True)
        with lock(home):
            cfg.parent.mkdir(exist_ok=True)
            if not cfg.exists():
                with cfg.open('x', encoding='utf-8') as f:
                    json.dump(default_config(repo), f, indent=2)
            initialize_db(home)
        print('Initialized; configure nonempty checks and authenticated CLI commands before execution.')
        return 0
    if (not (home / 'ledger.sqlite3').exists() or
            (not cfg.exists() and args.action not in ('status', 'hold', 'release', 'events', 'dashboard'))):
        raise FactoryError('Run init --apply first')
    if args.action in ('events', 'dashboard'):
        from ledger_view import serve, events
        if args.action == 'dashboard':
            serve(home, args.port, repo=repo)
        else:
            events(home, args.after, args.limit, args.follow, repo=repo)
        return 0
    if args.action in ('hold', 'release'):
        with lock(home), connect(home) as con:
            state, controls = change_control(con, args.ticket, args.hold_version, args.reason,
                                             release=args.action == 'release')
            record(con, args.ticket, state, {'action': args.action, 'reason': args.reason, **controls})
        print(json.dumps({'id': args.ticket, **controls}))
        return 0
    config_error = None
    try:
        c = config(repo)
    except (FactoryError, OSError, ValueError, KeyError, TypeError) as exc:
        if args.action != 'status':
            raise
        c, config_error = None, str(exc)
    if args.action == 'status':
        with connect(home) as con:
            rows = [dict(r) for r in con.execute('SELECT * FROM tickets ORDER BY updated,id')]
            for row in rows:
                row.update(control(con, row['id']))
                from issue_intake import issue_link
                row['source_issue'] = issue_link(con, row['id'])
                row['publication_held'] = row['hold_reason'] is not None
        for row in rows:
            row['ticket'] = json.loads(row['ticket'])
            row['verification_current'] = False
            if row['state'] in ('READY', 'AWAITING_HUMAN') and c is not None:
                try:
                    snapshot = dict(row, ticket=json.dumps(row['ticket']))
                    verify_candidate(repo, c, snapshot, require_approval=row['state'] == 'READY')
                    row['verification_current'] = True
                except (AssertionError, FactoryError, OSError, KeyError, ValueError, TypeError):
                    pass
            if row['review_json']:
                row['review_json'] = json.loads(row['review_json'])
        print(json.dumps({'tickets': rows, 'coordinator_locked': (home / 'coordinator.lock').exists(),
                          'configuration_error': config_error}, indent=2))
        return 0
    if args.action == 'unlock':
        # A killed controller can leave coordinator.lock behind with no RUNNING ticket
        # (for example during add/retry/publish); recover cannot clear that case.
        with lock(home, 'recovery.lock'):
            target = home / 'coordinator.lock'
            if not target.exists():
                print('No coordinator lock is present.')
                return 0
            try:
                owner = json.loads(target.read_text(encoding='utf-8'))
            except ValueError:
                owner = None
            if (not isinstance(owner, dict) or owner.get('host') != socket.gethostname()
                    or type(owner.get('pid')) is not int or alive(owner['pid'])):
                raise FactoryError('Lock owner is alive or cannot be verified local; refusing to unlock')
            with connect(home) as con:
                stale = [r['id'] for r in con.execute("SELECT id FROM tickets WHERE state IN ('RUNNING','REVIEWING')")]
            if stale:
                raise FactoryError('Tickets still marked in flight: ' + ', '.join(stale) + '; use recover --ticket ID for each')
            target.unlink()
        print('Removed the stale coordinator lock; no ticket or process was altered.')
        return 0
    if args.action == 'recover':
        # A second recovery must not unlink a newly acquired coordinator lock.
        with lock(home, 'recovery.lock'):
            with connect(home) as con:
                row = con.execute('SELECT * FROM tickets WHERE id=?', (args.ticket,)).fetchone()
            if not row or row['state'] not in ('RUNNING', 'REVIEWING'):
                raise FactoryError('Recovery applies only to stale RUNNING/REVIEWING tickets')
            if row['owner_host'] != socket.gethostname() or alive(row['owner_pid']):
                raise FactoryError('Ticket owner is alive or unknown; refusing recovery')
            target = home / 'coordinator.lock'
            if target.exists():
                owner = json.loads(target.read_text(encoding='utf-8'))
                if owner.get('host') != socket.gethostname() or alive(owner.get('pid')):
                    raise FactoryError('Lock owner is alive or cannot be verified local; refusing recovery')
                target.unlink()
            with lock(home), connect(home) as con:
                con.execute("UPDATE tickets SET state='BLOCKED', error=?, updated=? WHERE id=? AND state IN ('RUNNING','REVIEWING')", ('Recovered stale task; inspect retained worktree and logs manually. No process was killed.', time.time(), args.ticket))
                record(con, args.ticket, 'BLOCKED', {'action': 'recover', 'from': row['state']})
        print('Recovered to BLOCKED; retained files and processes were not altered.')
        return 0
    with lock(home):
        if args.action in ('intake', 'link-issue'):
            from issue_intake import intake
            print(json.dumps(intake(repo, home, c, args)))
            return 0
        if args.action == 'approve':
            with connect(home) as con:
                require_unheld(con, args.ticket)
                row = con.execute('SELECT * FROM tickets WHERE id=?', (args.ticket,)).fetchone()
            if not row or row['state'] != 'AWAITING_HUMAN' or row['head_sha'] != args.head:
                raise FactoryError('Approval requires the exact AWAITING_HUMAN candidate')
            review = verify_candidate(repo, c, row, require_approval=False)
            if review.get('risk', {}).get('digest') != args.risk_digest:
                raise FactoryError('Risk digest changed')
            if not args.reviewer.strip() or not args.note.strip():
                raise FactoryError('Human reviewer and approval note must be nonempty')
            review['human_approval'] = {'head': args.head, 'risk_digest': args.risk_digest,
                'policy': config_hash(c), 'reviewer': args.reviewer.strip(), 'note': args.note.strip(), 'at': time.time()}
            update(home, args.ticket, 'READY', review_json=json.dumps(review), error=None)
            print(json.dumps({'id': args.ticket, 'head': args.head, 'state': 'READY'}))
            return 0
        if args.action == 'repair':
            from repair import repair_candidate
            return repair_candidate(sys.modules[__name__], repo, home, c, args)
        if args.action == 'reject':
            with connect(home) as con:
                require_unheld(con, args.ticket)
                row = con.execute('SELECT * FROM tickets WHERE id=?', (args.ticket,)).fetchone()
            if not row or row['state'] not in ('PENDING', 'BLOCKED', 'READY', 'AWAITING_HUMAN'):
                raise FactoryError('Reject applies only to inactive unmerged tickets')
            if row['head_sha']:
                merged = subprocess.run(['git', '-C', str(repo), 'merge-base', '--is-ancestor', row['head_sha'], c['base_ref']], timeout=60).returncode
                if merged != 1:
                    raise FactoryError('Candidate merged or ancestry unavailable; explicit revert ticket required')
            update(home, args.ticket, 'REJECTED', error='Candidate rejected; base and evidence retained. Remote draft, if any, must be closed separately.')
            print('Rejected without modifying base or deleting work. This is not a production rollback.')
            return 0
        if args.action == 'retry':
            with connect(home) as con:
                require_unheld(con, args.ticket)
                row = con.execute('SELECT * FROM tickets WHERE id=?', (args.ticket,)).fetchone()
                if not row or row['state'] != 'BLOCKED':
                    raise FactoryError('Only BLOCKED tickets may be explicitly retried')
                if row['attempts'] >= attempt_limit(c):
                    raise FactoryError('Maximum attempt budget reached; a replacement inherits this history')
                con.execute("UPDATE tickets SET state='PENDING',updated=? WHERE id=?", (time.time(), args.ticket))
                record(con, args.ticket, 'PENDING', {'action': 'retry', 'attempts_used': row['attempts']})
            print(json.dumps({'id': args.ticket, 'state': 'PENDING', 'attempts_used': row['attempts'], 'maximum_attempts': attempt_limit(c)}))
            return 0
        if args.action == 'publish':
            with connect(home) as con:
                require_unheld(con, args.ticket)
            try:
                return publish(repo, home, c, args.ticket, args.execute)
            except TransientError:
                raise
            except Exception as exc:
                if args.execute:
                    with connect(home) as con:
                        row = con.execute('SELECT state FROM tickets WHERE id=?', (args.ticket,)).fetchone()
                    if row and row['state'] == 'READY':
                        update(home, args.ticket, 'BLOCKED', error='Publication eligibility revoked: ' + str(exc))
                raise
        if args.action == 'add':
            t = validate_ticket(json.loads(Path(args.ticket).read_text(encoding='utf-8')))
            validate_handoff(repo, t, required=c.get('workflow') == 'egm')
            with connect(home) as con:
                reply = add_ticket(con, c, t, idempotent=args.idempotent)
            print(json.dumps(reply))
            return 0
        if not 1 <= args.limit <= 2:
            raise FactoryError('limit must be 1 or 2')
        base = git(repo, 'rev-parse', c['base_ref'])
        if git(repo, 'rev-parse', 'HEAD') != base or dirty(repo, allow_config=True):
            raise FactoryError('Base checkout must be clean and HEAD must equal configured base_ref')
        with connect(home) as con:
            # Manual merges are recognized only by exact candidate ancestry.
            rows = [dict(r) for r in con.execute('SELECT * FROM tickets ORDER BY updated,id')]
            for row in rows:
                row.update(control(con, row['id']))
                from issue_intake import issue_link
                row['source_issue'] = issue_link(con, row['id'])
                # A merged head is merged even if review had already blocked it.
                # Do not rewrite an unmerged BLOCKED ticket back to READY.
                if row['state'] in ('READY', 'AWAITING_HUMAN', 'BLOCKED', 'MERGED') and row['head_sha']:
                    p = subprocess.run(['git', '-C', str(repo), 'merge-base', '--is-ancestor', row['head_sha'], base], capture_output=True)
                    if p.returncode not in (0, 1):
                        raise FactoryError('Cannot verify dependency ancestry')
                    if p.returncode == 0 and row['state'] != 'MERGED':
                        row['state'] = 'MERGED'
                        if args.execute:
                            con.execute('UPDATE tickets SET state=?,updated=? WHERE id=?', ('MERGED', time.time(), row['id']))
                            record(con, row['id'], 'MERGED', {'action': 'ancestry', 'base': base})
                    elif p.returncode == 1 and row['state'] == 'MERGED':
                        row['state'] = 'READY'
                        if args.execute:
                            con.execute('UPDATE tickets SET state=?,updated=? WHERE id=?', ('READY', time.time(), row['id']))
                            record(con, row['id'], 'READY', {'action': 'ancestry', 'base': base})
        if any(r['state'] in ('RUNNING', 'REVIEWING') for r in rows):
            raise FactoryError('Stale running tasks require explicit recover before another run')
        # Fail before any agent is paid for, not after the builder has finished.
        refuse_links(repo, base)
        waiting = {}
        selected = select_tickets(rows, min(args.limit, c['max_parallel']), waiting)
        print(json.dumps({'dry_run': not args.execute, 'base': base, 'selected': [t['id'] for t in selected], 'waiting': waiting}), flush=True)
        if not args.execute:
            return 0
        if not isinstance(c.get('checks'), list) or not c['checks']:
            raise FactoryError('Configure at least one check argv; missing checks are never green')
        for ticket in selected:
            attempts = next(r['attempts'] for r in rows if r['id'] == ticket['id'])
            if attempts >= attempt_limit(c):
                raise FactoryError('Maximum attempt budget reached for ' + ticket['id'])
            validate_handoff(repo, ticket, required=c.get('workflow') == 'egm')
            validate_policy(c, ticket)
        for check in c['checks']:
            command({'argv': check}, {})
        for role in review_policy.required_commands(c.get('review_policy', {})):
            command(c['commands'][role], {})
        for t in selected:
            for lens in ('standards', 'spec'):
                command(reviewer_spec_for(c, t, lens), {})
        for role in {builder_key(c, t) for t in selected}:
            command(c['commands'][role], {})
            helper_prompt(c['commands'][role])
            if role != 'reviewer':
                skill = Path(c['commands'][role].get('primary_skill', ''))
                if not skill.is_absolute() or not skill.is_file():
                    raise FactoryError(f'Configure an existing absolute primary_skill path for {role}')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(execute_ticket, repo, home, c, t, base) for t in selected]
            for future in futures:
                future.result()
        with connect(home) as con:
            outcomes = {t['id']: con.execute('SELECT state FROM tickets WHERE id=?', (t['id'],)).fetchone()['state'] for t in selected}
        print(json.dumps({'outcomes': outcomes}, indent=2))
        return 1 if any(s not in ('READY', 'AWAITING_HUMAN') for s in outcomes.values()) else 0


if __name__ == '__main__':
    for _signal in (signal.SIGINT, signal.SIGTERM):
        signal.signal(_signal, interrupt)
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('factory: interrupted; owned child processes were killed and the lock released. '
              'Tickets that were in flight are BLOCKED and count as an attempt.', file=sys.stderr)
        sys.exit(130)
    except (FactoryError, OSError, ValueError, KeyError, TypeError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f'factory: {exc}', file=sys.stderr)
        sys.exit(2)
