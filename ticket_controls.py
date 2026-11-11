"""Private durable ticket holds, separate from verification and attempt state.

Call mutations while holding the coordinator lock. This module uses the caller's
SQLite transaction so the control change and ledger event commit together.
"""


def control(con, ticket_id):
    # Older ledgers need no eager migration just to read status or recover a lock.
    table = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ticket_controls'").fetchone()
    row = con.execute('SELECT reason,version FROM ticket_controls WHERE ticket_id=?',
                      (ticket_id,)).fetchone() if table else None
    return {'hold_reason': row[0] if row else None, 'hold_version': row[1] if row else 0}


def require_unheld(con, ticket_id):
    if control(con, ticket_id)['hold_reason'] is not None:
        raise ValueError(f'Ticket {ticket_id} is held; inspect status and release its current hold version first')


def change_control(con, ticket_id, expected_version, reason, release=False):
    if type(expected_version) is not int or expected_version < 0:
        raise ValueError('hold-version must be a nonnegative integer')
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
        raise ValueError('A nonempty reason of at most 1000 characters is required')
    row = con.execute('SELECT state FROM tickets WHERE id=?', (ticket_id,)).fetchone()
    if not row or row[0] not in ('PENDING', 'BLOCKED', 'READY'):
        raise ValueError('Holds can change only on inactive PENDING, BLOCKED or READY tickets; recover stopped work first')
    current = control(con, ticket_id)
    if current['hold_version'] != expected_version:
        raise ValueError('Hold version changed; read current status before changing the hold')
    if release and current['hold_reason'] is None:
        raise ValueError('Ticket is not held')
    con.execute('''CREATE TABLE IF NOT EXISTS ticket_controls (
        ticket_id TEXT PRIMARY KEY, reason TEXT, version INTEGER NOT NULL)''')
    updated = {'hold_reason': None if release else reason.strip(), 'hold_version': expected_version + 1}
    con.execute('''INSERT INTO ticket_controls(ticket_id,reason,version) VALUES(?,?,?)
        ON CONFLICT(ticket_id) DO UPDATE SET reason=excluded.reason,version=excluded.version''',
        (ticket_id, updated['hold_reason'], updated['hold_version']))
    return row[0], updated
