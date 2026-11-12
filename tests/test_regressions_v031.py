"""Regressions for defects reproduced in the v0.3 audit (see CHANGELOG.md)."""
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_factory as _base  # noqa: E402

ROOT = _base.ROOT

DEAD_PID = 2 ** 22 - 3  # above the default Linux pid_max; never a live process here

GH = '''import json,sys,subprocess
from pathlib import Path
print('A new release of gh is available: 2.60.0 -> 2.61.0', file=sys.stderr)
state=Path('.git/fake-gh.json')
if sys.argv[1:3]==['pr','list']:
    print(state.read_text() if state.exists() else '[]')
elif sys.argv[1:3]==['pr','create']:
    assert not state.exists(), 'Duplicate PR creation'
    branch=sys.argv[sys.argv.index('--head')+1]
    head=subprocess.check_output(['git','rev-parse',branch],text=True).strip()
    state.write_text(json.dumps([{'url':'https://example.invalid/pull/1','isDraft':True,'headRefOid':head}]))
else:
    raise SystemExit(7)
'''


@unittest.skipUnless(os.name == 'posix', 'Fixtures use POSIX shebangs and signals')
class AuditRegressions(_base.FactoryTests):
    def run_cli(self, action, *args, env=None):
        return subprocess.run([sys.executable, str(ROOT / 'factory.py'), action, '--repo', str(self.repo), *args],
                              capture_output=True, text=True, env=env, encoding='utf-8')

    def ledger(self, sql, *params):
        con = sqlite3.connect(self.repo / '.git/infra-factory/ledger.sqlite3')
        try:
            rows = con.execute(sql, params).fetchall()
            con.commit()
            return rows
        finally:
            con.close()

    def trail(self, ticket):
        return [r[0] for r in self.ledger('SELECT state FROM events WHERE ticket_id=? ORDER BY sequence', ticket)]

    def remote(self):
        bare = self.home / 'remote.git'
        subprocess.check_call(['git', 'init', '-q', '--bare', str(bare)])
        self.git('remote', 'add', 'origin', str(bare))
        self.git('push', '-q', 'origin', 'main')

    def tool(self, name, body):
        directory = self.home / 'bin'
        directory.mkdir(exist_ok=True)
        path = directory / name
        path.write_text('#!' + sys.executable + '\n' + body, encoding='utf-8')
        path.chmod(0o755)
        return dict(os.environ, PATH=str(directory) + os.pathsep + os.environ['PATH'])

    def stale_lock(self):
        target = self.repo / '.git/infra-factory/coordinator.lock'
        target.write_text(json.dumps({'pid': DEAD_PID, 'host': socket.gethostname()}), encoding='utf-8')
        return target

    def test_unmerged_ready_candidate_holds_its_paths(self):
        self.add('A', ['shared']); self.add('B', ['shared/module.py']); self.add('C')
        self.cli('run', '--execute', '--limit', '1')
        preview = json.loads(self.cli('run').stdout)
        self.assertEqual(preview['selected'], ['C'])
        self.assertIn('overlap', preview['waiting']['B'])
        self.git('merge', '-q', '--ff-only', self.states()['A']['head_sha'])
        self.assertIn('B', json.loads(self.cli('run').stdout)['selected'])

    def test_rejecting_holder_releases_paths(self):
        self.add('A', ['shared']); self.add('B', ['shared/module.py'])
        self.cli('run', '--execute', '--limit', '1'); self.cli('reject', '--ticket', 'A')
        self.assertEqual(json.loads(self.cli('run').stdout)['selected'], ['B'])

    def test_waiting_explains_unmet_dependency(self):
        self.add('A'); self.add('B', depends=['A'])
        self.assertIn('A=PENDING', json.loads(self.cli('run').stdout)['waiting']['B'])

    def test_unlock_clears_dead_owner_lock_only(self):
        self.add('A'); target = self.stale_lock()
        self.cli('run', code=2)
        self.cli('unlock'); self.assertFalse(target.exists())
        self.cli('run')
        target.write_text(json.dumps({'pid': os.getpid(), 'host': socket.gethostname()}), encoding='utf-8')
        self.cli('unlock', code=2); self.assertTrue(target.exists())
        target.write_text(json.dumps({'pid': DEAD_PID, 'host': 'another-host'}), encoding='utf-8')
        self.cli('unlock', code=2)
        target.write_text('{}', encoding='utf-8')
        self.cli('unlock', code=2); self.assertTrue(target.exists())

    def test_unlock_defers_to_recover_for_in_flight_ticket(self):
        self.add('A'); self.stale_lock()
        self.ledger("UPDATE tickets SET state='RUNNING', owner_pid=?, owner_host=? WHERE id='A'", DEAD_PID, socket.gethostname())
        self.assertIn('recover', self.cli('unlock', code=2).stderr)
        self.cli('recover', '--ticket', 'A')
        self.assertEqual(self.states()['A']['state'], 'BLOCKED')
        self.assertEqual(self.trail('A')[-1], 'BLOCKED')

    def test_cli_notices_on_stderr_do_not_break_publication(self):
        self.add('A'); self.cli('run', '--execute'); self.remote()
        real = subprocess.check_output(['which', 'git'], text=True, encoding='utf-8').strip()
        self.tool('git', "import os,sys\nif 'ls-remote' in sys.argv: print(\"Warning: Permanently added 'github.com' "
                         "(ED25519) to the list of known hosts.\", file=sys.stderr, flush=True)\n"
                         f"os.execv({real!r},[{real!r}]+sys.argv[1:])\n")
        env = self.tool('gh', GH)
        p = self.run_cli('publish', '--ticket', 'A', '--execute', env=env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        row = self.states()['A']
        self.assertEqual((row['state'], row['pr_url']), ('READY', 'https://example.invalid/pull/1'))

    def test_transport_failure_keeps_verification_then_publishes(self):
        self.add('A'); self.cli('run', '--execute')
        p = self.run_cli('publish', '--ticket', 'A', '--execute')  # no origin: stands in for network/auth failure
        self.assertEqual(p.returncode, 2)
        row = self.states()['A']
        self.assertEqual((row['state'], row['attempts']), ('READY', 1))
        self.assertIn('Local verification retained', row['error'])
        self.assertTrue(row['verification_current'])
        self.remote()
        p = self.run_cli('publish', '--ticket', 'A', '--execute', env=self.tool('gh', GH))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIsNone(self.states()['A']['error'])

    def test_missing_gh_after_push_is_resumable(self):
        self.add('A'); self.cli('run', '--execute'); self.remote()
        empty = self.home / 'nogh'; empty.mkdir()
        git_dir = str(Path(subprocess.check_output(['which', 'git'], text=True, encoding='utf-8').strip()).parent)
        python_dir = str(Path(sys.executable).parent)
        self.tool('gh', 'raise SystemExit(4)\n')
        p = self.run_cli('publish', '--ticket', 'A', '--execute', env=dict(os.environ, PATH=os.pathsep.join([str(self.home / 'bin'), python_dir, git_dir])))
        self.assertEqual(p.returncode, 2)
        row = self.states()['A']
        self.assertEqual(row['state'], 'READY'); self.assertIn('branch was pushed', row['error'])
        p = self.run_cli('publish', '--ticket', 'A', '--execute', env=self.tool('gh', GH))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_identity_mismatch_still_revokes(self):
        self.add('A'); self.cli('run', '--execute'); self.remote()
        self.git('push', '-q', 'origin', self.states()['A']['head_sha'] + ':refs/heads/main')
        self.cli('publish', '--ticket', 'A', '--execute', code=2)
        self.assertEqual(self.states()['A']['state'], 'BLOCKED')

    def test_every_transition_is_evented(self):
        self.add('A', title='REJECT'); self.cli('run', '--execute', code=1); self.cli('retry', '--ticket', 'A')
        self.assertEqual(self.trail('A'), ['PENDING', 'RUNNING', 'REVIEWING', 'BLOCKED', 'PENDING'])

    def test_merge_detection_is_evented(self):
        self.add('B'); self.cli('run', '--execute')
        self.git('merge', '-q', '--ff-only', self.states()['B']['head_sha']); self.cli('run', '--execute')
        self.assertEqual(self.trail('B'), ['PENDING', 'RUNNING', 'REVIEWING', 'READY', 'MERGED'])

    def test_manifests_lockfiles_and_tool_config_are_guarded(self):
        names = ['package-lock.json', 'pnpm-lock.yaml', 'go.sum', 'tsconfig.json', 'setup.py', 'pkg/widget_test.go']
        (self.repo / 'pkg').mkdir()
        for name in names:
            (self.repo / name).write_text('original\n', encoding='utf-8')
        self.commit()
        for index, name in enumerate(names):
            ticket = 'L%d' % index
            self.add(ticket, [name]); self.run_cli('run', '--execute', '--limit', '1')
            row = self.states()[ticket]
            self.assertEqual(row['state'], 'BLOCKED', name)
            self.assertIn('Verification-sensitive', row['error'], name)

    def test_new_test_file_still_allowed(self):
        self.add('A', ['new_widget_test.go']); self.cli('run', '--execute')

    def test_symlinked_repository_refused_before_any_agent_runs(self):
        os.symlink('README.md', self.repo / 'docs-link'); self.commit(); self.add('A')
        for extra in ((), ('--execute',)):
            self.assertIn('Symlinks/submodules', self.cli('run', *extra, code=2).stderr)
        row = self.states()['A']
        self.assertEqual((row['state'], row['attempts']), ('PENDING', 0))
        self.assertFalse(list(self.events.glob('*builder*')))

    def test_invalid_legacy_ticket_does_not_block_queue(self):
        self.add('A')
        legacy = {'id': 'OLD', 'title': 'x', 'description': 'x', 'acceptance': ['x'], 'paths': ['old.py'], 'depends_on': [], 'role': 'backend'}
        self.ledger('INSERT INTO tickets(id,ticket,state,updated) VALUES(?,?,?,?)', 'OLD', json.dumps(legacy), 'PENDING', 0)
        self.assertIn('invalid ticket', json.loads(self.cli('run').stdout)['waiting']['OLD'])
        self.cli('run', '--execute')
        states = self.states(); self.assertEqual((states['A']['state'], states['OLD']['state']), ('READY', 'PENDING'))

    def test_mixed_lens_verdict_is_not_mislabelled(self):
        sys.path.insert(0, str(ROOT))
        import factory
        self.assertIn("'INCONCLUSIVE'", (ROOT / 'dispatch.py').read_text(encoding='utf-8').split('verdicts = {')[1][:260])

    def test_sigterm_kills_agents_releases_lock_and_blocks_ticket(self):
        pid_file = self.home / 'builder.pid'; slow = self.home / 'slow.py'
        slow.write_text(f'import os,time,pathlib\npathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\ntime.sleep(60)\n', encoding='utf-8')
        c = json.loads(self.cfg.read_text(encoding='utf-8')); c['commands']['backend']['argv'] = [sys.executable, str(slow)]; c['timeout_seconds'] = 120
        self.cfg.write_text(json.dumps(c), encoding='utf-8'); self.commit(); self.add('A')
        p = subprocess.Popen([sys.executable, str(ROOT / 'factory.py'), 'run', '--repo', str(self.repo), '--execute'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        deadline = time.time() + 20
        while time.time() < deadline and not (pid_file.exists() and pid_file.read_text(encoding='utf-8')):
            time.sleep(.05)
        builder = int(pid_file.read_text(encoding='utf-8'))
        p.send_signal(signal.SIGTERM)
        _, stderr = p.communicate(timeout=30)
        self.assertEqual(p.returncode, 130, stderr)
        for _ in range(40):
            try:
                os.kill(builder, 0)
            except ProcessLookupError:
                break
            time.sleep(.05)
        else:
            os.kill(builder, signal.SIGKILL); self.fail('builder outlived the terminated controller')
        self.assertFalse((self.repo / '.git/infra-factory/coordinator.lock').exists())
        row = self.states()['A']
        self.assertEqual(row['state'], 'BLOCKED'); self.assertIn('Interrupted', row['error'])
        self.cli('retry', '--ticket', 'A')

    def test_repository_hooks_cannot_smuggle_paths_into_the_candidate(self):
        hooks = self.repo / '.git/hooks'
        hooks.mkdir(exist_ok=True)
        hook = hooks / 'pre-commit'
        hook.write_text('#!/bin/sh\ngit mv -f README.md smuggled.txt\nexit 0\n', encoding='utf-8')
        hook.chmod(0o755)
        self.add('A')
        self.cli('run', '--execute')
        self.assertEqual(self.states()['A']['state'], 'READY')
        work = Path(self.states()['A']['worktree'])
        self.assertTrue((work / 'README.md').exists())
        self.assertFalse((work / 'smuggled.txt').exists())

    def test_rename_cannot_hide_an_out_of_scope_deletion(self):
        sys.path.insert(0, str(ROOT))
        import factory
        work = self.home / 'scope-repo'
        subprocess.check_call(['git', 'init', '-q', '-b', 'main', str(work)])
        subprocess.check_call(['git', '-C', str(work), 'config', 'user.email', 'test@example.invalid'])
        subprocess.check_call(['git', '-C', str(work), 'config', 'user.name', 'Factory Test'])
        (work / 'README.md').write_text('secret policy\n', encoding='utf-8')
        subprocess.check_call(['git', '-C', str(work), 'add', '.'])
        subprocess.check_call(['git', '-C', str(work), 'commit', '-qm', 'base'])
        base = subprocess.check_output(['git', '-C', str(work), 'rev-parse', 'HEAD'], text=True, encoding='utf-8').strip()
        subprocess.check_call(['git', '-C', str(work), 'mv', 'README.md', 'keep.py'])
        subprocess.check_call(['git', '-C', str(work), 'commit', '-qm', 'rename'])
        head = subprocess.check_output(['git', '-C', str(work), 'rev-parse', 'HEAD'], text=True, encoding='utf-8').strip()
        shown = subprocess.check_output(['git', '-C', str(work), 'diff', '--name-only', base, head], text=True, encoding='utf-8')
        self.assertNotIn('README.md', shown.split())
        with self.assertRaises(factory.FactoryError) as caught:
            factory.assert_committed_scope(work, {'paths': ['keep.py']}, base, head)
        self.assertIn('README.md', str(caught.exception))
        self.assertEqual(factory.diff_paths(work, base, head), ['README.md', 'keep.py'])

    def test_merged_blocked_candidate_releases_dependents(self):
        self.add('A', title='REJECT')
        self.add('B', depends=['A'])
        self.cli('run', '--execute', '--limit', '1', code=1)
        self.assertEqual(self.states()['A']['state'], 'BLOCKED')
        self.git('merge', '-q', '--ff-only', self.states()['A']['head_sha'])
        self.cli('run', '--execute')
        states = self.states()
        self.assertEqual(states['A']['state'], 'MERGED')
        self.assertEqual(states['B']['state'], 'READY')

    def test_dependency_cycle_is_rejected(self):
        self.add('A')
        stored = json.loads(self.ledger('SELECT ticket FROM tickets WHERE id=?', 'A')[0][0])
        stored['depends_on'] = ['B']
        self.ledger('UPDATE tickets SET ticket=? WHERE id=?', json.dumps(stored), 'A')
        self.add('B', depends=['A'], code=2)


for _name in dir(_base.FactoryTests):  # inherit the fixture, not a second copy of its tests
    if _name.startswith('test_') and _name not in AuditRegressions.__dict__:
        setattr(AuditRegressions, _name, None)


@unittest.skipUnless(os.name == 'posix', 'Executable fixture uses POSIX shebang')
class BridgeCredentialRegressions(unittest.TestCase):
    def bridge(self, provider, cli_body, concurrent_change=False):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); (d / 'prompt.txt').write_text('Review', encoding='utf-8')
            home = d / 'home'; config = home / ('.codex' if provider == 'codex' else '.claude'); config.mkdir(parents=True)
            name = 'auth.json' if provider == 'codex' else '.credentials.json'
            credential = config / name; credential.write_text('{"refresh":"old"}', encoding='utf-8'); credential.chmod(0o600)
            key = 'CODEX_HOME' if provider == 'codex' else 'CLAUDE_CONFIG_DIR'
            body = ('import json,os,sys\nfrom pathlib import Path\n'
                    f"assert os.environ.get('HTTPS_PROXY')=='http://proxy.invalid:8080'\n"
                    f"auth=Path(os.environ[{key!r}])/{name!r}\n" + cli_body +
                    (f"Path({str(credential)!r}).write_text('{{\"refresh\":\"other-session\"}}')\n" if concurrent_change else '') +
                    ("Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text('{}')\n" if provider == 'codex'
                     else "print(json.dumps({'result':'{}'}))\n"))
            fixture = d / provider; fixture.write_text('#!' + sys.executable + '\n' + body, encoding='utf-8'); fixture.chmod(0o755)
            env = {'PATH': str(d) + os.pathsep + os.environ['PATH'], 'HOME': str(home), key: str(config),
                   'HTTPS_PROXY': 'http://proxy.invalid:8080', 'GITHUB_TOKEN': 'must-not-inherit'}
            p = subprocess.run([sys.executable, str(ROOT / 'agent_bridge.py'), '--provider', provider, '--mode', 'reviewer',
                                '--model', 'fixture', '--prompt-file', str(d / 'prompt.txt'), '--result-file', str(d / 'result.json')],
                               env=env, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            return credential.read_text(encoding='utf-8'), credential.stat().st_mode & 0o777, sorted(x.name for x in config.iterdir()), p.stderr

    def test_refreshed_login_is_written_back(self):
        for provider in ('codex', 'claude'):
            with self.subTest(provider=provider):
                text, mode, names, _ = self.bridge(provider, "auth.write_text('{\"refresh\":\"rotated\"}')\n")
                self.assertEqual(text, '{"refresh":"rotated"}'); self.assertEqual(mode, 0o600); self.assertEqual(len(names), 1)

    def test_unchanged_login_is_untouched(self):
        self.assertEqual(self.bridge('codex', '')[0], '{"refresh":"old"}')

    def test_concurrent_refresh_is_never_overwritten(self):
        text, _, _, stderr = self.bridge('codex', "auth.write_text('{\"refresh\":\"rotated\"}')\n", concurrent_change=True)
        self.assertEqual(text, '{"refresh":"other-session"}'); self.assertIn('WARNING', stderr)

    def test_corrupt_refresh_is_not_written_back(self):
        text, _, _, stderr = self.bridge('claude', "auth.write_text('truncated{')\n")
        self.assertEqual(text, '{"refresh":"old"}'); self.assertIn('WARNING', stderr)


if __name__ == '__main__':
    unittest.main()
