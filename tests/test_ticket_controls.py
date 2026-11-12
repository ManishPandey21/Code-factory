"""Real CLI regressions for durable holds and duplicate-safe submission."""
import contextlib
import json
from pathlib import Path
import sqlite3
import unittest
from test_factory import FactoryTests


class TicketControlTests(unittest.TestCase):
    setUp = FactoryTests.setUp
    tearDown = FactoryTests.tearDown
    git = FactoryTests.git
    commit = FactoryTests.commit
    cli = FactoryTests.cli
    states = FactoryTests.states
    add = FactoryTests.add

    def hold(self, tid='A', version=0, reason='Review destination', code=0):
        return self.cli('hold', '--ticket', tid, '--hold-version', str(version), '--reason', reason, code=code)

    def release(self, tid='A', version=1, code=0):
        return self.cli('release', '--ticket', tid, '--hold-version', str(version),
                        '--reason', 'Destination reviewed', code=code)

    def event_count(self, tid='A'):
        with contextlib.closing(sqlite3.connect(self.repo / '.git/infra-factory/ledger.sqlite3')) as con, con:
            return con.execute('SELECT COUNT(*) FROM events WHERE ticket_id=?', (tid,)).fetchone()[0]

    def test_hold_survives_commands_and_stale_release_is_refused(self):
        self.add('A'); self.hold()
        row = self.states()['A']
        self.assertEqual((row['hold_reason'], row['hold_version']), ('Review destination', 1))
        preview = json.loads(self.cli('run').stdout)
        self.assertEqual(preview['selected'], [])
        self.assertIn('held', preview['waiting']['A'])
        self.release(version=0, code=2)
        self.assertEqual(self.states()['A']['hold_version'], 1)
        self.hold(version=1, reason='New concern')
        self.release(version=1, code=2)
        self.release(version=2)
        self.assertIsNone(self.states()['A']['hold_reason'])
        self.assertEqual(self.states()['A']['hold_version'], 3)
        self.assertEqual(json.loads(self.cli('run').stdout)['selected'], ['A'])

    def test_ready_hold_blocks_publication_without_revoking_verification(self):
        self.add('A'); self.cli('run', '--execute'); self.hold()
        self.cli('publish', '--ticket', 'A', '--execute', code=2)
        row = self.states()['A']
        self.assertEqual(row['state'], 'READY')
        self.assertTrue(row['verification_current'])
        self.assertTrue(row['publication_held'])
        self.assertIsNone(row['pr_url'])
        self.release()
        self.cli('publish', '--ticket', 'A')

    def test_hold_blocks_retry_replacement_and_overlapping_dispatch(self):
        self.add('A', title='REJECT'); self.cli('run', '--execute', code=1)
        self.hold()
        self.cli('retry', '--ticket', 'A', code=2)
        self.cli('reject', '--ticket', 'A', code=2)
        ticket = json.loads((self.home / 'A.json').read_text(encoding='utf-8'))
        ticket.update(id='B', supersedes=['A'])
        replacement = self.home / 'B.json'; replacement.write_text(json.dumps(ticket), encoding='utf-8')
        self.cli('add', '--ticket', str(replacement), code=2)
        self.release(); self.cli('retry', '--ticket', 'A')
        # Held pending work reserves its paths even before its first candidate.
        self.add('C', paths=['shared-path.py']); self.hold('C')
        self.add('D', paths=['shared-path.py'])
        preview = json.loads(self.cli('run').stdout)
        self.assertNotIn('D', preview['selected'])
        self.assertIn('overlap', preview['waiting']['D'])

    def test_hold_refuses_in_flight_and_invalid_version_or_reason(self):
        self.add('A')
        self.hold(version=-1, code=2)
        self.hold(reason='  ', code=2)
        self.release(version=0, code=2)
        with contextlib.closing(sqlite3.connect(self.repo / '.git/infra-factory/ledger.sqlite3')) as con, con:
            con.execute("UPDATE tickets SET state='RUNNING' WHERE id='A'")
        self.hold(code=2)

    def test_control_status_and_release_work_with_broken_configuration(self):
        self.add('A'); self.hold()
        self.cfg.write_text('{broken', encoding='utf-8')
        status = json.loads(self.cli('status').stdout)
        self.assertTrue(status['configuration_error'])
        self.assertEqual(status['tickets'][0]['hold_version'], 1)
        self.assertFalse(status['tickets'][0]['verification_current'])
        self.release()
        self.cli('run', '--execute', code=2)

    def test_missing_config_preserves_status_and_controls(self):
        self.add('A')
        self.cfg.unlink()
        self.hold()
        status = json.loads(self.cli('status').stdout)
        self.assertTrue(status['configuration_error'])
        self.assertEqual(status['tickets'][0]['hold_version'], 1)
        self.release()
        self.cli('run', '--execute', code=2)

    def test_invalid_inventory_path_still_allows_inspection(self):
        self.add('A'); self.hold()
        config = json.loads(self.cfg.read_text(encoding='utf-8'))
        config['skill_inventory'] = {'version': 1, 'skills': {
            'matt:codebase-design': {'available': True, 'path': None}}}
        self.cfg.write_text(json.dumps(config), encoding='utf-8')
        status = json.loads(self.cli('status').stdout)
        self.assertTrue(status['configuration_error'])
        self.assertEqual(status['tickets'][0]['hold_version'], 1)
        self.release()
        self.cli('run', '--execute', code=2)

    def test_external_merge_of_held_candidate_does_not_reserve_paths_forever(self):
        self.add('A'); self.cli('run', '--execute'); self.hold()
        row = self.states()['A']
        self.git('merge', '--ff-only', row['branch'])
        self.add('B', paths=['A.py'])
        preview = json.loads(self.cli('run').stdout)
        self.assertIn('B', preview['selected'])

    def test_idempotent_add_preserves_state_attempts_events_and_holds(self):
        self.add('A'); self.hold()
        with contextlib.closing(sqlite3.connect(self.repo / '.git/infra-factory/ledger.sqlite3')) as con, con:
            con.execute("UPDATE tickets SET attempts=2,state='BLOCKED' WHERE id='A'")
        before = self.event_count()
        p = self.cli('add', '--ticket', str(self.home / 'A.json'), '--idempotent')
        reply = json.loads(p.stdout)
        self.assertTrue(reply['replayed'])
        self.assertEqual((reply['state'], reply['attempts_used']), ('BLOCKED', 2))
        self.assertEqual(self.event_count(), before)
        self.assertEqual(self.states()['A']['hold_version'], 1)
        self.cli('add', '--ticket', str(self.home / 'A.json'), code=2)
        ticket = json.loads((self.home / 'A.json').read_text(encoding='utf-8')); ticket['title'] = 'Different request'
        (self.home / 'A.json').write_text(json.dumps(ticket), encoding='utf-8')
        self.cli('add', '--ticket', str(self.home / 'A.json'), '--idempotent', code=2)
        self.assertEqual(self.event_count(), before)

    def test_idempotent_first_submission_and_replay_have_one_add_event(self):
        # Reuse the fixture schema, with a new unused ID.
        self.add('seed')
        path = self.home / 'seed.json'
        ticket = json.loads(path.read_text(encoding='utf-8')); ticket['id'] = 'new'; ticket['paths'] = ['new.py']
        path.write_text(json.dumps(ticket), encoding='utf-8')
        first = json.loads(self.cli('add', '--ticket', str(path), '--idempotent').stdout)
        second = json.loads(self.cli('add', '--ticket', str(path), '--idempotent').stdout)
        self.assertFalse(first['replayed']); self.assertTrue(second['replayed'])
        self.assertEqual(self.event_count('new'), 1)


del FactoryTests

if __name__ == '__main__':
    unittest.main()


class ControlAtomicityTests(unittest.TestCase):
    def test_event_failure_rolls_back_hold_and_release_versions(self):
        import contextlib
        import io
        import sys
        from unittest.mock import patch
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import factory
        from test_factory import FactoryTests as Fixture
        fixture = Fixture(); fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.add('A')
        for action, version in [('hold', 0), ('release', 1)]:
            if action == 'release':
                fixture.cli('hold', '--ticket', 'A', '--hold-version', '0', '--reason', 'Keep')
            with contextlib.redirect_stdout(io.StringIO()), patch('factory.record', side_effect=RuntimeError('audit failed')):
                with self.assertRaises(RuntimeError):
                    factory.main([action, '--repo', str(fixture.repo), '--ticket', 'A',
                                  '--hold-version', str(version), '--reason', 'Change'])
            row = fixture.states()['A']
            self.assertEqual(row['hold_version'], version)
            self.assertEqual(row['hold_reason'], None if version == 0 else 'Keep')
