"""Read-only GitHub Issue intake with atomic local ticket/source linkage.

Issue text is retained as untrusted source data, never interpreted as ticket
scope or workflow instructions. The caller must hold the coordinator lock.
"""
import json
from pathlib import Path
import re
import subprocess

from egm import validate_handoff
from records import add_ticket, connect, record, validate_ticket
from runtime import FactoryError, config_hash, git
from ticket_controls import require_unheld

_REPO = r'([A-Za-z0-9_-][A-Za-z0-9_.-]*)/([A-Za-z0-9_-][A-Za-z0-9_.-]*)'


def issue_identity(url):
    match = re.fullmatch(r'https://github\.com/' + _REPO + r'/issues/([1-9][0-9]*)', url)
    if not match:
        raise FactoryError('Use a canonical https://github.com/OWNER/REPO/issues/NUMBER URL')
    repository = (match[1] + '/' + match[2]).lower()
    number = int(match[3])
    return repository, number, f'https://github.com/{repository}/issues/{number}'


def origin_repository(repo):
    origin = git(repo, 'remote', 'get-url', 'origin')
    for prefix in ('https://github.com/', 'git@github.com:', 'ssh://git@github.com/'):
        if origin.startswith(prefix):
            name = origin[len(prefix):].removesuffix('.git')
            if re.fullmatch(_REPO, name):
                return name.lower()
    raise FactoryError('Issue intake requires a GitHub origin with an unambiguous owner/repository')


def fetch_issue(repository, number):
    # Explicit hostname prevents GH_HOST redirecting an otherwise canonical URL.
    result = subprocess.run(['gh', 'api', '--hostname', 'github.com',
                             f'repos/{repository}/issues/{number}'],
                            capture_output=True, timeout=60)
    if result.returncode:
        raise FactoryError('GitHub Issue lookup failed; no ticket/link changed')
    if len(result.stdout) > 1024 * 1024:
        raise FactoryError('GitHub Issue response exceeds 1 MiB')
    return json.loads(result.stdout)


def source_snapshot(repo, url):
    repository, number, canonical = issue_identity(url)
    if origin_repository(repo) != repository:
        raise FactoryError('Issue repository does not match origin')
    data = fetch_issue(repository, number)
    if (not isinstance(data, dict) or 'pull_request' in data or
            type(data.get('number')) is not int or data['number'] != number or
            type(data.get('id')) is not int or data['id'] <= 0 or
            data.get('state') != 'open' or not isinstance(data.get('html_url'), str) or
            issue_identity(data['html_url'])[2] != canonical):
        raise FactoryError('Expected the exact open GitHub Issue, not a PR or redirected issue')
    for field in ('title', 'updated_at'):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise FactoryError('Issue is missing ' + field)
    if data.get('body') is not None and not isinstance(data['body'], str):
        raise FactoryError('Issue body must be text')
    snapshot = {'repository': repository, 'number': number, 'url': canonical,
                'github_id': data['id'], 'title': data['title'], 'body': data.get('body') or '',
                'updated_at': data['updated_at']}
    snapshot['digest'] = config_hash(snapshot)
    return snapshot


def issue_link(con, ticket_id):
    table = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='issue_links'").fetchone()
    row = con.execute('SELECT snapshot FROM issue_links WHERE ticket_id=?', (ticket_id,)).fetchone() if table else None
    if not row:
        return None
    snapshot = json.loads(row[0])
    payload = dict(snapshot); digest = payload.pop('digest', None)
    if digest != config_hash(payload):
        raise FactoryError('Issue snapshot digest changed')
    return snapshot


def link_issue(con, ticket_id, snapshot):
    existing = issue_link(con, ticket_id)
    if existing:
        if existing != snapshot:
            raise FactoryError('Issue link/snapshot changed; refusing to overwrite recorded provenance')
        return True
    require_unheld(con, ticket_id)
    row = con.execute('SELECT state,pr_url FROM tickets WHERE id=?', (ticket_id,)).fetchone()
    if not row or row['state'] not in ('PENDING', 'BLOCKED', 'READY', 'AWAITING_HUMAN') or row['pr_url']:
        raise FactoryError('Link issues only to inactive, unpublished tickets')
    con.execute('''CREATE TABLE IF NOT EXISTS issue_links (
        ticket_id TEXT PRIMARY KEY, issue_url TEXT NOT NULL UNIQUE,
        github_id INTEGER NOT NULL UNIQUE, snapshot TEXT NOT NULL)''')
    if con.execute('SELECT 1 FROM issue_links WHERE issue_url=? OR github_id=?',
                   (snapshot['url'], snapshot['github_id'])).fetchone():
        raise FactoryError('Issue is already linked to another ticket; reuse its existing ID')
    con.execute('INSERT INTO issue_links VALUES(?,?,?,?)',
                (ticket_id, snapshot['url'], snapshot['github_id'], json.dumps(snapshot)))
    record(con, ticket_id, row['state'], {'action': 'link_issue', 'url': snapshot['url'],
                                        'source_digest': snapshot['digest']})
    return False


def intake(repo, home, c, args):
    snapshot = source_snapshot(repo, args.issue)
    ticket = None
    if args.action == 'intake':
        ticket = validate_ticket(json.loads(Path(args.ticket).read_text(encoding='utf-8')))
        validate_handoff(repo, ticket, required=c.get('workflow') == 'egm')
    with connect(home) as con:
        # Preview executes exactly the validation/transaction path and rolls it
        # back, including table creation and events. No durable writes survive.
        con.execute('SAVEPOINT issue_intake')
        reply = add_ticket(con, c, ticket, idempotent=True) if ticket else {'id': args.ticket}
        replayed = link_issue(con, reply['id'], snapshot)
        reply.update(dry_run=not args.execute, source_issue=snapshot, link_replayed=replayed)
        if not args.execute:
            con.execute('ROLLBACK TO issue_intake')
        con.execute('RELEASE issue_intake')
    return reply
