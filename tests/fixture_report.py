"""Synthetic counts ONLY for orchestration tests; not a real project adapter."""
import json, sys
from pathlib import Path
assert Path('README.md').is_file()
Path(sys.argv[1]).write_text(json.dumps({'status':'passed','total':1,'passed':1,'failed':0,'skipped':0}), encoding='utf-8')
