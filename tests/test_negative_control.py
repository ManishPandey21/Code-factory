"""End-to-end mutation checks using real unittest assertions and native JUnit."""
import json
from pathlib import Path
import sys
import unittest
import test_factory as fixtures

ROOT = Path(__file__).resolve().parents[1]
TEST_ID = '["behavior","Value","test_value"]'
RUNNER = '''import runpy, sys, unittest
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, ElementTree
class Value(unittest.TestCase):
    def test_value(self):
        self.assertEqual(runpy.run_path('A.py')['value'], 42)
suite = unittest.defaultTestLoader.loadTestsFromTestCase(Value)
result = unittest.TextTestRunner().run(suite)
root = Element('testsuite', name='behavior', tests='1')
case = SubElement(root, 'testcase', classname='Value', name='test_value')
for _, message in result.failures:
    SubElement(case, 'failure', type='AssertionError').text = message
for _, message in result.errors:
    SubElement(case, 'error').text = message
Path('.test-output').mkdir(exist_ok=True)
ElementTree(root).write('.test-output/native.xml')
sys.exit(not result.wasSuccessful())
'''


class NegativeControlTests(unittest.TestCase):
    # Share fixture setup without inheriting/discovering the whole existing suite.
    setUp = fixtures.FactoryTests.setUp
    tearDown = fixtures.FactoryTests.tearDown
    git = fixtures.FactoryTests.git
    commit = fixtures.FactoryTests.commit
    cli = fixtures.FactoryTests.cli
    add = fixtures.FactoryTests.add
    states = fixtures.FactoryTests.states

    def configure_probe(self, mutation="Path('A.py').write_text('value = 41\\n')"):
        runner = self.home / 'native_runner.py'; runner.write_text(RUNNER, encoding='utf-8')
        (self.repo / '.gitignore').write_text('.test-output/\n', encoding='utf-8')
        config = json.loads(self.cfg.read_text(encoding='utf-8'))
        # One genuine behavior probe is sufficient to exercise the transport;
        # other check categories retain their explicit orchestration fixtures.
        check = config['verification']['checks'][0]
        check['argv'] = [sys.executable, str(ROOT / 'test_report.py'), '--report', '{report}',
                         '--junit', '.test-output/native.xml', '--mode', '{test_mode}',
                         '--', sys.executable, str(runner)]
        check['negative_control'] = {'argv': [sys.executable, '-c', 'from pathlib import Path; ' + mutation],
                                     'expected_failures': [TEST_ID]}
        self.cfg.write_text(json.dumps(config), encoding='utf-8'); self.commit()
        self.add('A')

    def test_real_assertion_fails_on_mutation_and_original_stays_green(self):
        self.configure_probe(); self.cli('run', '--execute')
        row = self.states()['A']; self.assertEqual(row['state'], 'READY')
        self.assertEqual((Path(row['worktree']) / 'A.py').read_text(encoding='utf-8'), 'value = 42\n')
        check = row['review_json']['lenses']['spec']['evidence']['checks'][0]
        self.assertEqual(check['counts']['tests'], [{'id': TEST_ID, 'status': 'passed'}])
        self.assertEqual(check['negative_control']['counts']['tests'], [{'id': TEST_ID, 'status': 'failed'}])
        self.cli('publish', '--ticket', 'A')
        Path(check['negative_control']['diff']).write_text('tampered', encoding='utf-8')
        self.assertFalse(self.states()['A']['verification_current'])
        self.cli('publish', '--ticket', 'A', code=2)

    def test_surviving_mutation_blocks_before_review(self):
        self.configure_probe("Path('A.py').write_text('value = 42 # still works\\n')")
        self.cli('run', '--execute', code=1)
        self.assertEqual(self.states()['A']['state'], 'BLOCKED')
        self.assertFalse(list(self.events.glob('*reviewer*.json')))

    def test_crash_is_not_a_detected_defect(self):
        self.configure_probe("Path('A.py').write_text('raise RuntimeError(123)\\n')")
        self.cli('run', '--execute', code=1)
        self.assertEqual(self.states()['A']['state'], 'BLOCKED')

    def test_mutating_tests_is_rejected(self):
        self.configure_probe("Path('test_fake.py').write_text('assert False\\n')")
        self.cli('run', '--execute', code=1)
        self.assertIn('test or protected input', self.states()['A']['error'])

    def test_no_mutation_is_rejected(self):
        self.configure_probe('pass')
        self.cli('run', '--execute', code=1)
        self.assertIn('must modify production files', self.states()['A']['error'])


    def test_suffix_colliding_check_ids_retain_distinct_artifacts(self):
        config = json.loads(self.cfg.read_text(encoding='utf-8'))
        config['verification']['checks'][1]['id'] = config['verification']['checks'][0]['id'] + '-negative'
        self.cfg.write_text(json.dumps(config), encoding='utf-8'); self.commit(); self.add('A')
        self.cli('run', '--execute')
        evidence = self.states()['A']['review_json']['lenses']['spec']['evidence']
        reports = [check['report'] for check in evidence['checks']]
        negative_reports = [check['negative_control']['report'] for check in evidence['checks']]
        self.assertEqual(len(set(reports + negative_reports)), 2 * len(evidence['checks']))
        for check in evidence['checks']:
            directory = Path(check['report']).parent.parent
            self.assertIn(str(directory / 'positive.log'), evidence['artifacts'])
        self.cli('publish', '--ticket', 'A')
