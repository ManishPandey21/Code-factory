import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
class FactoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.home=Path(self.tmp.name)
        self.repo=self.home/'repo';self.repo.mkdir()
        self.events=self.home/'events';self.events.mkdir()
        self.skill=self.home/'fixture-skill.md';self.skill.write_text('Fixture: implement only assigned file.')
        self.git('init','-q','-b','main')
        self.git('config','user.name','Factory Test');self.git('config','user.email','test@example.invalid')
        (self.repo/'README.md').write_text('Fixture repo\n');self.commit()
        self.cli('init','--apply')
        self.cfg=self.repo/'.infra-factory/config.json'
        c=json.loads(self.cfg.read_text())
        def spec(mode):
            return {'argv':[sys.executable,str(ROOT/'tests/fake_agent.py'),mode,'{prompt_file}','{result_file}',str(self.events)],'stdin_prompt':False,'model':'fixture','primary_skill':str(self.skill)}
        c['commands']={k:spec('reviewer' if k=='reviewer' else 'builder') for k in ['backend','frontend','critical','reviewer']}
        c['checks']=[[sys.executable,'-c','import pathlib; assert pathlib.Path("README.md").exists()']]
        kinds = {'frontend': ['unit','component','visual','e2e'], 'backend': ['unit','api','integration'], 'shared': ['contract']}
        c['verification'] = {'path_domains': {'frontend':['frontend'], 'backend':['backend'], 'shared':['shared']}, 'required': {}, 'checks': [
            {'id':d+'-'+k,'domains':[d],'kind':k,'argv':[sys.executable,str(ROOT/'tests/fixture_report.py'),'{report}'],'report':d+'-'+k+'.json','min_tests':1}
            for d, ks in kinds.items() for k in ks]}
        c['timeout_seconds']=10
        self.cfg.write_text(json.dumps(c));self.commit()
    def tearDown(self): self.tmp.cleanup()
    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.repo),*args],stderr=subprocess.PIPE,text=True).strip()
    def commit(self): self.git('add','.');self.git('commit','-qm','fixture')
    def cli(self,action,*args,code=0):
        p=subprocess.run([sys.executable,str(ROOT/'factory.py'),action,'--repo',str(self.repo),*args],capture_output=True,text=True)
        self.assertEqual(p.returncode,code,p.stdout+p.stderr)
        return p
    def add(self,id,paths=None,depends=None,title='Implement fixture',code=0):
        t={'id':id,'title':title,'description':'Create declared file','acceptance':['File contains value 42'],'paths':paths or [id+'.py'],'depends_on':depends or [],'role':'backend'}
        t['spec'] = {key: {'impact':'Fixture scope', 'acceptance':['Fixture contract holds']} for key in ('ui','api','data','cross_cutting')}
        f=self.home/(id+'.json');f.write_text(json.dumps(t));self.cli('add','--ticket',str(f),code=code)
    def states(self):
        return {r['id']:r for r in json.loads(self.cli('status').stdout)['tickets']}
    def test_two_tickets_actually_overlap(self):
        self.add('A');self.add('B');self.cli('run','--execute')
        rows=self.states();self.assertEqual({r['state'] for r in rows.values()},{'READY'})
        self.assertNotEqual(rows['A']['worktree'],rows['B']['worktree'])
        events=[json.loads(p.read_text()) for p in self.events.glob('*builder*.json')]
        self.assertEqual(len(events),2)
        self.assertLess(max(e['start'] for e in events),min(e['end'] for e in events))
        reviews=list(self.events.glob('*reviewer*.json'));self.assertEqual(len(reviews),4)
        self.assertFalse((self.repo/'A.py').exists())
    def test_builder_only_ignored_artifact_cannot_verify(self):
        (self.repo/'.gitignore').write_text('verification-ready.flag\n');self.commit()
        c=json.loads(self.cfg.read_text())
        c['checks']=[[sys.executable,'-c','from pathlib import Path; assert Path("verification-ready.flag").exists()']]
        self.cfg.write_text(json.dumps(c));self.commit()
        self.add('A',title='CONTAMINATE');self.cli('run','--execute',code=1)
        self.assertEqual(self.states()['A']['state'],'BLOCKED')
        self.assertFalse(list(self.events.glob('*reviewer*.json')))
    def test_review_requires_evidence_files_and_all_acceptance(self):
        for title in ('NO_EVIDENCE','NO_FILE','NO_ACCEPTANCE'):
            self.add(title,title=title);self.cli('run','--execute',code=1)
            self.assertEqual(self.states()[title]['state'],'BLOCKED')
    def test_tampered_evidence_revokes_publish(self):
        self.add('A');self.cli('run','--execute');row=self.states()['A']
        artifact=next(iter(row['review_json']['lenses']['spec']['evidence']['artifacts']))
        Path(artifact).write_text('tampered')
        self.assertFalse(self.states()['A']['verification_current'])
        self.cli('publish','--ticket','A','--execute',code=2)
        self.assertEqual(self.states()['A']['state'],'BLOCKED')
    def test_missing_report_blocks(self):
        c=json.loads(self.cfg.read_text());c['verification']['checks'][0]['argv']=[sys.executable,'-c','pass']
        self.cfg.write_text(json.dumps(c));self.commit()
        self.add('A');self.cli('run','--execute',code=1)
        self.assertEqual(self.states()['A']['state'],'BLOCKED')
    def test_existing_test_modification_blocked(self):
        (self.repo/'test_existing.py').write_text('value = 1\n');self.commit()
        self.add('A',paths=['test_existing.py']);self.cli('run','--execute',code=1)
        self.assertIn('Verification-sensitive',self.states()['A']['error'])
    def test_reject_retains_work_and_base(self):
        self.add('A');base=self.git('rev-parse','HEAD');self.cli('run','--execute')
        work=Path(self.states()['A']['worktree']);self.cli('reject','--ticket','A')
        self.assertEqual(self.git('rev-parse','HEAD'),base)
        self.assertTrue(work.exists());self.assertEqual(self.states()['A']['state'],'REJECTED')
        self.cli('publish','--ticket','A',code=2)
    def test_reject_merged_candidate_refused(self):
        self.add('A');self.cli('run','--execute');self.git('merge','--ff-only',self.states()['A']['head_sha'])
        self.cli('reject','--ticket','A',code=2)
    def test_config_change_during_build_blocks(self):
        # A trusted fixture deliberately mutates controller config during builder invocation.
        script=self.home/'mutate.py'
        script.write_text('from pathlib import Path\nimport json\np=Path('+repr(str(self.cfg))+')\nc=json.loads(p.read_text());c["timeout_seconds"]=123;p.write_text(json.dumps(c))\nPath("A.py").write_text("value=42")\n')
        c=json.loads(self.cfg.read_text());c['commands']['backend']['argv']=[sys.executable,str(script)]
        self.cfg.write_text(json.dumps(c));self.commit();self.add('A');self.cli('run','--execute',code=1)
        self.assertEqual(self.states()['A']['state'],'BLOCKED')

    def test_optimized_python_stale_status_is_false(self):
        self.add('A');self.cli('run','--execute')
        (Path(self.states()['A']['worktree'])/'A.py').write_text('tampered')
        p=subprocess.run([sys.executable,'-O',str(ROOT/'factory.py'),'status','--repo',str(self.repo)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertFalse(json.loads(p.stdout)['tickets'][0]['verification_current'])
    def test_external_tool_mutation_revokes_evidence(self):
        tool=self.home/'report.py';tool.write_bytes((ROOT/'tests/fixture_report.py').read_bytes())
        c=json.loads(self.cfg.read_text())
        for check in c['verification']['checks']: check['argv'][1]=str(tool)
        self.cfg.write_text(json.dumps(c));self.commit()
        self.add('A');self.cli('run','--execute');tool.write_text(tool.read_text()+'\n# changed\n')
        self.cli('publish','--ticket','A','--execute',code=2)
        self.assertEqual(self.states()['A']['state'],'BLOCKED')
    def test_examples_validate(self):
        for sample in (ROOT/'examples').glob('DEMO-*.json'):
            self.cli('add','--ticket',str(sample))

    def test_overlap_is_serialized(self):
        self.add('A',['shared']);self.add('B',['shared/module.py'])
        p=self.cli('run');self.assertEqual(json.loads(p.stdout)['selected'],['A'])
    def test_dependency_waits_for_merge(self):
        self.add('A');self.add('B',depends=['A'])
        self.cli('run','--execute');self.assertEqual(self.states()['B']['state'],'PENDING')
        row=self.states()['A'];self.git('merge','--ff-only',row['head_sha'])
        self.cli('run','--execute');self.assertEqual(self.states()['B']['state'],'READY')
    def test_missing_checks(self):
        self.add('A');c=json.loads(self.cfg.read_text());c['checks']=[];self.cfg.write_text(json.dumps(c));self.commit()
        self.cli('run','--execute',code=2);self.assertEqual(self.states()['A']['state'],'PENDING')
    def test_missing_skill(self):
        self.add('A');self.skill.unlink();self.cli('run','--execute',code=2)
    def test_failed_check(self):
        self.add('A');c=json.loads(self.cfg.read_text());c['checks']=[[sys.executable,'-c','raise SystemExit(4)']];self.cfg.write_text(json.dumps(c));self.commit()
        self.cli('run','--execute',code=1);self.assertEqual(self.states()['A']['state'],'BLOCKED')
    def test_stale_review_rejected(self):
        self.add('A',title='STALE');self.cli('run','--execute',code=1);self.assertEqual(self.states()['A']['state'],'BLOCKED')
    def test_reviewer_mutation_rejected(self):
        self.add('A',title='MUTATE');self.cli('run','--execute',code=1)
    def test_review_changes_required(self):
        self.add('A',title='REJECT');self.cli('run','--execute',code=1)
    def test_outside_scope_rejected(self):
        self.add('A',title='OUTSIDE');self.cli('run','--execute',code=1)
    def test_dirty_base(self):
        self.add('A');(self.repo/'dirty').write_text('x');self.cli('run','--execute',code=2)
    def test_protected_ticket(self): self.add('A',['.github/workflows/x.yml'],code=2)
    def test_unknown_dependency(self): self.add('A',depends=['UNKNOWN'],code=2)
    def test_duplicate_ticket(self): self.add('A');self.add('A',code=2)
    def test_live_lock_refused(self):
        self.add('A');p=self.repo/'.git/infra-factory/coordinator.lock';p.write_text('{}');self.cli('run','--execute',code=2)
    def test_init_preserves_existing(self):
        before=self.cfg.read_bytes();self.cli('init','--apply');self.assertEqual(before,self.cfg.read_bytes())
    def test_timeout_blocks(self):
        self.add('A');c=json.loads(self.cfg.read_text());c['timeout_seconds']=.05;self.cfg.write_text(json.dumps(c));self.commit();self.cli('run','--execute',code=1)

    def test_dot_path_overlap_is_serialized(self):
        self.add('A',['./shared']);self.add('B',['./shared/module.py'])
        self.assertEqual(json.loads(self.cli('run').stdout)['selected'],['A'])
    def test_rewound_dependency_does_not_unlock(self):
        initial=self.git('rev-parse','HEAD')
        self.add('A');self.add('B',depends=['A']);self.cli('run','--execute')
        self.git('merge','--ff-only',self.states()['A']['head_sha']);self.cli('run','--execute')
        self.add('C',depends=['A'])
        # Rewind only this throwaway fixture to exercise a changed dispatch base.
        self.git('reset','--hard',initial)
        self.assertEqual(json.loads(self.cli('run').stdout)['selected'],[])
    def test_publish_dry_run(self):
        self.add('A');self.cli('run','--execute')
        result=json.loads(self.cli('publish','--ticket','A').stdout)
        self.assertTrue(result['draft']);self.assertTrue(result['dry_run'])
    def test_publish_changed_config_blocks(self):
        self.add('A');self.cli('run','--execute')
        c=json.loads(self.cfg.read_text());c['timeout_seconds']=20;self.cfg.write_text(json.dumps(c))
        self.cli('publish','--ticket','A',code=2)
    def test_publish_dirty_candidate_blocks(self):
        self.add('A');self.cli('run','--execute')
        wt=Path(self.states()['A']['worktree']);(wt/'A.py').write_text('changed')
        self.cli('publish','--ticket','A',code=2)
    def test_publish_remote_base_mismatch(self):
        self.add('A');self.cli('run','--execute')
        bare=self.home/'remote.git'
        subprocess.check_call(['git','init','-q','--bare',str(bare)])
        self.git('remote','add','origin',str(bare));self.git('push','origin','main')
        # Advance remote main with a real candidate without changing local main.
        self.git('push','origin',self.states()['A']['head_sha']+':refs/heads/main')
        self.cli('publish','--ticket','A','--execute',code=2)

    def test_retry_is_bounded_and_retains_work(self):
        self.add('A',title='REJECT')
        retained=[]
        for attempt in range(1,4):
            self.cli('run','--execute',code=1)
            row=self.states()['A'];self.assertEqual(row['attempts'],attempt);retained.append(row['worktree'])
            self.cli('retry','--ticket','A',code=0 if attempt<3 else 2)
        self.assertEqual(len(set(retained)),3)
        self.assertTrue(all(Path(p).exists() for p in retained))
    def test_retry_pending_refused(self):
        self.add('A');self.cli('retry','--ticket','A',code=2)
    @unittest.skipUnless(os.name=='posix','Executable gh fixture uses POSIX shebang')
    def test_draft_publish_and_reuse_with_fake_github(self):
        self.add('A');self.cli('run','--execute')
        bare=self.home/'remote.git'
        subprocess.check_call(['git','init','-q','--bare',str(bare)])
        self.git('remote','add','origin',str(bare));self.git('push','origin','main')
        binpath=self.home/'bin';binpath.mkdir();gh=binpath/'gh'
        gh.write_text('#!'+sys.executable+'\n'+'''import json,sys,subprocess
from pathlib import Path
state=Path('.git/fake-gh.json')
if sys.argv[1:3]==['pr','list']:
    print(state.read_text() if state.exists() else '[]')
elif sys.argv[1:3]==['pr','create']:
    assert '--draft' in sys.argv
    assert not state.exists(), 'Duplicate PR creation'
    branch=sys.argv[sys.argv.index('--head')+1]
    head=subprocess.check_output(['git','rev-parse',branch],text=True).strip()
    state.write_text(json.dumps([{'url':'https://example.invalid/pull/1','isDraft':True,'headRefOid':head}]))
    print('https://example.invalid/pull/1')
else:
    raise SystemExit(7)
''');gh.chmod(0o755)
        with patch.dict(os.environ,{'PATH':str(binpath)+os.pathsep+os.environ['PATH']}):
            self.cli('publish','--ticket','A','--execute')
            self.cli('publish','--ticket','A','--execute')
        self.assertEqual(self.states()['A']['pr_url'],'https://example.invalid/pull/1')

if __name__=='__main__': unittest.main()
