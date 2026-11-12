"""Protect check runners while allowing declared negative-control destinations."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from check_paths import referenced_paths
from evidence import negative_control
from runtime import FactoryError, git


class MutationInputTests(unittest.TestCase):
    def test_bundled_policy_does_not_protect_mutation_destination(self):
        root=Path(__file__).resolve().parents[1]
        policy=json.loads((root/'examples/verification-policy.json').read_text(encoding='utf-8'))
        self.assertEqual(referenced_paths({'verification':policy},root,{'backend/service.py'}),set())

    def test_direct_and_interpreted_mutators_protect_scripts_not_destinations(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve()
            for argv in [['ci/mutate', '{worktree}', '{worktree}/backend/service.py'],
                         ['python', 'ci/mutate.py', '{worktree}', 'backend/service.py'],
                         ['python3.12', '-I', '-W', 'ignore', 'ci/mutate.py', 'backend/service.py']]:
                config={'verification':{'checks':[{'argv':['python','ci/check.py'], 'negative_control':{'argv':argv}}]}}
                refs=referenced_paths(config,root,{'ci/mutate','ci/mutate.py','ci/check.py','backend/service.py'})
                self.assertIn('ci/check.py',refs)
                self.assertIn('ci/mutate' if argv[0]=='ci/mutate' else 'ci/mutate.py',refs)
                self.assertNotIn('.',refs);self.assertNotIn('backend/service.py',refs)

    def test_negative_control_cannot_modify_a_configured_check_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();source=root/'repo';source.mkdir()
            git(source,'init','-q','-b','main');git(source,'config','user.name','Fixture')
            git(source,'config','user.email','fixture@example.invalid')
            (source/'ci').mkdir();(source/'ci/check.py').write_text('pass\n',encoding='utf-8')
            git(source,'add','.');git(source,'commit','-qm','base');head=git(source,'rev-parse','HEAD')
            logs=root/'logs';logs.mkdir()
            check={'id':'unit','argv':[sys.executable,'ci/check.py','{test_mode}'],
                   'negative_control':{'argv':[sys.executable,'-c',
                       "from pathlib import Path; Path('ci/check.py').write_text('raise RuntimeError()\\n',encoding='utf-8')"],
                                       'expected_failures':['behavior']}}
            config={'checks':[],'verification':{'checks':[check]},'timeout_seconds':10}
            with self.assertRaisesRegex(FactoryError,'configured check input'):
                negative_control(source,logs,config,head,head,check,{}, {})
