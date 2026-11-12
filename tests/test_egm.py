"""Real-Git tests for the EGM-to-factory handoff (no model calls)."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import egm
from test_factory import FactoryTests


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.env = dict(os.environ, GIT_AUTHOR_NAME='test', GIT_AUTHOR_EMAIL='t@example.invalid',
                        GIT_COMMITTER_NAME='test', GIT_COMMITTER_EMAIL='t@example.invalid')
        self.git('init', '-q', '-b', 'main')
        (self.repo / 'design.md').write_text('Approved design with an implementation plan', encoding='utf-8')
        (self.repo / 'review.md').write_text('Five stages reviewed; findings resolved', encoding='utf-8')
        self.commit()
        self.ticket = {'id': 'A', 'description': 'Approved work'}
        self.ticket['egm'] = {'schema': 1, 'ticket_sha256': egm.ticket_digest(self.ticket),
                              'design': egm.artifact(self.repo, 'design.md'),
                              'reports': {s: egm.artifact(self.repo, 'review.md') for s in egm.STAGES},
                              'approval': {'by': 'test owner', 'note': 'Fixture approval'}}

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], env=self.env,
                              capture_output=True, check=True)

    def commit(self):
        self.git('add', '.'); self.git('commit', '-qm', 'fixture')

    def test_malformed_ticket_cli_has_concise_error(self):
        ticket = self.repo / 'bad-ticket.json'
        ticket.write_text('{"id": "bad id"}', encoding='utf-8')
        p = subprocess.run([sys.executable, str(Path(egm.__file__)), '--repo', str(self.repo),
                            '--ticket', str(ticket), '--design', 'design.md',
                            '--report', 'initial_zoom_out=review.md', '--approved-by', 'fixture',
                            '--approval-note', 'fixture', '--output', str(self.repo / 'out.json')],
                           capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(p.returncode, 2)
        self.assertIn('egm: Ticket id', p.stderr)
        self.assertNotIn('Traceback', p.stderr)

    def test_valid_receipt_and_legacy_opt_out(self):
        egm.validate_handoff(self.repo, self.ticket, True)
        egm.validate_handoff(self.repo, {})
        with self.assertRaises(ValueError):
            egm.validate_handoff(self.repo, {}, True)

    def test_changed_ticket_requires_new_approval(self):
        self.ticket['description'] = 'Different work'
        with self.assertRaisesRegex(ValueError, 'scope'):
            egm.validate_handoff(self.repo, self.ticket, True)

    def test_modified_artifacts_rejected_before_and_after_commit(self):
        for name in ('design.md', 'review.md'):
            with self.subTest(artifact=name):
                old = (self.repo / name).read_text(encoding='utf-8')
                (self.repo / name).write_text('Changed', encoding='utf-8')
                with self.assertRaises(ValueError):
                    egm.validate_handoff(self.repo, self.ticket, True)
                self.commit()
                with self.assertRaises(ValueError):
                    egm.validate_handoff(self.repo, self.ticket, True)
                (self.repo / name).write_text(old, encoding='utf-8'); self.commit()

    def test_missing_stage_and_approval_fail_closed(self):
        for key in ('reports', 'approval'):
            ticket = copy.deepcopy(self.ticket)
            ticket['egm'][key] = {}
            with self.assertRaises(ValueError):
                egm.validate_handoff(self.repo, ticket, True)

    def test_unsafe_untracked_and_empty_artifacts(self):
        (self.repo / 'untracked.md').write_text('not committed', encoding='utf-8')
        (self.repo / 'empty.md').write_text('', encoding='utf-8')
        for path in ('../escape', '/etc/passwd', '.git/config', 'untracked.md', 'empty.md'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                egm.artifact(self.repo, path)
        if os.name == 'posix':
            (self.repo / 'alias.md').symlink_to(self.repo / 'design.md')
            with self.assertRaises(ValueError):
                egm.artifact(self.repo, 'alias.md')


class FactoryEGMTests(unittest.TestCase):
    # Reuse the setup helpers without inheriting/rerunning the full base suite.
    setUp = FactoryTests.setUp
    tearDown = FactoryTests.tearDown
    git = FactoryTests.git
    commit = FactoryTests.commit
    cli = FactoryTests.cli
    states = FactoryTests.states

    def test_handoff_cli_to_ready_and_stale_status(self):
        c = json.loads(self.cfg.read_text(encoding='utf-8')); c['workflow'] = 'egm'
        self.cfg.write_text(json.dumps(c), encoding='utf-8')
        (self.repo / 'design.md').write_text('Implement A.py returning value 42', encoding='utf-8')
        (self.repo / 'review.md').write_text('Fixture report covering all five stages', encoding='utf-8')
        self.commit()
        t = {'id': 'A', 'title': 'Implement fixture', 'description': 'Create A.py',
             'acceptance': ['File contains value 42'], 'paths': ['A.py'], 'depends_on': [], 'role': 'backend',
             'spec': {k: {'impact': 'Fixture', 'acceptance': ['Contract holds']}
                      for k in ('ui', 'api', 'data', 'cross_cutting')}}
        raw = self.home / 'raw.json'; raw.write_text(json.dumps(t), encoding='utf-8')
        output = self.home / 'bound.json'
        self.cli('add', '--ticket', str(raw), code=2)
        cmd = [sys.executable, str(Path(egm.__file__)), '--repo', str(self.repo), '--ticket', str(raw),
               '--design', 'design.md', '--approved-by', 'fixture human', '--approval-note', 'Fixture approval',
               '--output', str(output)]
        for stage in egm.STAGES:
            cmd += ['--report', stage + '=review.md']
        p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
        self.cli('add', '--ticket', str(output))
        self.cli('run', '--execute')
        row = self.states()['A']
        self.assertEqual(row['state'], 'READY', row.get('error'))
        self.assertTrue(row['verification_current'])
        logs = self.repo / '.git/infra-factory/logs' / Path(row['worktree']).name
        for lens in ('standards', 'spec'):
            prompt = (logs / f'review-{lens}-prompt.txt').read_text(encoding='utf-8')
            self.assertIn('independently read design.md', prompt)
            self.assertIn('omitted from the ticket summary', prompt)
            self.assertIn('Do not read EGM review reports', prompt)
        (self.repo / 'design.md').write_text('Changed after review', encoding='utf-8')
        self.assertFalse(self.states()['A']['verification_current'])
        self.cli('publish', '--ticket', 'A', code=2)


# Do not let unittest rediscover the imported helper suite.
del FactoryTests

if __name__ == '__main__':
    unittest.main()
