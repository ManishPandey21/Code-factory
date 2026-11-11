"""Native-report transport fixtures, not claims of frontend/backend coverage."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_report import ReportError, parse_junit


class NativeReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.cwd = Path(self.tmp.name)
        self.report = self.cwd / 'normalized.json'
        self.native = self.cwd / 'native.xml'

    def cli(self, code, expected=0, **kwargs):
        args = [sys.executable, str(ROOT / 'test_report.py'), '--report', str(self.report),
                '--junit', kwargs.pop('junit', 'native.xml'), '--timeout', str(kwargs.pop('timeout', 5)),
                '--', sys.executable, '-c', code]
        result = subprocess.run(args, cwd=self.cwd, capture_output=True, text=True, timeout=10, encoding='utf-8')
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def writer(self, xml, exit_code=0):
        return 'from pathlib import Path; Path("native.xml").write_text(' + repr(xml) + '); raise SystemExit(' + str(exit_code) + ')'

    def test_actual_native_testcase_counts_written(self):
        self.cli(self.writer('<testsuites><testsuite tests="2"><testcase name="one"/><testcase name="two"/></testsuite></testsuites>'))
        self.assertEqual(json.loads(self.report.read_text(encoding='utf-8')),
                         {'status': 'passed', 'total': 2, 'passed': 2, 'failed': 0, 'skipped': 0})

    def test_nonzero_exit_rejects_even_green_native_report(self):
        self.cli(self.writer('<testsuite><testcase/></testsuite>', 1), expected=2)
        self.assertFalse(self.report.exists())

    def test_no_tests_missing_failed_skipped_and_suite_error(self):
        cases = [None, '<testsuite/>', '<testsuite><testcase><failure/></testcase></testsuite>',
                 '<testsuite><testcase><skipped/></testcase></testsuite>',
                 '<testsuite><testcase/><error/></testsuite>',
                 '<testsuite failures="1"><testcase/></testsuite>',
                 '<testsuite tests="99"><testcase/></testsuite>',
                 '<testsuite><testcase status="notrun"/></testsuite>',
                 '<testsuite><testcase result="suppressed"/></testsuite>']
        for xml in cases:
            self.native.unlink(missing_ok=True)
            with self.subTest(xml=xml):
                self.cli('pass' if xml is None else self.writer(xml), expected=2)
                self.assertFalse(self.report.exists())

    def test_preexisting_native_never_reused(self):
        self.native.write_text('<testsuite><testcase/></testsuite>', encoding='utf-8')
        self.cli('raise SystemExit("command should not run")', expected=2)
        self.assertFalse(self.report.exists())

    def test_preexisting_normalized_is_not_overwritten(self):
        self.report.write_text('original', encoding='utf-8')
        self.cli(self.writer('<testsuite><testcase/></testsuite>'), expected=2)
        self.assertEqual(self.report.read_text(encoding='utf-8'), 'original')
        self.assertFalse(self.native.exists())

    def test_timeout_has_no_normalized_report(self):
        result = self.cli('import time; time.sleep(5)', expected=2, timeout=0.05)
        self.assertIn('timed out', result.stderr)
        self.assertFalse(self.report.exists())

    def test_traversal_and_absolute_native_paths_rejected(self):
        for path in ['../escape.xml', '/tmp/escape.xml', '.git/result.xml', 'C:/escape.xml']:
            with self.subTest(path=path):
                self.cli('pass', expected=2, junit=path)

    def test_symlink_report_or_parent_rejected(self):
        elsewhere = self.cwd / 'elsewhere'; elsewhere.mkdir()
        self.native.symlink_to(elsewhere / 'report.xml')
        self.cli('pass', expected=2)
        self.native.unlink()
        (self.cwd / 'link').symlink_to(elsewhere, target_is_directory=True)
        self.cli('pass', expected=2, junit='link/report.xml')

    def test_test_process_cannot_replace_normalized_report(self):
        code = self.writer('<testsuite><testcase/></testsuite>').split('; raise SystemExit')[0]
        code += '; Path("normalized.json").write_text("untrusted")'
        self.cli(code, expected=2)
        self.assertEqual(self.report.read_text(encoding='utf-8'), 'untrusted')

    def test_unsafe_and_oversized_xml_rejected(self):
        for raw in [b'<!DOCTYPE x [<!ENTITY x "entity">]><testsuite><testcase/></testsuite>',
                    '<!DOCTYPE x><testsuite><testcase/></testsuite>'.encode('utf-16'),
                    b'x' * (16 * 1024 * 1024 + 1), b'<broken>']:
            self.native.write_bytes(raw)
            with self.assertRaises(ReportError): parse_junit(self.native)


if __name__ == '__main__': unittest.main()
