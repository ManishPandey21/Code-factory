"""Deterministic subprocess fixture. Never presented as an AI model run."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

mode, prompt_path, result_path, event_dir = sys.argv[1:]
prompt = Path(prompt_path).read_text(encoding='utf-8')
ticket = json.JSONDecoder().raw_decode(prompt[prompt.index('{'):])[0]
tid = ticket['id']
events = Path(event_dir)
start = time.time()
if mode == 'builder':
    time.sleep(.35)
    (Path.cwd()/ticket['paths'][0]).write_text('value = 42\n', encoding='utf-8')
    if 'CONTAMINATE' in ticket['title']:
        Path('verification-ready.flag').write_text('only builder', encoding='utf-8')
    if 'OUTSIDE' in ticket['title']:
        Path('outside.txt').write_text('bad', encoding='utf-8')
    Path(result_path).write_text('{}', encoding='utf-8')
else:
    head = subprocess.check_output(['git','rev-parse','HEAD'], text=True, encoding='utf-8').strip()
    base = subprocess.check_output(['git','rev-parse','HEAD^'], text=True, encoding='utf-8').strip()
    if 'STALE' in ticket['title']:
        head = '0'*40
    verdict = 'CHANGES_REQUIRED' if 'REJECT' in ticket['title'] else 'PASS'
    if 'MUTATE' in ticket['title']:
        Path('reviewer-edit.txt').write_text('bad', encoding='utf-8')
    evidence = json.loads(prompt.split('COLD_TEST_EVIDENCE\n',1)[1])
    result = {'verdict':verdict,'reviewed_head':head,'base':base,'findings':[], 'evidence_digest':evidence['digest'],
              'tests_confirmed':True,'covered_files':evidence['files'],'acceptance_covered':list(range(len(evidence['acceptance'])))}
    result['acceptance_tests'] = [{'acceptance': i, 'tests': [{'check': evidence['checks'][0]['id'],
        'test': evidence['checks'][0]['counts']['tests'][0]['id']}]} for i in range(len(evidence['acceptance']))]
    if 'NO_EVIDENCE' in ticket['title']: result.pop('evidence_digest')
    if 'NO_FILE' in ticket['title']: result['covered_files']=[]
    if 'NO_ACCEPTANCE' in ticket['title']: result['acceptance_covered']=[]
    Path(result_path).write_text(json.dumps(result), encoding='utf-8')
end = time.time()
(events/(tid+'-'+mode+'-'+str(os.getpid())+'.json')).write_text(json.dumps({'ticket':tid,'mode':mode,'start':start,'end':end,'cwd':str(Path.cwd())}), encoding='utf-8')
