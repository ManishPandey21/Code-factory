"""Deterministic behavior probe for orchestration tests, not application coverage."""
import json
import sys
from pathlib import Path
try:
    assert Path('README.md').is_file()
    assert Path('README.md').read_text(encoding='utf-8') != 'BROKEN'
    failed = 0
except AssertionError:
    failed = 1
Path(sys.argv[1]).write_text(json.dumps({
    'status': 'failed' if failed else 'passed', 'total': 1, 'passed': 1 - failed,
    'failed': failed, 'skipped': 0,
    'tests': [{'id': 'fixture.readme', 'status': 'failed' if failed else 'passed'}]}), encoding='utf-8')
