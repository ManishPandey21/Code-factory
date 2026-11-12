"""Audit M2/L1-L4 regressions; real Git and deterministic subprocess fixtures."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import factory
from check_paths import referenced_paths
from test_factory import FactoryTests


class CheckPathTests(unittest.TestCase):
    setUp = FactoryTests.setUp
    tearDown = FactoryTests.tearDown
    git = FactoryTests.git
    commit = FactoryTests.commit
    cli = FactoryTests.cli
    add = FactoryTests.add
    states = FactoryTests.states

    def test_wrapper_change_blocked_before_cold_checks(self):
        wrapper = self.repo / 'scripts' / 'runner.py'; wrapper.parent.mkdir()
        wrapper.write_text('raise SystemExit("Real verification would fail")\n', encoding='utf-8')
        c = json.loads(self.cfg.read_text(encoding='utf-8'))
        c['checks'] = [[sys.executable, 'scripts/runner.py']]
        self.cfg.write_text(json.dumps(c), encoding='utf-8'); self.commit()
        self.add('A', paths=['scripts/runner.py']); self.cli('run', '--execute', code=1)
        row = self.states()['A']
        self.assertIn('Configured check input', row['error'])
        self.assertFalse(list(self.events.glob('*reviewer*.json')))

    def test_all_check_sources_spellings_and_deleted_wrapper(self):
        (self.repo/'scripts').mkdir(); wrapper=self.repo/'scripts'/'runner.py'
        wrapper.write_text('pass\n', encoding='utf-8'); self.commit(); base=self.git('rev-parse','HEAD')
        wrapper.unlink(); self.commit(); head=self.git('rev-parse','HEAD')
        for argument in ['scripts/runner.py', './scripts/runner.py', '{worktree}/scripts/runner.py',
                         str(wrapper), '--runner=scripts/runner.py', 'scripts/runner.py::node']:
            for field in ('checks','verification'):
                c={'checks':[], 'verification':{'checks':[]}}
                if field=='checks': c['checks']=[[sys.executable,argument]]
                else: c['verification']['checks']=[{'argv':[sys.executable,argument]}]
                with self.subTest(argument=argument,field=field), self.assertRaisesRegex(factory.FactoryError,'Configured check input'):
                    factory.guard_verification_inputs(self.repo,{},base,head,c)

    def test_absolute_wrapper_through_root_alias_remains_protected_after_deletion(self):
        (self.repo/'scripts').mkdir(); wrapper=self.repo/'scripts'/'runner.py'
        wrapper.write_text('pass',encoding='utf-8');self.commit();base=self.git('rev-parse','HEAD')
        alias=self.home/'alias';alias.symlink_to(self.repo,target_is_directory=True)
        argv=['python',str(alias/'scripts'/'runner.py')]
        wrapper.unlink();self.commit();head=self.git('rev-parse','HEAD')
        for c in [{'checks':[argv]}, {'verification':{'checks':[{'argv':argv}]}}]:
            with self.subTest(config=c), self.assertRaisesRegex(factory.FactoryError,'Configured check input'):
                factory.guard_verification_inputs(self.repo,{},base,head,c)

    def test_directory_reference_protects_descendants_and_both_rename_sides(self):
        (self.repo/'ci').mkdir(); (self.repo/'ci'/'wrapper.py').write_text('pass',encoding='utf-8')
        self.commit(); base=self.git('rev-parse','HEAD')
        self.git('mv','ci/wrapper.py','moved.py'); self.commit(); head=self.git('rev-parse','HEAD')
        with self.assertRaisesRegex(factory.FactoryError,'Configured check input'):
            factory.guard_verification_inputs(self.repo,{},base,head,{'checks':[['tool','ci']]})

    def test_absolute_source_path_maps_to_worktree_and_unrelated_code_is_allowed(self):
        original=self.repo/'scripts'/'runner.py'
        refs=referenced_paths({'checks':[['python',str(original),'--out={report}']]},
                              self.home/'worktree', {'scripts/runner.py','src/app.py'}, self.repo)
        self.assertEqual(refs,{'scripts/runner.py'})
        (self.repo/'app.py').write_text('value=1',encoding='utf-8'); self.commit(); base=self.git('rev-parse','HEAD')
        (self.repo/'app.py').write_text('value=2',encoding='utf-8'); self.commit(); head=self.git('rev-parse','HEAD')
        factory.guard_verification_inputs(self.repo,{},base,head,{'checks':[['python','-c','pass']]})


del FactoryTests


class GitVersionTests(unittest.TestCase):
    def test_vendor_versions_and_minimum(self):
        from unittest.mock import patch
        import subprocess
        from runtime_requirements import require_git_version
        for output in ['git version 2.29.0', 'git version 2.29.0.windows.1',
                       'git version 2.39.3 (Apple Git-145)', 'git version 3.0.0']:
            with self.subTest(output=output), patch('runtime_requirements.subprocess.run',
                    return_value=subprocess.CompletedProcess([],0,output,'')):
                self.assertGreaterEqual(require_git_version(),(2,29))
        for output in ['git version 2.28.9','git version 1.99.0','garbled','git version 2.29garbled']:
            with self.subTest(output=output), patch('runtime_requirements.subprocess.run',
                    return_value=subprocess.CompletedProcess([],0,output,'')):
                with self.assertRaisesRegex(ValueError,'Git >= 2.29'):require_git_version()

    def test_missing_or_failed_git_and_controller_preflight(self):
        from unittest.mock import patch
        from runtime_requirements import require_git_version
        import subprocess
        for error in [FileNotFoundError(),subprocess.TimeoutExpired('git',10)]:
            with patch('runtime_requirements.subprocess.run',side_effect=error):
                with self.assertRaisesRegex(ValueError,'Git >= 2.29'):require_git_version()
        with patch('factory.require_git_version',side_effect=ValueError('Git >= 2.29')), patch('factory.locations') as locations:
            with self.assertRaises(ValueError):factory.main(['init','--repo','unused','--apply'])
            locations.assert_not_called()

    def test_cold_checkout_rejects_old_git_before_creating_destination(self):
        import tempfile
        from unittest.mock import patch
        from cold_workspace import clone_candidate, ColdWorkspaceError
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'new'
            with patch('cold_workspace.require_git_version',side_effect=ValueError('Git >= 2.29')):
                with self.assertRaises(ColdWorkspaceError):clone_candidate(directory,target,'a'*40,'b'*40)
            self.assertFalse(target.exists())


class PathSafetyTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()

    def test_trusted_root_alias_allowed_but_nested_link_and_traversal_rejected(self):
        from path_safety import checked_path
        real=self.root/'real';real.mkdir();alias=self.root/'alias';alias.symlink_to(real,target_is_directory=True)
        report=real/'report.json';report.write_text('{}',encoding='utf-8')
        self.assertEqual(checked_path(alias/'report.json',root=alias),report)
        (real/'link').symlink_to(real,target_is_directory=True)
        for path in [alias/'link'/'report.json',alias/'link'/'..'/'report.json']:
            with self.assertRaises(ValueError):checked_path(path,root=alias)

    def test_platform_temp_alias_accepts_reports_but_not_inner_link(self):
        from unittest.mock import patch
        from verification_policy import validate_evidence
        from test_report import parse_junit
        real=self.root/'real';real.mkdir();alias=self.root/'var';alias.symlink_to(real,target_is_directory=True)
        (real/'report.json').write_text(json.dumps({'status':'passed','total':1,'passed':1,'failed':0,'skipped':0,'tests':[{'id':'test','status':'passed'}]}),encoding='utf-8')
        (real/'native.xml').write_text('<testsuite><testcase name="test"/></testsuite>',encoding='utf-8')
        (real/'nested').symlink_to(real,target_is_directory=True)
        with patch('path_safety.tempfile.gettempdir',return_value=str(alias)):
            self.assertEqual(validate_evidence(alias/'report.json',{'min_tests':1})['total'],1)
            self.assertEqual(parse_junit(alias/'native.xml')['total'],1)
            self.assertEqual(factory.sha_file(alias/'report.json'),factory.sha_file(real/'report.json'))
            with self.assertRaises(ValueError):validate_evidence(alias/'nested'/'report.json',{'min_tests':1})
            with self.assertRaises(factory.FactoryError):factory.sha_file(alias/'nested'/'report.json')

    def test_posix_tmp_alias_works_when_default_temp_is_elsewhere(self):
        import os
        if os.name != 'posix':self.skipTest('POSIX /tmp alias simulation')
        from unittest.mock import patch
        from verification_policy import validate_evidence
        report=self.root/'report.json'
        report.write_text(json.dumps({'status':'passed','total':1,'passed':1,'failed':0,'skipped':0,'tests':[{'id':'test','status':'passed'}]}),encoding='utf-8')
        original=Path.resolve
        def resolve(path,*args,**kwargs):
            return self.root if path == Path('/tmp') else original(path,*args,**kwargs)
        with patch('path_safety.tempfile.gettempdir',return_value='/another/temp'), patch.object(Path,'resolve',resolve):
            self.assertEqual(validate_evidence('/tmp/report.json',{'min_tests':1})['total'],1)

    def test_windows_reparse_point_is_rejected(self):
        import stat
        from types import SimpleNamespace
        from unittest.mock import patch
        from path_safety import checked_path
        original=Path.lstat
        def lstat(path,*args,**kwargs):
            if path.name=='junction':return SimpleNamespace(st_mode=stat.S_IFDIR,st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
            return original(path,*args,**kwargs)
        with patch.object(Path,'lstat',lstat):
            with self.assertRaisesRegex(ValueError,'reparse'):checked_path(self.root/'junction'/'result.json',root=self.root)


class GitHubShapeTests(unittest.TestCase):
    def setUp(self):
        from test_assurance import GitHubTrustTests
        self.fixture=GitHubTrustTests();self.fixture.setUp()

    def test_malformed_run_nested_repositories_and_scalars_fail_closed(self):
        import copy
        from repair import github_findings
        original=self.fixture.run
        mutations=[None,[],42,'error']
        for key in original:
            for value in (None,[],42,True):
                data=copy.deepcopy(original);data[key]=value;mutations.append(data)
        for key in ('repository','head_repository'):
            for value in (None,{},[],True,42):
                data=copy.deepcopy(original);data[key]={'full_name':value};mutations.append(data)
        for run in mutations:
            with self.subTest(run=run), self.assertRaises(ValueError):
                github_findings(self.fixture.policy,42,'abc',lambda path:run)

    def test_malformed_jobs_steps_and_refetch_fail_closed(self):
        import copy
        from repair import github_findings
        mutations=[None,[],{}, {'jobs':None},{'jobs':[None]},{'jobs':['job']},{'jobs':[{}]}]
        job=self.fixture.jobs['jobs'][0]
        for key in job:
            for value in (None,{},42,True):
                if type(value) is type(job[key]) and value == job[key]:continue
                data=copy.deepcopy(job);data[key]=value;mutations.append({'jobs':[data]})
        for step in (None,[],{}, {'name':None,'conclusion':'failure'}, {'name':'Test','conclusion':[]},'error'):
            data=copy.deepcopy(job);data['steps']=[step];mutations.append({'jobs':[data]})
        for response in mutations:
            with self.subTest(response=response), self.assertRaises(ValueError):
                github_findings(self.fixture.policy,42,'abc',lambda path:response if '/jobs?' in path else self.fixture.run)
        calls=0
        def fetch(path):
            nonlocal calls
            calls+=1
            return None if calls==3 else self.fixture.fetch(path)
        with self.assertRaises(ValueError):github_findings(self.fixture.policy,42,'abc',fetch)

    def test_invalid_api_json_has_controlled_error(self):
        import subprocess
        from unittest.mock import patch
        from repair import api
        for raw in (b'broken',b'null',b'[]',b'"error"',b'\xff'):
            with patch('repair.subprocess.run',return_value=subprocess.CompletedProcess([],0,raw,b'')):
                with self.assertRaisesRegex(ValueError,'GitHub'):api('repos/owner/repo/actions/runs/1')


class UTF8Tests(unittest.TestCase):
    def test_unicode_prompt_transport_with_ascii_locale(self):
        import os
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root=Path(__file__).resolve().parents[1]
            worker="import sys;from pathlib import Path;Path('received.txt').write_bytes(sys.stdin.buffer.read())"
            program=("import sys;from pathlib import Path;sys.path.insert(0,"+repr(str(root))+");import factory;"
                     "root=Path("+repr(directory)+");"
                     "factory.run_agent({'argv':[sys.executable,'-c',"+repr(worker)+"], 'stdin_prompt':True},"
                     "root,root/'prompt.txt',root/'result.json',root/'agent.log',10,"+ascii('café 東京')+")")
            env={**os.environ,'LC_ALL':'C','LANG':'C','PYTHONUTF8':'0','PYTHONCOERCECLOCALE':'0'}
            result=subprocess.run([sys.executable,'-c',program],capture_output=True,text=True,encoding='utf-8',env=env)
            self.assertEqual(result.returncode,0,result.stderr)
            for name in ('prompt.txt','received.txt'):
                self.assertEqual((Path(directory)/name).read_bytes(),'café 東京'.encode('utf-8'))

    def test_production_text_files_and_pipes_specify_encoding(self):
        import ast
        root=Path(__file__).resolve().parents[1]
        for path in root.glob('*.py'):
            for call in ast.walk(ast.parse(path.read_bytes())):
                if not isinstance(call,ast.Call):continue
                name=call.func.attr if isinstance(call.func,ast.Attribute) else call.func.id if isinstance(call.func,ast.Name) else ''
                keys={k.arg:k.value for k in call.keywords}
                requires=name in ('read_text','write_text')
                if name in ('run','Popen','check_output'):
                    requires=isinstance(keys.get('text'),ast.Constant) and keys['text'].value is True
                if name in ('open','fdopen'):
                    if isinstance(call.func,ast.Attribute) and isinstance(call.func.value,ast.Name) and call.func.value.id=='os' and name=='open':continue
                    mode_index=1 if isinstance(call.func,ast.Name) or name=='fdopen' else 0
                    mode=keys.get('mode',call.args[mode_index] if len(call.args)>mode_index else ast.Constant('r'))
                    requires=isinstance(mode,ast.Constant) and 'b' not in mode.value
                if requires:
                    with self.subTest(file=path.name,line=call.lineno):
                        self.assertIsInstance(keys.get('encoding'),ast.Constant)
                        self.assertEqual(keys['encoding'].value,'utf-8')


class AdditionalAuditTests(unittest.TestCase):
    def test_legacy_pinned_claude_ids_and_current_ids_exclude_aliases(self):
        from agent_bridge import FULL_CLAUDE_ID
        for model in ['claude-3-5-sonnet-20241022','claude-3-opus-20240229','claude-sonnet-4-5-20250929','claude-opus-4-6']:
            self.assertIsNotNone(FULL_CLAUDE_ID.fullmatch(model),model)
        for model in ['sonnet','claude-sonnet-latest','claude-3-5-sonnet','claude-3-5-sonnet-latest']:
            self.assertIsNone(FULL_CLAUDE_ID.fullmatch(model),model)

    def test_update_columns_rejected_before_database_access(self):
        from unittest.mock import patch
        with patch('factory.connect') as connect:
            with self.assertRaisesRegex(factory.FactoryError,'column'):
                factory.update(Path('/unused'),'A','READY',**{'error=NULL; DROP TABLE tickets; --':'x'})
            connect.assert_not_called()

    def test_view_uses_configured_budget_and_tolerates_bad_config(self):
        import tempfile
        from ledger_view import snapshot
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);factory.initialize_db(home)
            (home/'.infra-factory').mkdir();config=home/'.infra-factory/config.json'
            with factory.connect(home) as con:
                con.execute('INSERT INTO tickets(id,ticket,state,updated) VALUES(?,?,?,?)',('A',json.dumps({'title':'A'}),'PENDING',1))
            for data,expected in [({'repair_policy':{'max_repairs':1}},2),({},3),({'repair_policy':{'max_repairs':9}},None),([],None)]:
                config.write_text(json.dumps(data),encoding='utf-8')
                self.assertEqual(snapshot(home,repo=home)['tickets'][0]['maximum_attempts'],expected)
            config.unlink()
            self.assertIsNone(snapshot(home,repo=home)['tickets'][0]['maximum_attempts'])
