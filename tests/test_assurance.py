import argparse
import contextlib
import io
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import factory
from test_factory import FactoryTests, ROOT
import review_policy
import repair

POLICY = {'specialists': {'security': {'paths': ['A.py'], 'focus': 'Security boundaries'}},
          'risk': {'minimum_level': 'low', 'human_review_levels': ['high', 'critical'],
                   'path_levels': [{'paths': ['A.py'], 'level': 'high'}]}}

class AssuranceTests(unittest.TestCase):
    setUp = FactoryTests.setUp
    tearDown = FactoryTests.tearDown
    git = FactoryTests.git
    commit = FactoryTests.commit
    cli = FactoryTests.cli
    add = FactoryTests.add
    states = FactoryTests.states

    def configure(self, risk=True, github=False):
        c = json.loads(self.cfg.read_text())
        c['review_policy'] = copy.deepcopy(POLICY)
        if not risk: c['review_policy'].pop('risk')
        c['repair_policy'] = {'max_repairs': 2}
        if github: c['repair_policy']['github'] = {'repository': 'owner/repo', 'workflow_ids': [8]}
        def spec(mode):
            return {'argv': [sys.executable, str(ROOT/'tests/assurance_agent.py'), mode, '{prompt_file}',
                             '{result_file}', str(self.events)], 'stdin_prompt': False, 'model': 'fixture', 'primary_skill': str(self.skill)}
        c['commands'] = {k: spec('reviewer' if k.startswith('reviewer') else 'risk' if k == 'risk_assessor' else 'builder')
                         for k in ['backend','frontend','critical','reviewer','reviewer_security','risk_assessor']}
        self.cfg.write_text(json.dumps(c));self.commit()

    def approve(self, row, head=None, digest=None, code=0):
        return self.cli('approve', '--ticket', row['id'], '--head', head or row['head_sha'],
                        '--risk-digest', digest or row['review_json']['risk']['digest'],
                        '--reviewer', 'Human operator', '--note', 'Reviewed candidate and rollback', code=code)

    def test_specialist_and_independent_risk_require_exact_approval(self):
        self.configure();self.add('A');self.cli('run', '--execute')
        row = self.states()['A']
        self.assertEqual(row['state'], 'AWAITING_HUMAN')
        self.assertEqual(set(row['review_json']['lenses']), {'standards','spec','security'})
        self.assertEqual(row['review_json']['risk']['level'], 'high')
        self.assertTrue(row['verification_current'])
        self.cli('publish', '--ticket', 'A', code=2)
        self.approve(row, head='0'*40, code=2);self.approve(row, digest='bad', code=2)
        self.approve(row);self.cli('publish', '--ticket', 'A')
        self.assertEqual(self.states()['A']['state'], 'READY')
        artifact = Path(row['review_json']['risk']['artifact']['file'])
        artifact.write_text('{}')
        self.assertFalse(self.states()['A']['verification_current'])
        self.cli('publish', '--ticket', 'A', code=2)

    def test_nonmatching_diff_does_not_run_specialist(self):
        self.configure();self.add('B');self.cli('run', '--execute')
        row = self.states()['B']
        self.assertEqual(row['state'], 'READY')
        self.assertEqual(set(row['review_json']['lenses']), {'standards','spec'})
        self.assertFalse(row['review_json']['risk']['requires_human'])

    def test_hold_prevents_approval_and_repair_and_reserves_paths(self):
        self.configure();self.add('A');self.cli('run', '--execute');row=self.states()['A']
        self.cli('hold','--ticket','A','--hold-version','0','--reason','Inspect')
        self.approve(row, code=2)
        self.cli('repair','--ticket','A','--head',row['head_sha'],'--source','review','--execute',code=2)
        self.add('B', paths=['A.py'])
        preview=json.loads(self.cli('run').stdout)
        self.assertEqual(preview['selected'], [])
        self.cli('release','--ticket','A','--hold-version','1','--reason','Inspected')
        self.approve(row)

    def test_repair_rechecks_candidate_and_returns_to_human_gate(self):
        self.configure();self.add('A', title='REPAIR');self.cli('run','--execute',code=1)
        old=self.states()['A'];self.assertEqual(old['state'],'BLOCKED')
        args=['--ticket','A','--head',old['head_sha'],'--source','review']
        self.cli('repair',*args);self.assertEqual(self.states()['A']['attempts'],1)
        self.cli('repair',*args,'--execute')
        new=self.states()['A'];self.assertEqual(new['attempts'],2)
        self.assertEqual(new['state'],'AWAITING_HUMAN');self.assertNotEqual(new['head_sha'],old['head_sha'])
        self.approve(new,head=old['head_sha'],code=2)
        self.cli('repair',*args,'--execute',code=2)
        self.approve(new);self.cli('publish','--ticket','A')

    def test_repair_budget_cannot_reset(self):
        self.configure(risk=False);self.add('A',title='REPAIR ALWAYS');self.cli('run','--execute',code=1)
        for attempt in (2,3):
            row=self.states()['A']
            self.cli('repair','--ticket','A','--head',row['head_sha'],'--source','review','--execute',code=1)
            self.assertEqual(self.states()['A']['attempts'],attempt)
        row=self.states()['A']
        self.cli('repair','--ticket','A','--head',row['head_sha'],'--source','review','--execute',code=2)

    def test_stricter_budget_blocks_retry_and_inherited_dispatch(self):
        self.configure(risk=False)
        c=json.loads(self.cfg.read_text());c['repair_policy']['max_repairs']=1
        self.cfg.write_text(json.dumps(c));self.commit()
        self.add('A',title='REPAIR ALWAYS');self.cli('run','--execute',code=1)
        row=self.states()['A']
        self.cli('repair','--ticket','A','--head',row['head_sha'],'--source','review','--execute',code=1)
        self.cli('retry','--ticket','A',code=2)
        ticket=json.loads((self.home/'A.json').read_text());ticket.update(id='B',supersedes=['A'])
        replacement=self.home/'B.json';replacement.write_text(json.dumps(ticket))
        self.cli('add','--ticket',str(replacement));self.cli('run','--execute',code=2)
        self.assertEqual(self.states()['B']['attempts'],2)

    def test_historical_hold_on_merged_predecessor_does_not_block_repair(self):
        self.configure(risk=False);self.add('A');self.cli('run','--execute')
        row=self.states()['A'];self.cli('hold','--ticket','A','--hold-version','0','--reason','Inspect')
        self.git('merge','--ff-only',row['head_sha']);self.cli('run','--execute')
        self.assertEqual(self.states()['A']['state'],'MERGED')
        (self.repo/'A.py').write_text('value = 41\n');self.commit()
        self.add('B',paths=['A.py'],title='REPAIR');self.cli('run','--execute',code=1)
        row=self.states()['B']
        self.cli('repair','--ticket','B','--head',row['head_sha'],'--source','review','--execute')
        self.assertEqual(self.states()['B']['state'],'READY')

    def test_modified_review_artifact_cannot_feed_repair(self):
        self.configure(risk=False);self.add('A',title='REPAIR');self.cli('run','--execute',code=1)
        row=self.states()['A'];Path(row['review_json']['lenses']['spec']['artifact']['file']).write_text('{}')
        self.cli('repair','--ticket','A','--head',row['head_sha'],'--source','review','--execute',code=2)
        self.assertEqual(self.states()['A']['attempts'],1)

    def test_repair_claim_and_attempt_transition_roll_back_together(self):
        self.configure(risk=False);self.add('A',title='REPAIR');self.cli('run','--execute',code=1)
        row=self.states()['A'];repo,home=factory.locations(self.repo);c=factory.config(repo)
        args=argparse.Namespace(ticket='A',head=row['head_sha'],source='review',run_id=None,execute=True)
        original=factory.record
        def fail_transition(con,tid,state,details):
            if state == 'RUNNING' and details.get('action') != 'repair':
                raise RuntimeError('Simulated interruption before transaction commit')
            return original(con,tid,state,details)
        with factory.lock(home), contextlib.redirect_stdout(io.StringIO()), patch('records.record',side_effect=fail_transition):
            self.assertEqual(repair.repair_candidate(factory,repo,home,c,args),1)
        with factory.connect(home) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM repair_requests').fetchone()[0],0)
        self.assertEqual(self.states()['A']['attempts'],1)
        self.cli('repair','--ticket','A','--head',row['head_sha'],'--source','review','--execute')
        self.assertEqual(self.states()['A']['attempts'],2)

    def test_github_repair_invalidates_prior_human_approval(self):
        self.configure(github=True);self.add('A');self.cli('run','--execute')
        old=self.states()['A'];self.approve(old)
        repo,home=factory.locations(self.repo);c=factory.config(repo)
        source=GitHubTrustTests();source.setUp()
        head=old['head_sha'];source.run['head_sha']=head;source.jobs['jobs'][0]['head_sha']=head
        original=repair.github_findings
        args=argparse.Namespace(ticket='A',head=head,source='github',run_id=42,execute=True)
        with factory.lock(home), contextlib.redirect_stdout(io.StringIO()), patch('repair.github_findings',
                side_effect=lambda policy,run,head:original(policy,run,head,source.fetch)):
            self.assertEqual(repair.repair_candidate(factory,repo,home,c,args),0)
        new=self.states()['A'];self.assertEqual(new['state'],'AWAITING_HUMAN')
        self.assertNotIn('human_approval',new['review_json']);self.assertEqual(new['attempts'],2)
        self.assertNotEqual(new['head_sha'],head)
        with factory.connect(home) as con:
            events=[json.loads(r[0]) for r in con.execute('SELECT details FROM events')]
        receipt=next(e for e in events if e.get('action')=='repair')
        self.assertEqual(factory.sha_file(receipt['receipt']),receipt['sha256'])

    def test_stale_risk_assessment_blocks(self):
        self.configure();self.add('A',title='RISK_STALE');self.cli('run','--execute',code=1)
        self.assertEqual(self.states()['A']['state'],'BLOCKED')

    def test_missing_specialist_command_fails_before_dispatch(self):
        self.configure();self.add('A')
        c=json.loads(self.cfg.read_text());del c['commands']['reviewer_security']
        self.cfg.write_text(json.dumps(c));self.commit()
        self.cli('run','--execute',code=2)
        self.assertEqual(self.states()['A']['attempts'],0)

del FactoryTests

class PolicyTests(unittest.TestCase):
    def test_threshold_is_monotonic(self):
        p=copy.deepcopy(POLICY);p['risk']['human_review_levels']=['high']
        with self.assertRaises(ValueError):review_policy.validate(p)

    def test_critical_ticket_overrides_low_assessment(self):
        a={'reviewed_head':'h','base':'b','level':'low','rationale':'reason','covered_files':['B.py']}
        risk=review_policy.assess(POLICY,a,['B.py'],'h','b',True)
        self.assertEqual(risk['level'],'critical');self.assertTrue(risk['requires_human'])

class GitHubTrustTests(unittest.TestCase):
    def setUp(self):
        self.policy={'repository':'owner/repo','workflow_ids':[8]}
        self.run={'id':42,'head_sha':'abc','workflow_id':8,'repository':{'full_name':'owner/repo'},
                  'head_repository':{'full_name':'owner/repo'},'event':'push','status':'completed',
                  'conclusion':'failure','run_attempt':1,'updated_at':'now'}
        self.jobs={'jobs':[{'head_sha':'abc','run_id':42,'run_attempt':1,'status':'completed','conclusion':'failure',
                            'name':'Tests','steps':[{'name':'Unit test','conclusion':'failure'}]}]}
    def fetch(self,path):return copy.deepcopy(self.jobs if '/jobs?' in path else self.run)
    def test_allowed_run_collects_failed_steps(self):
        evidence,raw=repair.github_findings(self.policy,42,'abc',self.fetch)
        self.assertEqual(evidence['findings'][0]['steps'],['Unit test']);self.assertIn('pages',raw)
    def test_spoofed_fork_workflow_head_and_unsafe_event_rejected(self):
        for key,value in [('head_sha','stale'),('workflow_id',9),('head_repository',{'full_name':'fork/repo'}),
                          ('repository',{'full_name':'other/repo'}),('event','pull_request_target'),('status','in_progress')]:
            with self.subTest(key=key),patch.dict(self.run,{key:value}):
                with self.assertRaises(ValueError):repair.github_findings(self.policy,42,'abc',self.fetch)
    def test_job_and_rerun_races_rejected(self):
        self.jobs['jobs'][0]['head_sha']='wrong'
        with self.assertRaises(ValueError):repair.github_findings(self.policy,42,'abc',self.fetch)
        self.jobs['jobs'][0]['head_sha']='abc'
        calls=0
        def race(path):
            nonlocal calls
            calls+=1
            if calls==3:self.run['run_attempt']=2
            return self.fetch(path)
        with self.assertRaises(ValueError):repair.github_findings(self.policy,42,'abc',race)
