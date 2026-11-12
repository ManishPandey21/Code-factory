"""Best-effort local CLI usage metadata, separate from verification and authority.

No network, prompts, argv, credentials or subprocess output are collected.
A start without a matching finish records an interrupted/uncompleted invocation.
Tracing must never change the command's result or any readiness/hold decision.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import time
import uuid

from runtime import FactoryError
from path_safety import checked_path


EXPECTED_ERRORS = (FactoryError, OSError, ValueError, KeyError, TypeError,
                   sqlite3.Error, subprocess.SubprocessError)


def _append(home, event):
    """Commit one small metadata event in a separate local SQLite database.

    SQLite serializes concurrent CLI writers on all supported platforms. Never
    hold this connection while doing work or touch the authoritative ledger.
    """
    try:
        home = checked_path(home)
        path = checked_path(home / 'usage.sqlite3')
        home.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if not stat.S_ISREG(path.stat().st_mode):
                raise OSError('trace path is not a regular file')
        else:
            os.close(fd)
        con = sqlite3.connect(path, timeout=1)
        try:
            with con:
                con.execute('CREATE TABLE IF NOT EXISTS usage_events ('
                            'sequence INTEGER PRIMARY KEY, event TEXT NOT NULL)')
                con.execute('INSERT INTO usage_events(event) VALUES(?)',
                            (json.dumps(event, sort_keys=True),))
        finally:
            con.close()
    except (OSError, ValueError, sqlite3.Error):
        # Keep machine-readable stdout unchanged and do not echo paths or data.
        try:
            print('factory: local usage trace unavailable; command behavior is unchanged', file=sys.stderr)
        except (OSError, ValueError):
            pass


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def traced(home, args, action):
    """Record every parsed invocation with a resolvable Git repository.

    Preview/help distinction is explicit: parsed previews are traced; argparse
    help/errors and invalid repository paths have no run or local destination.
    """
    invocation = uuid.uuid4().hex
    preview = ((args.action == 'init' and not args.apply) or
               (args.action in ('run', 'publish', 'repair', 'intake', 'link-issue') and not args.execute))
    common = {'schema': 1, 'invocation': invocation, 'command': args.action,
              'pid': os.getpid(), 'preview': preview}
    started = time.monotonic()
    _append(home, {**common, 'event': 'start', 'at': _now()})
    code, outcome = 1, 'error'
    try:
        code = action()
        outcome = 'ok' if code == 0 else 'failed'
        return code
    except KeyboardInterrupt:
        code, outcome = 130, 'interrupted'
        raise
    except SystemExit as exc:
        code = exc.code if type(exc.code) is int else 0 if exc.code is None else 1
        outcome = 'ok' if code == 0 else 'failed'
        raise
    except EXPECTED_ERRORS:
        code = 2
        raise
    finally:
        _append(home, {**common, 'event': 'finish', 'at': _now(), 'exit_code': code,
                       'outcome': outcome, 'duration_ms': round((time.monotonic() - started) * 1000, 3)})
