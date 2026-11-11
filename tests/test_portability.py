"""Provider configuration and route identity regressions; no paid CLI calls."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import factory

ROOT = Path(__file__).resolve().parents[1]


class PortableConfigurationTests(unittest.TestCase):
    def configure(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'configure.py'),
                               '--repo', str(self.repo), '--tdd-skill', str(self.skill), *args],
                              capture_output=True, text=True)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        (self.repo / '.infra-factory').mkdir()
        self.path = self.repo / '.infra-factory/config.json'
        self.original = json.dumps({'version': 1, 'commands': {}, 'checks': [['python', '-V']]})
        self.path.write_text(self.original)
        self.skill = self.repo / 'SKILL.md'
        self.skill.write_text('Local TDD instructions')

    def test_provider_profiles_and_preview_preserve_checks(self):
        for provider, model in [('claude', 'claude-test-1'), ('codex', 'test-model-1')]:
            with self.subTest(provider=provider):
                p = self.configure('--provider', provider, '--model', model)
                self.assertEqual(p.returncode, 0, p.stderr)
                config = json.loads(p.stdout)
                self.assertEqual(config['checks'], [['python', '-V']])
                self.assertTrue(all(c['provider'] == provider and c['model'] == model
                                    for c in config['commands'].values()))
                self.assertEqual(self.path.read_text(), self.original)

    def test_policy_roles_use_fresh_reviewer_bridge_for_both_providers(self):
        for provider, model in [('claude', 'claude-test-1'), ('codex', 'test-model-1')]:
            p = self.configure('--provider', provider, '--model', model,
                               '--review-policy', str(ROOT / 'examples/review-policy.json'),
                               '--route', 'risk_assessor=codex:test-risk-model:high')
            self.assertEqual(p.returncode, 0, p.stderr)
            c = json.loads(p.stdout)
            for role in ('reviewer_security', 'reviewer_data', 'reviewer_frontend', 'risk_assessor'):
                self.assertIn('reviewer', c['commands'][role]['argv'])
                self.assertIn('--strict-routing', c['commands'][role]['argv'])
                self.assertNotIn('primary_skill', c['commands'][role])
            self.assertEqual(c['commands']['risk_assessor']['model'], 'test-risk-model')
            self.assertEqual(c['commands']['reviewer_security']['provider'], provider)

    def test_no_implicit_model_ids(self):
        p = self.configure()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('explicit', p.stderr)

    def test_mixed_override_and_backup(self):
        args = ('--provider', 'codex', '--model', 'test-model-1', '--route',
                'reviewer_spec=claude:claude-test-1:high', '--apply')
        p = self.configure(*args)
        self.assertEqual(p.returncode, 0, p.stderr)
        config = json.loads(self.path.read_text())
        self.assertEqual(config['commands']['reviewer_spec']['provider'], 'claude')
        self.assertEqual(self.path.with_suffix('.json.before-cli-config').read_text(), self.original)
        self.assertNotEqual(self.configure(*args).returncode, 0)


class RoutingIdentityTests(unittest.TestCase):
    def test_success_receipt_must_match_configured_route(self):
        spec = {'argv': ['bridge', '--strict-routing'], 'provider': 'codex',
                'model': 'test-model-1', 'effort': 'medium'}
        correct = {'schema': 1, 'outcome': 'ok', 'provider': 'codex',
                   'requested_model': 'test-model-1', 'requested_effort': 'medium',
                   'exit_code': 0, 'served_models_verified': False}
        with tempfile.TemporaryDirectory() as td:
            result = Path(td) / 'result.json'
            receipt = Path(td) / 'result.routing.json'
            for key, wrong in [('provider', 'claude'), ('requested_model', 'other'),
                               ('requested_effort', 'low'), ('schema', 999), ('exit_code', 1)]:
                with self.subTest(field=key):
                    receipt.write_text(json.dumps(dict(correct, **{key: wrong})))
                    with self.assertRaises(factory.FactoryError):
                        factory.routing_evidence(result, spec)
            receipt.write_text(json.dumps(correct))
            result = factory.routing_evidence(result, spec)
            self.assertIs(result['served_models_verified'], False)


if __name__ == '__main__':
    unittest.main()
