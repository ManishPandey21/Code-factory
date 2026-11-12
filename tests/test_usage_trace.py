"""Local invocation tracing must not become a verification or authorization gate."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_factory as fixtures
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import usage_trace
from runtime import FactoryError

ROOT = Path(__file__).resolve().parents[1]


def read_events(home):
    with contextlib.closing(sqlite3.connect(home / 'usage.sqlite3')) as con, con:
        return [json.loads(row[0]) for row in con.execute('SELECT event FROM usage_events ORDER BY sequence')]


class UsageTraceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.args = argparse.Namespace(action='run', execute=True)

    def test_success_failure_and_exception_preserve_results(self):
        self.assertEqual(usage_trace.traced(self.home, self.args, lambda: 0), 0)
        self.assertEqual(usage_trace.traced(self.home, self.args, lambda: 1), 1)
        with self.assertRaisesRegex(FactoryError, 'secret reason'):
            usage_trace.traced(self.home, self.args, lambda: (_ for _ in ()).throw(FactoryError('secret reason')))
        events = read_events(self.home)
        self.assertEqual([e['event'] for e in events], ['start', 'finish'] * 3)
        self.assertEqual([e['exit_code'] for e in events if e['event'] == 'finish'], [0, 1, 2])
        for start, end in zip(events[::2], events[1::2]):
            self.assertEqual(start['invocation'], end['invocation'])
            self.assertGreaterEqual(end['duration_ms'], 0)
        self.assertNotIn('secret reason', json.dumps(events))

    def test_interruption_and_unknown_exception_are_recorded_and_reraised(self):
        for error, code, outcome in [(KeyboardInterrupt(), 130, 'interrupted'),
                                     (RuntimeError('private'), 1, 'error'), (SystemExit(7), 7, 'failed')]:
            with self.assertRaises(type(error)):
                usage_trace.traced(self.home, self.args, lambda: (_ for _ in ()).throw(error))
            self.assertEqual((read_events(self.home)[-1]['exit_code'], read_events(self.home)[-1]['outcome']), (code, outcome))

    def test_tracing_unavailable_cannot_change_success_or_hide_original_error(self):
        with patch('usage_trace.sqlite3.connect', side_effect=sqlite3.OperationalError('private path')), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(usage_trace.traced(self.home, self.args, lambda: 0), 0)
            with self.assertRaisesRegex(FactoryError, 'original'):
                usage_trace.traced(self.home, self.args, lambda: (_ for _ in ()).throw(FactoryError('original')))
        self.assertIn('trace unavailable', err.getvalue())
        self.assertNotIn('private path', err.getvalue())

    def test_concurrent_processes_keep_all_start_and_finish_events(self):
        code = ('from pathlib import Path; import argparse,sys; from usage_trace import traced; '
                'traced(Path(sys.argv[1]), argparse.Namespace(action="status"), lambda: 0)')
        processes = [subprocess.Popen([sys.executable, '-c', code, str(self.home)], cwd=ROOT,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(8)]
        for process in processes:
            output, error = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, error)
            self.assertEqual((output, error), (b'', b''))
        events = read_events(self.home)
        self.assertEqual(len(events), 16)
        self.assertEqual(len({event['invocation'] for event in events}), 8)

    def test_hard_killed_run_retains_durable_start(self):
        code = ('from pathlib import Path; import argparse,os,sys; from usage_trace import traced; '
                'traced(Path(sys.argv[1]), argparse.Namespace(action="status"), lambda: os._exit(9))')
        result = subprocess.run([sys.executable, '-c', code, str(self.home)], cwd=ROOT, capture_output=True)
        self.assertEqual(result.returncode, 9)
        self.assertEqual([event['event'] for event in read_events(self.home)], ['start'])

    def test_preview_is_explicit_and_no_extra_arguments_are_recorded(self):
        self.args.execute = False; self.args.reason = 'private'; self.args.ticket = '/private/ticket.json'
        usage_trace.traced(self.home, self.args, lambda: 0)
        event = read_events(self.home)[0]
        self.assertTrue(event['preview'])
        self.assertEqual(set(event), {'schema', 'invocation', 'command', 'pid', 'preview', 'event', 'at'})
        self.assertNotIn('private', json.dumps(event))


class CLIUsageTests(unittest.TestCase):
    setUp = fixtures.FactoryTests.setUp
    tearDown = fixtures.FactoryTests.tearDown
    git = fixtures.FactoryTests.git
    commit = fixtures.FactoryTests.commit
    cli = fixtures.FactoryTests.cli
    add = fixtures.FactoryTests.add
    states = fixtures.FactoryTests.states

    def test_real_cli_commands_are_traced_without_changing_holds_or_cleanliness(self):
        home = self.repo / '.git/infra-factory'
        self.assertEqual(read_events(home)[-1]['command'], 'init')
        self.add('A')
        self.cli('hold', '--ticket', 'A', '--hold-version', '0', '--reason', 'SENSITIVE')
        self.cli('run', '--execute')  # Held work remains unallocated.
        self.cli('release', '--ticket', 'A', '--hold-version', '0', '--reason', 'SENSITIVE', code=2)
        events = read_events(home)
        self.assertEqual([e['command'] for e in events[::2]], ['init', 'add', 'hold', 'run', 'release'])
        self.assertEqual(events[-1]['exit_code'], 2)
        self.assertNotIn('SENSITIVE', json.dumps(events))
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertEqual(self.states()['A']['hold_version'], 1)
        # Trace corruption is observable, but cannot change the status result.
        (home / 'usage.sqlite3').write_bytes(b'invalid database')
        result = self.cli('status')
        self.assertIn('trace unavailable', result.stderr)
        self.assertEqual(json.loads(result.stdout)['tickets'][0]['hold_version'], 1)

    def test_unknown_ticket_error_and_preview_are_traced(self):
        self.cli('publish', '--ticket', 'missing', code=2)
        home = self.repo / '.git/infra-factory'
        event = read_events(home)[-1]
        self.assertTrue(event['preview'])
        self.assertEqual((event['outcome'], event['exit_code']), ('error', 2))
