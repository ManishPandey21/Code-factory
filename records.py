"""Ticket validation and transactional ledger records."""
from __future__ import annotations
import contextlib
import json
from pathlib import PurePosixPath
import re
import sqlite3
import time
from ticket_controls import require_unheld
from verification_policy import validate_spec

from runtime import COMPLEXITIES, FactoryError, MAX_ATTEMPTS, attempt_limit, config_hash, protected


@contextlib.contextmanager
def connect(home):
    """Commit on success, roll back on error, and always close the handle."""
    con = sqlite3.connect(home / 'ledger.sqlite3', timeout=30)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


def record(con, ticket_id, state, details):
    con.execute('INSERT INTO events(ticket_id,state,at,details) VALUES(?,?,?,?)',
                (ticket_id, state, time.time(), json.dumps(details, sort_keys=True)))


def reject_dependency_cycle(con, ticket):
    graph = {row['id']: json.loads(row['ticket']).get('depends_on', [])
             for row in con.execute('SELECT id, ticket FROM tickets')}
    graph[ticket['id']] = list(ticket['depends_on'])
    stack = []

    def visit(node):
        if node in stack:
            raise FactoryError('Dependency cycle: ' + ' -> '.join(stack + [node]))
        if node not in graph:
            return
        stack.append(node)
        for dependency in graph[node]:
            visit(dependency)
        stack.pop()
        graph.pop(node, None)

    visit(ticket['id'])


def initialize_db(home):
    with connect(home) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS tickets (
            id TEXT PRIMARY KEY, ticket TEXT NOT NULL, state TEXT NOT NULL,
            branch TEXT, worktree TEXT, base_sha TEXT, head_sha TEXT,
            review_json TEXT, error TEXT, owner_pid INTEGER, owner_host TEXT,
            updated REAL NOT NULL)''')
        con.execute('CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT NOT NULL, state TEXT NOT NULL, at REAL NOT NULL, details TEXT NOT NULL)')
        existing = {r[1] for r in con.execute('PRAGMA table_info(tickets)')}
        for column in ('config_hash', 'checks_json', 'pr_url'):
            if column not in existing:
                con.execute(f'ALTER TABLE tickets ADD COLUMN {column} TEXT')
        if 'attempts' not in existing:
            con.execute('ALTER TABLE tickets ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0')


def inherited_attempts(con, t):
    """A replacement ticket keeps the attempt history of what it replaces; renaming grants nothing."""
    inherited = 0
    for old in t.get('supersedes', []):
        require_unheld(con, old)
        row = con.execute('SELECT * FROM tickets WHERE id=?', (old,)).fetchone()
        if not row:
            raise FactoryError(f'Unknown superseded ticket: {old}')
        if row['state'] not in ('PENDING', 'BLOCKED', 'REJECTED'):
            raise FactoryError(f'{old} is {row["state"]}; only PENDING, BLOCKED or REJECTED tickets can be superseded')
        inherited = max(inherited, row['attempts'])
    declared = set(t.get('supersedes', []))
    mine = sorted(t['paths'])
    for row in con.execute("SELECT * FROM tickets WHERE state IN ('PENDING','BLOCKED','REJECTED') AND attempts > 0"):
        if row['id'] not in declared and sorted(json.loads(row['ticket']).get('paths', [])) == mine:
            raise FactoryError(f'{row["id"]} covers the same paths and has used {row["attempts"]} attempt(s); '
                               f'declare "supersedes": ["{row["id"]}"] so its attempt history carries over')
    if inherited >= MAX_ATTEMPTS:
        raise FactoryError('Superseded ticket(s) already used all attempts; '
                           'the work needs re-scoping by a person, not another attempt')
    return inherited


def validate_ticket(t):
    if not isinstance(t, dict) or not isinstance(t.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', t['id']):
        raise FactoryError('Ticket id must be 1–64 letters, numbers, underscores or hyphens')
    for key in ('title', 'description'):
        if not isinstance(t.get(key), str) or not t[key].strip():
            raise FactoryError(f'{key} must be a nonempty string')
    for key in ('acceptance', 'paths', 'depends_on'):
        if not isinstance(t.get(key), list) or any(not isinstance(x, str) or not x.strip() for x in t[key]):
            raise FactoryError(f'{key} must be a list of nonempty strings')
    if not t['acceptance'] or not t['paths']:
        raise FactoryError('acceptance and paths cannot be empty')
    if t.get('role') not in ('backend', 'frontend', 'critical'):
        raise FactoryError('role must be backend, frontend or critical')
    if t.get('complexity', 'routine') not in COMPLEXITIES:
        raise FactoryError('complexity must be ' + ' or '.join(COMPLEXITIES))
    supersedes = t.get('supersedes', [])
    if not isinstance(supersedes, list) or any(not isinstance(x, str) or not x.strip() for x in supersedes):
        raise FactoryError('supersedes must be a list of ticket ids')
    if t['id'] in supersedes:
        raise FactoryError('Ticket cannot supersede itself')
    if t['id'] in t['depends_on']:
        raise FactoryError('Ticket cannot depend on itself')
    for p in t['paths']:
        path = PurePosixPath(p)
        if path.is_absolute() or '..' in path.parts or not path.parts or '\\' in p or any(x in p for x in '*?['):
            raise FactoryError('paths must be literal relative files or directories, without traversal/globs')
        if any(ord(ch) < 32 for ch in p):
            raise FactoryError('paths must not contain control characters')
        if protected(p):
            raise FactoryError(f'Protected path: {p}')
    t['paths'] = [PurePosixPath(p).as_posix() for p in t['paths']]
    if len(t['paths']) != len(set(t['paths'])):
        raise FactoryError('Duplicate normalized paths are not allowed')
    validate_spec(t)
    return t


def update(home, ticket_id, state, repair_request=None, **kwargs):
    values = {'state': state, 'updated': time.time(), **kwargs}
    with connect(home) as con:
        if repair_request is not None:
            con.execute('''CREATE TABLE IF NOT EXISTS repair_requests (
                ticket_id TEXT NOT NULL, head TEXT NOT NULL, receipt TEXT NOT NULL,
                PRIMARY KEY(ticket_id,head))''')
            con.execute('INSERT INTO repair_requests VALUES(?,?,?)',
                        (ticket_id, repair_request['head'], repair_request['receipt']))
            record(con, ticket_id, state, {'action': 'repair', **repair_request})
        con.execute('UPDATE tickets SET ' + ','.join(f'{k}=?' for k in values) + ' WHERE id=?', [*values.values(), ticket_id])
        record(con, ticket_id, state, kwargs)



def add_ticket(con, c, t, idempotent=False):
    """Insert a validated ticket and audit event in the caller's transaction."""
    existing = con.execute('SELECT * FROM tickets WHERE id=?', (t['id'],)).fetchone()
    if existing:
        if not idempotent:
            raise FactoryError('Ticket already exists; use --idempotent only to replay identical content')
        if config_hash(json.loads(existing['ticket'])) != config_hash(t):
            raise FactoryError('Idempotent replay conflicts with existing ticket content')
        return {'id': t['id'], 'state': existing['state'], 'replayed': True,
                'attempts_used': existing['attempts'], 'maximum_attempts': attempt_limit(c)}
    for dependency in t['depends_on']:
        if not con.execute('SELECT id FROM tickets WHERE id=?', (dependency,)).fetchone():
            raise FactoryError(f'Unknown dependency: {dependency}; add dependencies first')
    reject_dependency_cycle(con, t)
    inherited = inherited_attempts(con, t)
    con.execute('INSERT INTO tickets(id,ticket,state,updated,attempts) VALUES(?,?,?,?,?)',
                (t['id'], json.dumps(t), 'PENDING', time.time(), inherited))
    record(con, t['id'], 'PENDING', {'action': 'add', 'supersedes': t.get('supersedes', []),
                                     'inherited_attempts': inherited})
    for old in t.get('supersedes', []):
        con.execute("UPDATE tickets SET state='REJECTED',error=?,updated=? WHERE id=?",
                    ('Superseded by ' + t['id'] + '; history kept', time.time(), old))
        record(con, old, 'REJECTED', {'action': 'superseded', 'by': t['id']})
    return {'id': t['id'], 'state': 'PENDING', 'replayed': False, 'attempts_used': inherited,
            'maximum_attempts': attempt_limit(c)}
