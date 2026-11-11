import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
@unittest.skipUnless(os.name=='posix','Executable fixture uses POSIX shebang')
class BridgeTests(unittest.TestCase):
    def fixture_run(self, directory, provider, body, env=None, mode='reviewer'):
        fixture = directory / provider
        fixture.write_text('#!' + sys.executable + '\n' + body)
        fixture.chmod(0o755)
        environment = dict(os.environ) if env is None else dict(env)
        environment['PATH'] = str(directory) + os.pathsep + environment.get('PATH', '')
        return subprocess.run([
            sys.executable, str(ROOT / 'agent_bridge.py'), '--provider', provider,
            '--mode', mode, '--model', 'fixture', '--prompt-file', str(directory / 'prompt.txt'),
            '--result-file', str(directory / 'result.json')],
            env=environment, capture_output=True, text=True)

    def profile_check(self, provider, fail=False):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / 'prompt.txt').write_text('Review independently')
            original = d / 'original-home'
            original.mkdir()
            config = original / ('.codex' if provider == 'codex' else '.claude')
            config.mkdir()
            credential = 'auth.json' if provider == 'codex' else '.credentials.json'
            (config / credential).write_text('{"fixture":"not-a-real-secret"}')
            for name in ('config.toml', 'settings.json', 'history.jsonl', 'AGENTS.md', 'CLAUDE.md'):
                (config / name).write_text('BUILDER MEMORY MUST NOT BE COPIED')
            witness = d / 'witness.json'
            env = dict(os.environ)
            env.update({'HOME': str(original), 'USERPROFILE': str(original),
                        'CODEX_HOME': str(original / '.codex'), 'CLAUDE_CONFIG_DIR': str(original / '.claude'),
                        'CODEX_THREAD_ID': 'builder-session', 'CLAUDE_CODE_SESSION_ID': 'builder-session',
                        'PYTHONPATH': '/do-not-inherit', 'GITHUB_TOKEN': 'must-not-inherit',
                        'OPENAI_API_KEY': 'fixture-openai', 'ANTHROPIC_API_KEY': 'fixture-anthropic'})
            body = '''import json, os, stat, sys
from pathlib import Path
home = Path(os.environ['HOME'])
assert home != Path(ORIGINAL)
assert os.environ['USERPROFILE'] == str(home)
for key in ('CODEX_HOME', 'CLAUDE_CONFIG_DIR', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_STATE_HOME', 'XDG_DATA_HOME', 'TMP', 'TEMP', 'TMPDIR'):
    assert Path(os.environ[key]).is_relative_to(home)
    assert Path(os.environ[key]).is_dir()
for key in ('CODEX_THREAD_ID', 'CLAUDE_CODE_SESSION_ID', 'PYTHONPATH', 'GITHUB_TOKEN'):
    assert key not in os.environ
config = Path(os.environ[CONFIG_KEY])
assert sorted(p.name for p in config.iterdir()) == [CREDENTIAL]
auth = config / CREDENTIAL
assert auth.read_text() == '{"fixture":"not-a-real-secret"}'
assert stat.S_IMODE(auth.stat().st_mode) == 0o600
Path(WITNESS).write_text(json.dumps({'home': str(home)}))
sys.stdin.read()
'''.replace('ORIGINAL', repr(str(original))).replace('CONFIG_KEY', repr('CODEX_HOME' if provider == 'codex' else 'CLAUDE_CONFIG_DIR')).replace('CREDENTIAL', repr(credential)).replace('WITNESS', repr(str(witness)))
            if fail:
                body += 'sys.exit(7)\n'
            elif provider == 'codex':
                body += "assert '--ephemeral' in sys.argv\nassert os.environ['OPENAI_API_KEY']=='fixture-openai'\nassert 'ANTHROPIC_API_KEY' not in os.environ\nPath(sys.argv[sys.argv.index('--output-last-message')+1]).write_text('{}')\n"
            else:
                body += "assert '--no-session-persistence' in sys.argv\nassert os.environ['ANTHROPIC_API_KEY']=='fixture-anthropic'\nassert 'OPENAI_API_KEY' not in os.environ\nprint(json.dumps({'result':'{}'}))\n"
            p = self.fixture_run(d, provider, body, env)
            self.assertEqual(p.returncode, 7 if fail else 0, p.stdout + p.stderr)
            self.assertFalse(Path(json.loads(witness.read_text())['home']).exists())
            self.assertEqual((config / credential).read_text(), '{"fixture":"not-a-real-secret"}')

    def test_codex_cold_profile(self): self.profile_check('codex')
    def test_claude_cold_profile(self): self.profile_check('claude')
    def test_failed_cli_cleans_profile(self): self.profile_check('codex', fail=True)

    def test_preexisting_result_and_symlink_rejected(self):
        for symlink in (False, True):
            with self.subTest(symlink=symlink), tempfile.TemporaryDirectory() as td:
                d = Path(td)
                (d / 'prompt.txt').write_text('Review')
                final = d / 'result.json'
                if symlink:
                    final.symlink_to(d / 'missing-target')
                else:
                    final.write_text('stale')
                p = self.fixture_run(d, 'codex', "raise RuntimeError('must never run')\n")
                self.assertEqual(p.returncode, 2)
                self.assertIn('Result path already exists', p.stderr)
                self.assertFalse((d / 'missing-target').exists())

    def test_result_planted_during_cli_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / 'prompt.txt').write_text('Review')
            body = ('import sys\nfrom pathlib import Path\n'
                    f"Path({str(d / 'result.json')!r}).write_text('planted')\n"
                    "Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text('{}')\n")
            p = self.fixture_run(d, 'codex', body)
            self.assertEqual(p.returncode, 2)
            self.assertEqual((d / 'result.json').read_text(), 'planted')

    def test_prompt_mutation_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / 'prompt.txt').write_text('Review')
            body = ('import sys\nfrom pathlib import Path\n'
                    f"Path({str(d / 'prompt.txt')!r}).write_text('changed')\n"
                    "Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text('{}')\n")
            p = self.fixture_run(d, 'codex', body)
            self.assertEqual(p.returncode, 2)
            self.assertIn('Prompt changed', p.stderr)
            self.assertFalse((d / 'result.json').exists())

    def test_builder_environment_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / 'prompt.txt').write_text('Build')
            env = dict(os.environ, INFRA_TEST_BUILDER='retained')
            body = ("import os,sys\nfrom pathlib import Path\n"
                    "assert os.environ['INFRA_TEST_BUILDER']=='retained'\n"
                    "assert sys.argv[sys.argv.index('--sandbox')+1]=='workspace-write'\n"
                    "Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text('Built')\n")
            p = self.fixture_run(d, 'codex', body, env, mode='builder')
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual(json.loads((d / 'result.json').read_text()), {'summary': 'Built'})

    def check(self,provider,broken=False):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td); prompt=d/'prompt.txt';prompt.write_text('Review the candidate')
            final=d/'result.json'
            fixture=d/provider
            body="""import json,sys
from pathlib import Path
prompt=sys.stdin.read()
assert 'Transport override' in prompt
assert not any('bypass' in a for a in sys.argv)
data={'verdict':'PASS','reviewed_head':'abc','base':'def','findings':[]}
"""
            if provider=='codex':
                body+="assert sys.argv[sys.argv.index('--sandbox')+1]=='read-only'\nPath(sys.argv[sys.argv.index('--output-last-message')+1]).write_text("+repr('not json' if broken else json.dumps({'verdict':'PASS','reviewed_head':'abc','base':'def','findings':[]}))+ ")\n"
            else:
                body+="assert sys.argv[sys.argv.index('--permission-mode')+1]=='plan'\nprint(json.dumps({'is_error': "+repr(broken)+",'result':json.dumps(data)}))\n"
            fixture.write_text('#!'+sys.executable+'\n'+body);fixture.chmod(0o755)
            env=dict(os.environ);env['PATH']=str(d)+os.pathsep+env['PATH']
            p=subprocess.run([sys.executable,str(ROOT/'agent_bridge.py'),'--provider',provider,'--mode','reviewer','--model','fixture','--prompt-file',str(prompt),'--result-file',str(final)],env=env,capture_output=True,text=True)
            self.assertEqual(p.returncode,2 if broken else 0,p.stdout+p.stderr)
            if not broken: self.assertEqual(json.loads(final.read_text())['verdict'],'PASS')
    def test_codex_final(self):self.check('codex')
    def test_claude_final(self):self.check('claude')
    def test_codex_invalid_json(self):self.check('codex',True)
    def test_claude_error(self):self.check('claude',True)
