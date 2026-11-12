"""0.3.4 regressions: pinned model/effort routing, served-model checks, routing evidence,
risk/complexity routing, reviewer escalation, and attempt history across replacement tickets.

Fixtures are fake CLIs; nothing here calls a model provider.
"""
import importlib.util
import contextlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name + '_under_test', ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(ROOT))
    return module


# A fake `claude` that records its argv and environment and answers like the real CLI.
# Knobs come from a JSON file (reviewer profiles scrub the environment): 'served' overrides the
# model reported in modelUsage, 'fail' makes it an error envelope, 'result' sets the final text.
FAKE_CLAUDE = r'''
import json, os, sys
from pathlib import Path
prompt = sys.stdin.read()
knobs = json.loads(Path(KNOBS).read_text())
Path(knobs['witness']).write_text(json.dumps({
    'argv': sys.argv[1:], 'effort_env': os.environ.get('CLAUDE_CODE_EFFORT_LEVEL'),
    'no_fallback': os.environ.get('CLAUDE_CODE_NO_MODEL_FALLBACK'),
    'remap': os.environ.get('ANTHROPIC_DEFAULT_OPUS_MODEL'), 'model_env': os.environ.get('ANTHROPIC_MODEL')}))
model = sys.argv[sys.argv.index('--model') + 1]
served = knobs.get('served', model)
result = knobs.get('result', 'done')
fail = bool(knobs.get('fail'))
env = {'type': 'result', 'is_error': fail, 'result': 'There is an issue with the selected model' if fail else result,
       'modelUsage': {} if fail else {served: {'inputTokens': 10, 'outputTokens': 5, 'costUSD': 0.01}},
       'duration_ms': 1200, 'num_turns': 3, 'total_cost_usd': 0.01,
       'permission_denials': [{'tool_name': 'Bash', 'tool_input': {'command': 'npm ci'}}]}
if sys.argv[sys.argv.index('--output-format') + 1] == 'stream-json':
    print(json.dumps({'type': 'system', 'subtype': 'init', 'model': model}))
    print(json.dumps({'type': 'assistant', 'message': {'model': served}}))
print(json.dumps(env))
sys.exit(1 if fail else 0)
'''

FAKE_CODEX = r'''
import json, os, sys
from pathlib import Path
sys.stdin.read()
knobs = json.loads(Path(KNOBS).read_text())
Path(knobs['witness']).write_text(json.dumps({'argv': sys.argv[1:]}))
Path(sys.argv[sys.argv.index('--output-last-message') + 1]).write_text(knobs.get('result', 'built'))
'''


@unittest.skipUnless(os.name == 'posix', 'Executable fixture uses POSIX shebang')
class StrictBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.bin = self.d / 'bin'
        self.bin.mkdir()
        for name, body in (('claude', FAKE_CLAUDE), ('codex', FAKE_CODEX)):
            f = self.bin / name
            f.write_text('#!' + sys.executable + '\n' + body.replace('KNOBS', repr(str(self.d / 'knobs.json'))), encoding='utf-8')
            f.chmod(0o755)
        self.home = self.d / 'home'
        (self.home / '.claude').mkdir(parents=True)
        (self.home / '.claude' / '.credentials.json').write_text('{"fixture": true}', encoding='utf-8')
        (self.d / 'prompt.txt').write_text('Do the work', encoding='utf-8')
        self.work = self.d / 'work'
        self.work.mkdir()
        self.witness = self.d / 'witness.json'
        self.result = self.d / 'logs' / 'builder-result.json'
        self.result.parent.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def bridge(self, *extra, provider='claude', mode='builder', model='claude-opus-5-5', effort='high',
               served=None, result=None, fail=False, **env):
        knobs = {'witness': str(self.witness), 'fail': fail}
        if served:
            knobs['served'] = served
        if result is not None:
            knobs['result'] = result
        (self.d / 'knobs.json').write_text(json.dumps(knobs), encoding='utf-8')
        environment = {k: v for k, v in os.environ.items() if not k.startswith(('FAKE_', 'CLAUDE_CODE_', 'ANTHROPIC_'))}
        environment.update({'PATH': str(self.bin) + os.pathsep + os.environ['PATH'], 'HOME': str(self.home),
                            'CLAUDE_CONFIG_DIR': str(self.home / '.claude'), 'FAKE_WITNESS': str(self.witness)})
        environment.update(env)
        argv = [sys.executable, str(ROOT / 'agent_bridge.py'), '--provider', provider, '--mode', mode,
                '--model', model, '--prompt-file', str(self.d / 'prompt.txt'), '--result-file', str(self.result),
                '--strict-routing']
        if effort:
            argv += ['--effort', effort]
        return subprocess.run(argv + list(extra), cwd=self.work, env=environment, capture_output=True, text=True, encoding='utf-8')

    def evidence(self):
        return json.loads(self.result.with_name('builder-result.routing.json').read_text(encoding='utf-8'))

    def test_effort_flag_and_env_agree_even_when_the_environment_says_otherwise(self):
        p = self.bridge(effort='medium', CLAUDE_CODE_EFFORT_LEVEL='max', ANTHROPIC_DEFAULT_OPUS_MODEL='claude-x-1-0',
                        ANTHROPIC_MODEL='claude-y-1-0')
        self.assertEqual(p.returncode, 0, p.stderr)
        w = json.loads(self.witness.read_text(encoding='utf-8'))
        self.assertEqual(w['argv'][w['argv'].index('--effort') + 1], 'medium')
        self.assertEqual(w['effort_env'], 'medium', 'CLAUDE_CODE_EFFORT_LEVEL overrides --effort in the CLI')
        self.assertEqual(w['no_fallback'], '1')
        self.assertIsNone(w['remap'])
        self.assertIsNone(w['model_env'])
        self.assertNotIn('--fallback-model', w['argv'])
        ev = self.evidence()
        self.assertEqual((ev['outcome'], ev['requested_model'], ev['requested_effort']), ('ok', 'claude-opus-5-5', 'medium'))
        self.assertEqual(ev['effort_controls']['removed_overrides'], ['ANTHROPIC_DEFAULT_OPUS_MODEL', 'ANTHROPIC_MODEL'])
        self.assertEqual(list(ev['served_models']), ['claude-opus-5-5'])
        self.assertEqual(ev['permission_denials'], ['Bash'])
        self.assertNotIn('npm ci', json.dumps(ev), 'tool inputs are not copied into evidence')
        self.assertNotIn('fixture', json.dumps(ev), 'credentials never enter evidence')

    def test_builder_transcript_is_kept(self):
        p = self.bridge()
        self.assertEqual(p.returncode, 0, p.stderr)
        transcript = self.result.with_name('builder-result.transcript.jsonl')
        self.assertEqual(json.loads(transcript.read_text(encoding='utf-8').splitlines()[0])['subtype'], 'init')
        self.assertEqual(json.loads(self.result.read_text(encoding='utf-8')), {'summary': 'done'})

    def test_low_medium_high_reach_the_cli(self):
        for effort in ('low', 'medium', 'high'):
            for f in self.result.parent.iterdir():
                f.unlink()
            p = self.bridge(effort=effort)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(self.witness.read_text(encoding='utf-8'))['effort_env'], effort)

    def test_strict_routing_requires_an_effort(self):
        p = self.bridge(effort=None)
        self.assertEqual(p.returncode, 2)
        self.assertIn('requires --effort', p.stderr)
        self.assertEqual(self.evidence()['outcome'], 'routing_refused')
        self.assertFalse(self.witness.exists(), 'the CLI must not run')

    def test_unknown_effort_is_rejected_before_the_cli(self):
        p = self.bridge(effort='ultra')
        self.assertEqual(p.returncode, 2)
        self.assertFalse(self.witness.exists())

    def test_alias_model_is_refused(self):
        p = self.bridge(model='opus')
        self.assertEqual(p.returncode, 2)
        self.assertIn('not a full Claude model id', p.stderr)
        self.assertFalse(self.witness.exists())

    def test_unavailable_model_fails_closed_with_evidence(self):
        p = self.bridge(model='claude-nonexistent-9-9', fail=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(self.result.exists())
        self.assertEqual(self.evidence()['outcome'], 'cli_failed')

    def test_substituted_model_is_refused(self):
        p = self.bridge(served='claude-sonnet-5-5')
        self.assertEqual(p.returncode, 2)
        self.assertIn('did not serve this run', p.stderr)
        self.assertFalse(self.result.exists(), 'no result from a downgraded run')
        ev = self.evidence()
        self.assertEqual(ev['outcome'], 'routing_refused')
        self.assertEqual(list(ev['served_models']), ['claude-sonnet-5-5'])

    def test_effort_cap_in_settings_is_refused_not_clamped(self):
        (self.work / '.claude').mkdir()
        (self.work / '.claude' / 'settings.json').write_text(json.dumps({'maxEffortLevel': 'medium'}), encoding='utf-8')
        p = self.bridge(effort='high')
        self.assertEqual(p.returncode, 2)
        self.assertIn('maxEffortLevel', p.stderr)
        self.assertFalse(self.witness.exists())
        p = self.bridge(effort='medium')   # at the cap is fine
        self.assertEqual(p.returncode, 2, 'stale evidence from the refused run must block reuse')
        for f in self.result.parent.iterdir():
            f.unlink()
        p = self.bridge(effort='medium')
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_stale_routing_evidence_is_refused(self):
        self.result.with_name('builder-result.routing.json').write_text('{"outcome": "ok"}', encoding='utf-8')
        p = self.bridge()
        self.assertEqual(p.returncode, 2)
        self.assertIn('stale evidence', p.stderr)

    def test_reviewer_gets_effort_in_its_scrubbed_profile(self):
        self.result = self.d / 'logs' / 'review-spec-result.json'
        p = self.bridge(mode='reviewer', model='claude-fable-5-2', CLAUDE_CODE_EFFORT_LEVEL='low',
                        result=json.dumps({'verdict': 'PASS', 'reviewed_head': 'a', 'base': 'b', 'findings': []}))
        self.assertEqual(p.returncode, 0, p.stderr)
        w = json.loads(self.witness.read_text(encoding='utf-8'))
        self.assertEqual(w['effort_env'], 'high')
        self.assertEqual(w['argv'][w['argv'].index('--permission-mode') + 1], 'plan')
        ev = json.loads(self.result.with_name('review-spec-result.routing.json').read_text(encoding='utf-8'))
        self.assertEqual((ev['mode'], ev['requested_model'], ev['outcome']), ('reviewer', 'claude-fable-5-2', 'ok'))

    def test_codex_remains_supported_with_explicit_effort(self):
        p = self.bridge(provider='codex', model='gpt-6.1-sol', effort='medium')
        self.assertEqual(p.returncode, 0, p.stderr)
        argv = json.loads(self.witness.read_text(encoding='utf-8'))['argv']
        self.assertEqual(argv[argv.index('-c') + 1], 'model_reasoning_effort="medium"')
        self.assertFalse(self.evidence()['served_models_verified'])
        for f in self.result.parent.iterdir():
            f.unlink()
        p = self.bridge(provider='codex', model='gpt-6.1-sol', effort='max')
        self.assertEqual(p.returncode, 2)

    def test_legacy_configuration_is_unchanged(self):
        (self.d / 'knobs.json').write_text(json.dumps({'witness': str(self.witness)}), encoding='utf-8')
        environment = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'])
        p = subprocess.run([sys.executable, str(ROOT / 'agent_bridge.py'), '--provider', 'claude', '--mode', 'builder',
                            '--model', 'sonnet', '--prompt-file', str(self.d / 'prompt.txt'),
                            '--result-file', str(self.result)], cwd=self.work, env=environment, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn('--effort', json.loads(self.witness.read_text(encoding='utf-8'))['argv'])
        self.assertFalse(self.result.with_name('builder-result.routing.json').exists())


class RoutingSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = load('factory')

    def config(self, *roles):
        return {'commands': {r: {'argv': ['x', r]} for r in roles}}

    def ticket(self, role='frontend', **extra):
        return dict({'id': 'T', 'role': role}, **extra)

    def test_builder_routes_by_complexity_and_risk(self):
        c = self.config('frontend', 'backend', 'critical', 'builder_routine', 'builder_complex', 'builder_critical')
        self.assertEqual(self.f.builder_key(c, self.ticket('frontend')), 'builder_routine')
        self.assertEqual(self.f.builder_key(c, self.ticket('backend', complexity='complex')), 'builder_complex')
        self.assertEqual(self.f.builder_key(c, self.ticket('critical', complexity='routine')), 'builder_critical')

    def test_older_configurations_still_route_by_role(self):
        c = self.config('frontend', 'backend', 'critical')
        self.assertEqual(self.f.builder_key(c, self.ticket('backend', complexity='complex')), 'backend')

    def test_critical_tickets_escalate_reviewers_when_configured(self):
        c = self.config('reviewer_spec', 'reviewer_standards', 'reviewer_spec_critical')
        self.assertEqual(self.f.reviewer_spec_for(c, self.ticket('critical'), 'spec')['argv'][1], 'reviewer_spec_critical')
        self.assertEqual(self.f.reviewer_spec_for(c, self.ticket('critical'), 'standards')['argv'][1], 'reviewer_standards')
        self.assertEqual(self.f.reviewer_spec_for(c, self.ticket('frontend'), 'spec')['argv'][1], 'reviewer_spec')

    def test_unknown_complexity_is_rejected(self):
        t = {'id': 'T', 'title': 't', 'description': 'd', 'acceptance': ['a'], 'paths': ['src/a.py'],
             'depends_on': [], 'role': 'frontend', 'complexity': 'trivial',
             'spec': {'ui': {'impact': 'x', 'acceptance': ['y']}, 'api': {'not_applicable': 'n'},
                      'data': {'not_applicable': 'n'}, 'cross_cutting': {'not_applicable': 'n'}}}
        with self.assertRaises(self.f.FactoryError):
            self.f.validate_ticket(t)

    def test_missing_routing_evidence_fails_closed_for_strict_commands(self):
        with tempfile.TemporaryDirectory() as td:
            result = Path(td) / 'review-spec-result.json'
            with self.assertRaises(self.f.FactoryError):
                self.f.routing_evidence(result, {'argv': ['bridge', '--strict-routing']})
            self.assertIsNone(self.f.routing_evidence(result, {'argv': ['bridge']}))
            result.with_name('review-spec-result.routing.json').write_text(json.dumps({'outcome': 'routing_refused'}), encoding='utf-8')
            with self.assertRaises(self.f.FactoryError):
                self.f.routing_evidence(result, {'argv': ['bridge', '--strict-routing']})


class AttemptHistoryTests(unittest.TestCase):
    """Replacement tickets inherit attempts; renaming never grants a fresh budget."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / 'repo'
        self.repo.mkdir()
        env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@x', GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@x')
        for cmd in (['git', 'init', '-q', '-b', 'main'], ['git', 'commit', '-q', '--allow-empty', '-m', 'base']):
            subprocess.run(cmd, cwd=self.repo, env=env, check=True)
        self.factory(['init', '--repo', str(self.repo), '--apply'])
        self.db = self.repo / '.git' / 'infra-factory' / 'ledger.sqlite3'

    def tearDown(self):
        self.tmp.cleanup()

    def factory(self, args, check=True):
        p = subprocess.run([sys.executable, str(ROOT / 'factory.py')] + args, capture_output=True, text=True, encoding='utf-8')
        if check:
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def add(self, tid, check=True, **extra):
        t = {'id': tid, 'title': 'Edit vitals', 'description': 'd', 'acceptance': ['a'], 'paths': ['src/a.py', 'tests/test_a.py'],
             'depends_on': [], 'role': 'frontend',
             'spec': {'ui': {'impact': 'x', 'acceptance': ['y']}, 'api': {'not_applicable': 'n'},
                      'data': {'not_applicable': 'n'}, 'cross_cutting': {'not_applicable': 'n'}}}
        t.update(extra)
        path = Path(self.tmp.name) / (tid + '.json')
        path.write_text(json.dumps(t), encoding='utf-8')
        return self.factory(['add', '--repo', str(self.repo), '--ticket', str(path)], check)

    def set_state(self, tid, state, attempts):
        with contextlib.closing(sqlite3.connect(self.db)) as con, con:
            con.execute('UPDATE tickets SET state=?, attempts=? WHERE id=?', (state, attempts, tid))

    def row(self, tid):
        with contextlib.closing(sqlite3.connect(self.db)) as con, con:
            con.row_factory = sqlite3.Row
            return dict(con.execute('SELECT * FROM tickets WHERE id=?', (tid,)).fetchone())

    def test_renamed_ticket_without_supersedes_is_refused(self):
        self.add('U02-B')
        self.set_state('U02-B', 'BLOCKED', 2)
        p = self.add('U02-C', check=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('declare "supersedes": ["U02-B"]', p.stdout + p.stderr)
        self.assertEqual(self.row('U02-B')['attempts'], 2)

    def test_replacement_inherits_attempts_and_closes_the_old_ticket(self):
        self.add('U02-B')
        self.set_state('U02-B', 'BLOCKED', 2)
        p = self.add('U02-C', supersedes=['U02-B'])
        self.assertEqual(json.loads(p.stdout)['attempts_used'], 2)
        self.assertEqual(self.row('U02-C')['attempts'], 2)
        old = self.row('U02-B')
        self.assertEqual((old['state'], old['attempts']), ('REJECTED', 2))
        self.assertIn('Superseded by U02-C', old['error'])

    def test_exhausted_history_cannot_be_renamed_into_a_new_budget(self):
        self.add('U02-B')
        self.set_state('U02-B', 'BLOCKED', 3)
        p = self.add('U02-C', check=False, supersedes=['U02-B'])
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('already used all attempts', p.stdout + p.stderr)

    def test_active_or_ready_tickets_cannot_be_superseded(self):
        self.add('U02-B')
        self.set_state('U02-B', 'READY', 1)
        p = self.add('U02-C', check=False, supersedes=['U02-B'])
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('only PENDING, BLOCKED or REJECTED', p.stdout + p.stderr)

    def test_retry_keeps_the_attempt_count(self):
        self.add('U02-B')
        self.set_state('U02-B', 'BLOCKED', 2)
        p = self.factory(['retry', '--repo', str(self.repo), '--ticket', 'U02-B'])
        self.assertEqual(json.loads(p.stdout)['attempts_used'], 2)
        self.assertEqual(self.row('U02-B')['attempts'], 2)

    def test_different_paths_need_no_supersedes(self):
        self.add('U02-B')
        self.set_state('U02-B', 'BLOCKED', 2)
        self.add('U03', paths=['src/b.py'])
        self.assertEqual(self.row('U03')['attempts'], 0)


class ConfigureTests(unittest.TestCase):
    def test_every_role_is_pinned_with_effort_and_strict_routing(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / '.infra-factory').mkdir()
            (repo / '.infra-factory' / 'config.json').write_text(json.dumps({'version': 1, 'commands': {}}), encoding='utf-8')
            skill = repo / 'SKILL.md'
            skill.write_text('tdd', encoding='utf-8')
            p = subprocess.run([sys.executable, str(ROOT / 'configure.py'), '--repo', str(repo), '--tdd-skill', str(skill),
                                '--provider', 'claude', '--model', 'claude-test-1',
                                '--route', 'builder_routine=codex:gpt-6.1-sol:medium'], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(p.returncode, 0, p.stderr)
            commands = json.loads(p.stdout)['commands']
            for role, spec in commands.items():
                self.assertIn('--strict-routing', spec['argv'], role)
                self.assertEqual(spec['argv'][spec['argv'].index('--effort') + 1], spec['effort'], role)
            self.assertEqual(commands['builder_routine']['provider'], 'codex')
            self.assertEqual(commands['reviewer_spec_critical']['model'], 'claude-test-1')
            self.assertNotIn('fable', json.dumps({k: v['model'] for k, v in commands.items() if 'critical' not in k}))
            bad = subprocess.run([sys.executable, str(ROOT / 'configure.py'), '--repo', str(repo), '--tdd-skill', str(skill),
                                  '--route', 'builder_routine=codex:gpt-6.1-sol:xhigh'], capture_output=True, text=True, encoding='utf-8')
            self.assertNotEqual(bad.returncode, 0)


if __name__ == '__main__':
    unittest.main()
