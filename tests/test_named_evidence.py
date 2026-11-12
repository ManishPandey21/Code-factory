"""Evidence must identify real tests and demonstrate assertion sensitivity."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_report import parse_junit, ReportError
from verification_policy import validate_evidence, PolicyError
from evidence import validate_review_evidence
from runtime import FactoryError


class NamedEvidenceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'report'

    def test_names_survive_native_normalization(self):
        self.path.write_text('<testsuite name="api"><testcase classname="Login" name="rejects_bad_password"/></testsuite>')
        data = parse_junit(self.path)
        self.assertEqual(data['tests'], [{'id': '["api","Login","rejects_bad_password"]', 'status': 'passed'}])

    def test_unnamed_and_duplicate_tests_rejected(self):
        for cases in ['<testcase/>', '<testcase name="same"/><testcase name="same"/>']:
            self.path.write_text('<testsuite>' + cases + '</testsuite>')
            with self.assertRaises(ReportError): parse_junit(self.path)

    def test_headcounts_alone_rejected(self):
        self.path.write_text(json.dumps(dict(status='passed', total=1, passed=1, failed=0, skipped=0)))
        with self.assertRaises(PolicyError): validate_evidence(self.path, {'min_tests': 1})

    def test_negative_control_requires_assertion_failure_not_error(self):
        self.path.write_text('<testsuite><testcase name="behavior"><failure type="AssertionError"/></testcase></testsuite>')
        self.assertEqual(parse_junit(self.path, expect_failure=True)['tests'][0]['status'], 'failed')
        self.path.write_text('<testsuite><testcase name="behavior"><error/></testcase></testsuite>')
        with self.assertRaises(ReportError): parse_junit(self.path, expect_failure=True)

    def test_review_must_cite_observed_test_ids(self):
        ticket = {'acceptance': ['reject invalid password'], 'spec': {s: {} for s in ('ui', 'api', 'data', 'cross_cutting')}}
        evidence = {'digest': 'digest', 'files': ['login.py'], 'checks': [
            {'id': 'api', 'counts': {'tests': [{'id': 'test_login', 'status': 'passed'}]}}]}
        review = dict(verdict='PASS', evidence_digest='digest', tests_confirmed=True,
                      covered_files=['login.py'], acceptance_covered=[0])
        with self.assertRaises(FactoryError): validate_review_evidence(review, evidence, ticket)
        review['acceptance_tests'] = [{'acceptance': 0, 'tests': [{'check': 'api', 'test': 'invented'}]}]
        with self.assertRaises(FactoryError): validate_review_evidence(review, evidence, ticket)
        review['acceptance_tests'][0]['tests'][0]['test'] = 'test_login'
        validate_review_evidence(review, evidence, ticket)


class AssertionClassificationTests(unittest.TestCase):
    def test_runtime_and_unknown_failures_cannot_count_as_assertions(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'report.xml'
            for attrs in ['type="RuntimeError" message="application crashed"',
                          'message="RuntimeError: crashed"', '',
                          'type="ValueError" message="assert bogus"']:
                path.write_text('<testsuite><testcase name="test"><failure ' + attrs + '/></testcase></testsuite>')
                with self.subTest(attrs=attrs), self.assertRaises(ReportError):
                    parse_junit(path, expect_failure=True)
            for attrs in ['type="AssertionError"', 'message="assert 41 == 42"',
                          'message="AssertionError: expected value"']:
                path.write_text('<testsuite><testcase name="test"><failure ' + attrs + '/></testcase></testsuite>')
                self.assertEqual(parse_junit(path, expect_failure=True)['failed'], 1)


class NegativeInventoryTests(unittest.TestCase):
    def test_missing_renamed_unexpected_and_surviving_tests_are_rejected(self):
        from evidence import validate_negative_result
        check = {'negative_control': {'expected_failures': ['behavior']}}
        passing = {'tests': [{'id': 'behavior', 'status': 'passed'}, {'id': 'regression', 'status': 'passed'}]}
        valid = {'tests': [{'id': 'behavior', 'status': 'failed'}, {'id': 'regression', 'status': 'passed'}]}
        validate_negative_result(check, passing, valid)
        bad = [[], [{'id': 'behavior', 'status': 'failed'}],
               [{'id': 'invented', 'status': 'failed'}, {'id': 'regression', 'status': 'passed'}],
               [{'id': 'behavior', 'status': 'passed'}, {'id': 'regression', 'status': 'failed'}],
               [{'id': 'behavior', 'status': 'failed'}, {'id': 'regression', 'status': 'failed'}],
               passing['tests']]
        for tests in bad:
            with self.subTest(tests=tests), self.assertRaises(FactoryError):
                validate_negative_result(check, passing, {'tests': tests})
