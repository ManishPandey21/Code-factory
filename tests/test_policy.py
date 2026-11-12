import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verification_policy import MINIMUM, PolicyError, validate_evidence, validate_policy


def fixtures():
    spec = {s: {'impact': 'Explicit contract for ' + s,
                'acceptance': ['Observable behavior for ' + s]}
            for s in ('ui', 'api', 'data', 'cross_cutting')}
    ticket = {'paths': ['frontend/app.tsx'], 'acceptance': ['User can complete the workflow'], 'spec': spec}
    checks = []
    for domain, kinds in MINIMUM.items():
        for kind in sorted(kinds):
            cid = domain + '-' + kind
            checks.append({'id': cid, 'domains': [domain], 'kind': kind,
                           'argv': ['trusted-test-runner', cid, '{test_mode}'], 'report': 'reports/' + cid + '.json',
                           'min_tests': 1, 'negative_control': {'argv': ['trusted-mutation'], 'expected_failures': ['test']}})
    config = {'verification': {'path_domains': {d: [d] for d in MINIMUM},
                               'required': {}, 'checks': checks}}
    return config, ticket


class PolicyTests(unittest.TestCase):
    def test_frontend_only_requires_all_ui_checks(self):
        c, t = fixtures()
        selected = validate_policy(c, t)
        self.assertEqual({x['kind'] for x in selected}, MINIMUM['frontend'])
        self.assertEqual({d for x in selected for d in x['domains']}, {'frontend'})

    def test_backend_only_requires_service_and_integration(self):
        c, t = fixtures(); t['paths'] = ['backend/service.py']
        self.assertEqual({x['kind'] for x in validate_policy(c, t)}, MINIMUM['backend'])

    def test_both_layers_select_both_suites(self):
        c, t = fixtures(); t['paths'].append('backend/service.py')
        selected = validate_policy(c, t)
        self.assertEqual(len(selected), 8)
        self.assertIn('contract', {x['kind'] for x in selected})

    def test_shared_and_unknown_require_full_stack(self):
        for paths in [['shared/types.ts'], ['package.json'], ['src']]:
            with self.subTest(paths=paths):
                c, t = fixtures(); t['paths'] = paths
                self.assertEqual(len(validate_policy(c, t)), 8)

    def test_parent_directory_matches_descendants(self):
        c, t = fixtures()
        c['verification']['path_domains']['frontend'] = ['src/frontend']
        c['verification']['path_domains']['backend'] = ['src/backend']
        t['paths'] = ['src']
        self.assertEqual(len(validate_policy(c, t)), 8)

    def test_additional_required_kind_cannot_be_missing(self):
        c, t = fixtures(); c['verification']['required'] = {'frontend': ['security']}
        with self.assertRaisesRegex(PolicyError, 'security'):
            validate_policy(c, t)

    def test_minimum_cannot_be_weakened(self):
        c, t = fixtures()
        c['verification']['checks'] = [x for x in c['verification']['checks'] if x['kind'] != 'visual']
        c['verification']['required']['frontend'] = ['unit']
        with self.assertRaisesRegex(PolicyError, 'visual'):
            validate_policy(c, t)

    def test_strict_spec_schema(self):
        for mutation in ['missing', 'empty', 'ambiguous', 'all_na', 'blank_na']:
            c, t = fixtures()
            if mutation == 'missing': del t['spec']['api']
            if mutation == 'empty': t['spec']['ui']['acceptance'] = []
            if mutation == 'ambiguous': t['spec']['ui']['not_applicable'] = 'No UI'
            if mutation == 'all_na': t['spec'] = {s: {'not_applicable': 'Not involved'} for s in t['spec']}
            if mutation == 'blank_na': t['spec']['api'] = {'not_applicable': ' '}
            with self.subTest(mutation=mutation), self.assertRaises(PolicyError):
                validate_policy(c, t)

    def test_justified_non_applicability(self):
        c, t = fixtures(); t['spec']['api'] = {'not_applicable': 'No network/API interaction changes'}
        validate_policy(c, t)

    def test_malformed_configuration_fails_closed(self):
        mutations = [lambda p: p['checks'].append(copy.deepcopy(p['checks'][0])),
                     lambda p: p['checks'][0].update(min_tests=True),
                     lambda p: p['checks'][0].update(domains=['unknown']),
                     lambda p: p['checks'][0].update(kind=[]),
                     lambda p: p['checks'][0].update(argv=[]),
                     lambda p: p['checks'][0].update(report='../escape'),
                     lambda p: p['checks'][0].update(report='C:/escape'),
                     lambda p: p['checks'][0].update(report='.git/config'),
                     lambda p: p['checks'][0].update(report=p['checks'][1]['report']),
                     lambda p: p['path_domains'].update(frontend=['frontend', './frontend']),
                     lambda p: p.update(required={'typo': ['unit']})]
        for i, mutate in enumerate(mutations):
            c, t = fixtures(); mutate(c['verification'])
            with self.subTest(case=i), self.assertRaises(PolicyError):
                validate_policy(c, t)

    def test_no_policy_is_not_legacy_green(self):
        _, t = fixtures()
        with self.assertRaises(PolicyError): validate_policy({'checks': [['true']]}, t)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'report.json'
        self.good = {'status': 'passed', 'total': 3, 'passed': 3, 'failed': 0, 'skipped': 0}
        self.good['tests'] = [{'id': str(i), 'status': 'passed'} for i in range(3)]
        self.check = {'min_tests': 2}

    def write(self, data): self.path.write_text(json.dumps(data), encoding='utf-8')

    def test_passing_counts(self):
        self.write(self.good)
        self.assertEqual(validate_evidence(self.path, self.check), self.good)

    def test_zero_skip_fail_inconsistent_and_bool_never_pass(self):
        for patch in [{'total': 0, 'passed': 0}, {'skipped': 1}, {'failed': 1},
                      {'passed': 2}, {'total': True}, {'status': 'unknown'},
                      {'total': 1, 'passed': 1}, {'total': 3.0}, {'total': -1},
                      {'unexpected': 'field'}]:
            self.write({**self.good, **patch})
            with self.subTest(patch=patch), self.assertRaises(PolicyError):
                validate_evidence(self.path, self.check)

    def test_missing_malformed_duplicate_and_oversize(self):
        with self.assertRaises(PolicyError): validate_evidence(self.path, self.check)
        for content in ['not json', '[]', '{"status":"failed","status":"passed"}', ' ' * (1024 * 1024 + 1)]:
            self.path.write_text(content, encoding='utf-8')
            with self.assertRaises(PolicyError): validate_evidence(self.path, self.check)

    def test_report_or_parent_symlink_rejected(self):
        actual = Path(self.temp.name) / 'actual'; actual.mkdir()
        (actual / 'report.json').write_text(json.dumps(self.good), encoding='utf-8')
        self.path.symlink_to(actual / 'report.json')
        with self.assertRaises(PolicyError): validate_evidence(self.path, self.check)
        link = Path(self.temp.name) / 'link'; link.symlink_to(actual, target_is_directory=True)
        with self.assertRaises(PolicyError): validate_evidence(link / 'report.json', self.check)


if __name__ == '__main__':
    unittest.main()
