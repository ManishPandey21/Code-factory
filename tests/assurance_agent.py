"""Deterministic assurance fixture; never a provider/model quality evaluation."""
import json
from pathlib import Path
import subprocess
import sys

mode, prompt_path, result_path, event_dir = sys.argv[1:]
prompt = Path(prompt_path).read_text()
ticket = json.JSONDecoder().raw_decode(prompt[prompt.index('{'):])[0]
if mode == 'builder':
    path = Path(ticket['paths'][0]);path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('value = 42\n' + ('# corrected\n' if 'TRUSTED_REPAIR_FINDINGS' in prompt else ''))
    result = {}
else:
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    base = subprocess.check_output(['git', 'rev-parse', 'HEAD^'], text=True).strip()
    if mode == 'risk':
        if 'COLD_TEST_EVIDENCE' in prompt or 'TRUSTED_REPAIR_FINDINGS' in prompt:
            raise RuntimeError('Contaminated independent risk prompt')
        result = {'reviewed_head': head, 'base': base, 'level': 'low', 'rationale': 'Fixture assessment',
                  'covered_files': json.loads(prompt.split('CHANGED_FILES\n')[1]), 'requires_human': False}
        if 'RISK_STALE' in ticket['title']: result['reviewed_head'] = '0' * 40
    else:
        evidence = json.loads(prompt.split('COLD_TEST_EVIDENCE\n')[1])
        fail = ('REPAIR' in ticket['title'] and ('ALWAYS' in ticket['title'] or
                '# corrected' not in Path(ticket['paths'][0]).read_text()))
        result = {'reviewed_head': head, 'base': base, 'verdict': 'CHANGES_REQUIRED' if fail else 'PASS',
                  'findings': [{'file': ticket['paths'][0], 'message': 'Fixture correction required'}] if fail else [],
                  'evidence_digest': evidence['digest'], 'tests_confirmed': True, 'covered_files': evidence['files'],
                  'acceptance_covered': list(range(len(evidence['acceptance'])))}
        result['acceptance_tests'] = [{'acceptance': i, 'tests': [{'check': evidence['checks'][0]['id'],
            'test': evidence['checks'][0]['counts']['tests'][0]['id']}]} for i in range(len(evidence['acceptance']))]
Path(result_path).write_text(json.dumps(result))
