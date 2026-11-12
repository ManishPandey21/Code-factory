#!/usr/bin/env python3
"""Run a native JUnit-producing test command and normalize successful evidence.

Example invocations (run from a fresh verifier checkout):
  python /trusted/test_report.py --report /tmp/run/unit.json --junit unit.xml -- \
    python -m pytest --junitxml=unit.xml
  python /trusted/test_report.py --report /tmp/run/components.json --junit components.xml -- \
    npx vitest run --reporter=junit --outputFile=components.xml
  PLAYWRIGHT_JUNIT_OUTPUT_FILE=e2e.xml python /trusted/test_report.py \
    --report /tmp/run/e2e.json --junit e2e.xml -- npx playwright test --reporter=junit

Configure a separate command for each required suite. This adapter retains named
testcase outcomes; it does not infer test categories, coverage, assertions, or
visual quality from filenames or aggregate counts. Test commands/runners must be
trusted. --mode fail accepts only a nonzero native exit with named assertion
failures (no errors/skips); the controller compares them with the passing inventory.
Neither a successful exit code nor hand-supplied counts are evidence.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
from pathlib import Path, PurePosixPath
import signal
import subprocess
import sys
import xml.etree.ElementTree as ET

MAX_XML_BYTES = 16 * 1024 * 1024


class ReportError(ValueError):
    pass


def no_symlinks(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ReportError('Report paths must not contain symlinks')
    return path


def native_path(value):
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or not path.parts or '..' in path.parts or
            any(c in value for c in '\\:*?\x00\n\r') or
            any(p.lower() in {'.git', '.infra-factory', '.claude', '.codex', '.agents', '.github'} for p in path.parts)):
        raise ReportError('--junit must be a literal relative path within the checkout')
    return no_symlinks(Path.cwd() / path)


def parse_junit(path, expect_failure=False):
    path = no_symlinks(path)
    if not path.is_file() or path.stat().st_size > MAX_XML_BYTES:
        raise ReportError('Native JUnit report missing, non-regular or oversized')
    raw = path.read_bytes()
    # Reject declarations independently of encoding (including UTF-16/32 NULs).
    declarations = raw.replace(b'\x00', b'').upper()
    if b'<!DOCTYPE' in declarations or b'<!ENTITY' in declarations:
        raise ReportError('DTD/entity declarations are prohibited')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ReportError(f'Invalid JUnit XML: {exc}') from exc
    def local(tag):
        return tag.rsplit('}', 1)[-1] if isinstance(tag, str) else ''
    if local(root.tag) not in {'testsuite', 'testsuites'}:
        raise ReportError('Expected JUnit testsuite/testsuites root')
    cases = [node for node in root.iter() if local(node.tag) == 'testcase']
    total = len(cases)
    failed = sum(any(local(child.tag) in {'failure', 'error'} for child in node.iter()) for node in cases)
    skipped = sum(any(local(child.tag) == 'skipped' for child in node.iter()) for node in cases)
    # Suite-level errors are failures too, even if every testcase appears green.
    all_errors = any(local(node.tag) in {'failure', 'error'} for node in root.iter())
    all_skipped = any(local(node.tag) == 'skipped' for node in root.iter())
    if any(node.get('status', '').lower() in {'notrun', 'disabled', 'skipped', 'failed', 'error'} or
           node.get('result', '').lower() in {'suppressed', 'skipped', 'failed', 'error'} for node in cases):
        raise ReportError('JUnit contains non-executed or non-passing testcase attributes')
    errors = any(local(node.tag) == 'error' for node in root.iter())
    if expect_failure:
        assertion_types = {'AssertionError', 'builtins.AssertionError', 'java.lang.AssertionError',
                           'junit.framework.AssertionFailedError', 'org.opentest4j.AssertionFailedError'}
        failures = [node for node in root.iter() if local(node.tag) == 'failure']
        case_failures = [child for case in cases for child in case.iter() if local(child.tag) == 'failure']
        if len(failures) != len(case_failures):
            raise ReportError('Suite-level failures are not assertion evidence')
        for failure in failures:
            kind = failure.get('type', '')
            message = failure.get('message', '')
            # Pytest omits type for assertions, but prefixes its native message
            # with the assertion expression or AssertionError. Unknown runner
            # formats require a trusted adapter; never treat a crash as a kill.
            pytest_assertion = not kind and re.match(r'^(?:assert\s|AssertionError(?:[:\s]|$))', message)
            if kind not in assertion_types and not pytest_assertion:
                raise ReportError('Negative control requires a recognized assertion failure')
    if (not total or skipped or all_skipped or errors or
            (not expect_failure and (failed or all_errors)) or (expect_failure and not failed)):
        raise ReportError(f'JUnit suite is not fully passing: total={total}, failed={failed}, skipped={skipped}')
    # Explicit aggregate failure/skip counts must not contradict testcase data.
    for node in root.iter():
        if local(node.tag) not in {'testsuite', 'testsuites'}:
            continue
        if 'tests' in node.attrib:
            try:
                declared = int(node.attrib['tests'])
            except ValueError as exc:
                raise ReportError('Invalid JUnit tests count') from exc
            actual = sum(local(child.tag) == 'testcase' for child in node.iter())
            if declared != actual:
                raise ReportError('JUnit aggregate test count differs from actual testcase elements')
        for key in ('failures', 'errors', 'skipped', 'disabled'):
            if key in node.attrib:
                try:
                    count = int(node.attrib[key])
                except ValueError as exc:
                    raise ReportError(f'Invalid JUnit {key} count') from exc
                actual_failures = sum(any(local(c.tag) == 'failure' for c in case.iter())
                                      for case in node.iter() if local(case.tag) == 'testcase')
                if count != (actual_failures if expect_failure and key == 'failures' else 0):
                    raise ReportError(f'JUnit aggregate {key} is nonzero')
    tests, seen = [], set()
    def collect(node, suites=()):
        tag = local(node.tag)
        if tag == 'testsuite':
            suites = (*suites, node.get('name', ''))
        if tag == 'testcase':
            name = node.get('name', '')
            if not name.strip():
                raise ReportError('Every testcase needs a nonempty name')
            identity = json.dumps([*suites, node.get('classname', ''), name],
                                  ensure_ascii=True, separators=(',', ':'))
            if identity in seen:
                raise ReportError('Duplicate testcase identity: ' + identity)
            seen.add(identity)
            status = 'failed' if any(local(c.tag) == 'failure' for c in node.iter()) else 'passed'
            tests.append({'id': identity, 'status': status})
        for child in node:
            collect(child, suites)
    collect(root)
    return {'status': 'failed' if failed else 'passed', 'total': total,
            'passed': total - failed, 'failed': failed, 'skipped': 0, 'tests': tests}


def run(report, junit, command, timeout=300, expect_failure=False):
    report = Path(report)
    if not report.is_absolute() or '..' in report.parts:
        raise ReportError('--report must be an absolute path without traversal')
    report = no_symlinks(report)
    junit = native_path(junit)
    if report == junit:
        raise ReportError('Native and normalized report paths must differ')
    if report.exists() or junit.exists():
        raise ReportError('Reports must not pre-exist; use fresh isolated paths')
    if not command or not all(isinstance(arg, str) and arg and '\x00' not in arg for arg in command):
        raise ReportError('A test command argv is required after --')
    if not math.isfinite(timeout) or timeout <= 0:
        raise ReportError('Timeout must be positive')
    report.parent.mkdir(parents=True, exist_ok=True)
    junit.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(command, shell=False, stdin=subprocess.DEVNULL,
                            start_new_session=(os.name == 'posix'))
    try:
        code = proc.wait(timeout=timeout)
    except BaseException:
        if os.name == 'posix':
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            proc.kill()  # Windows descendant isolation requires an external Job Object runner.
        proc.wait()
        raise
    if (expect_failure and code <= 0) or (not expect_failure and code != 0):
        raise ReportError(f'Test command exited {code}; expected ' + ('a test failure' if expect_failure else 'success'))
    evidence = parse_junit(junit, expect_failure=expect_failure)
    no_symlinks(report)
    # Exclusive creation prevents replacing a pre-existing or test-created report.
    with report.open('x', encoding='utf-8') as stream:
        json.dump(evidence, stream, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True)
    parser.add_argument('--junit', required=True)
    parser.add_argument('--mode', choices=('pass', 'fail'), default='pass')
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    run(args.report, args.junit, command, args.timeout, args.mode == 'fail')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'test_report: {exc}', file=sys.stderr)
        sys.exit(2)
