"""Portable actual-port integration; requires a qualified CMW checkout on PYTHONPATH.

Only the interpreter shim's named external discoveries are substituted. Parser,
staging, supervision, metadata, Jobs receipts and CMW finalization run unchanged.
"""
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from cmw.jobs import runtime
from cmw.jobs.ownership import owner_alive
from cmw.jobs.store import Store, ACTIVE
from cmw.periodic.vasp.inputs import parse_incar
from cmw.periodic.vasp.result_finalization import finalize_result, verify_finalization, ResultFinalizationError
from tests.jobs.isolated_runtime import install
from tests.periodic.vasp.handoff_case import prepare_case, bind_completed_case, wait_for_fixture_sources

PORT = Path(__file__).resolve().parents[1]


def wait(predicate, timeout=35):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate(): return
        time.sleep(.05)
    raise AssertionError('Owned fixture deadline expired')


class ManagedForegroundTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix='port-managed-')).resolve()
        self.store=Store(self.root/'state')
        self.isolation=install();self.isolation.__enter__()
        self.owners=[]

    def tearDown(self):
        drained=False
        try:
            if self.store.path.exists():
                state=self.store.snapshot();self.owners.append(state['controller'].get('owner'))
                self.store.dispatch(False)
                for job in state['jobs']:
                    self.owners.extend((job.get('worker'),job.get('group')))
                    if job['status'] in ACTIVE: self.store.change(job['id'],'cancel',confirm=True)
                wait(lambda: not any(j['status'] in ACTIVE for j in self.store.snapshot()['jobs']))
                runtime.stop(self.store)
                for process in list(runtime._CHILDREN): process.wait(timeout=8)
                runtime.reap_detached()
                wait(lambda:not any(owner_alive(owner) for owner in self.owners if owner))
            drained=True
        finally:
            self.isolation.__exit__(None,None,None)
            result=self._outcome.result
            failed=any(test is self for test,_ in result.failures+result.errors)
            if drained and not failed:
                shutil.rmtree(self.root)
            else:
                print('Retained failed fixture:',self.root,file=sys.stderr)

    def case(self, **options):
        case=prepare_case(self.root/'case',**options)
        # Add invented valence metadata before a fresh preparation, never alter
        # an already-bound source bundle or its preparation record.
        spec=json.loads((case['root']/'prepare.json').read_text())
        for element in ('H','He'):
            p=case['root']/'library'/element/'POTCAR'
            p.write_text(p.read_text().replace('End of Dataset', 'ZVAL = 1.0\nEnd of Dataset'))
        from cmw.periodic.vasp.preparation import prepare
        inputs=case['root']/'port-inputs'
        prepared=prepare(case['root']/'prepare.json',output=inputs,scratch_root=case['scratch'],record_directory='port-preparation')
        case['inputs']=inputs;case['prepared']=prepared
        case['argv'][0]=str(PORT/'scripts/run-vasp.sh')
        case['argv'][case['argv'].index('--input')+1]=str(inputs)
        shim=case['root']/'python-shim'
        shim.write_text('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' '+shlex.quote(str(PORT/'tests/managed_fixture.py'))+' "$@"\n')
        shim.chmod(0o700)
        case['env']={'CMW_JOBS_OWN_SESSION':'1','CMW_MANAGED_PYTHON':str(shim),'PORT_TEST_CASE':str(case['root'])}
        # Binding helper can select a different genuine preparation record.
        case['preparation_record']=case['scratch']/'port-preparation/preparation.json'
        return case

    def launch(self, case):
        self.store.add(name='invented-port-case',argv=case['argv'],cwd=case['inputs'],env=case['env'])
        runtime.start(self.store)

    def finish(self, case):
        wait(lambda:self.store.snapshot()['jobs'][0]['status'] in {'Done','Fail','Cancelled','Unknown'})
        state=self.store.snapshot()
        self.assertNotEqual(state['jobs'][0]['status'],'Unknown',state['jobs'][0])
        bind_completed_case(case,state)
        return state['jobs'][0]

    def test_static_and_fixed_cell_actual_shell_binding_and_reverification(self):
        # The unittest loader runs this method twice through separate subclasses
        # below, keeping each native attempt in its own state and output tree.
        case=self.case(relaxation=getattr(self,'relaxation',False))
        before={p.name:p.read_bytes() for p in case['inputs'].iterdir()}
        self.launch(case);job=self.finish(case)
        self.assertEqual(job['status'],'Done',job)
        self.assertEqual(json.loads((case['root']/'threads.json').read_text()),{'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','VECLIB_MAXIMUM_THREADS':'1'})
        self.assertEqual(before,{p.name:p.read_bytes() for p in case['inputs'].iterdir()})
        for name in ('POSCAR','KPOINTS','POTCAR'): self.assertEqual((case['run']/name).read_bytes(),before[name])
        self.assertEqual(parse_incar((case['run']/'INCAR').read_text())['settings'],{**parse_incar(before['INCAR'].decode())['settings'], 'NCORE':2, 'KPAR':1})
        result=finalize_result(case['run'],policy_path=case['policy_path'],spec_path=case['spec_path'],scratch_root=case['scratch'],record_directory='accepted')
        self.assertTrue(verify_finalization(result['publication']['record_path'])['valid'])
        self.assertEqual(result['artifact_bundle']['artifact_count'],2 if getattr(self,'relaxation',False) else 1)

    def test_nonzero_and_scientific_failure_refuse_finalization(self):
        case=self.case(exit_code=7 if not getattr(self,'relaxation',False) else 0,converged=not getattr(self,'relaxation',False))
        self.launch(case);job=self.finish(case)
        self.assertEqual(job['status'],'Fail' if not getattr(self,'relaxation',False) else 'Done')
        with self.assertRaises(ResultFinalizationError):
            finalize_result(case['run'],policy_path=case['policy_path'],spec_path=case['spec_path'],scratch_root=case['scratch'],record_directory='refused')

    def test_leader_exit_waits_for_separate_rank_group(self):
        case=self.case();p=case['root']/'payload.json';data=json.loads(p.read_text());data['subgroup']=True;p.write_text(json.dumps(data))
        self.launch(case);wait(lambda:(case['root']/'rank.json').exists())
        rank=json.loads((case['root']/'rank.json').read_text());state=self.store.snapshot();job=state['jobs'][0]
        self.assertEqual(rank['sid'],job['group']['pid']);self.assertNotEqual(rank['pgid'],rank['sid'])
        time.sleep(.3);self.assertEqual(self.store.snapshot()['jobs'][0]['status'],'Run')
        self.assertNotIn('state: FINISHED',(case['run']/'RUN_METADATA.txt').read_text())
        (case['root']/'release').touch();self.assertEqual(self.finish(case)['status'],'Done')

    def test_timeout_preserves_outer_owner(self):
        case=self.case();p=case['root']/'payload.json';data=json.loads(p.read_text());data.update(subgroup=True,resistant=False);p.write_text(json.dumps(data))
        case['argv'][case['argv'].index('--timeout')+1]='1.5'
        self.launch(case);job=self.finish(case)
        self.assertEqual(job['status'],'Fail');self.assertEqual(job['exit_code'],124)
        self.assertIn('reason: timeout',(case['run']/'RUN_METADATA.txt').read_text())
        self.assertTrue(self.store.snapshot()['controller']['online'])


    def test_cancel_escalates_only_owned_rank_and_leaves_sentinel(self):
        from cmw.jobs.ownership import identity
        sentinel=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],start_new_session=True)
        sentinel_owner=identity(sentinel.pid)
        try:
            case=self.case();p=case['root']/'payload.json';data=json.loads(p.read_text());data.update(subgroup=True,resistant=True);p.write_text(json.dumps(data))
            self.launch(case);wait(lambda:(case['root']/'rank.json').exists())
            rank=json.loads((case['root']/'rank.json').read_text());rank_owner=identity(rank['pid'])
            state=self.store.snapshot();job=state['jobs'][0]
            self.owners.extend((job['group'],job['worker'],rank_owner))
            self.assertEqual(job['status'],'Run')
            self.store.change(job['id'],'cancel',confirm=True)
            wait(lambda:self.store.snapshot()['jobs'][0]['status']=='Cancelled')
            self.assertFalse(owner_alive(rank_owner))
            self.assertTrue(owner_alive(sentinel_owner))
            self.assertTrue(self.store.snapshot()['controller']['online'])
        finally:
            if owner_alive(sentinel_owner): sentinel.terminate()
            sentinel.wait(timeout=5)

    def test_timeout_escalates_resistant_subgroup_and_retains_metadata(self):
        case=self.case();p=case['root']/'payload.json';data=json.loads(p.read_text());data.update(subgroup=True,resistant=True);p.write_text(json.dumps(data))
        case['argv'][case['argv'].index('--timeout')+1]='1.5'
        self.launch(case);job=self.finish(case)
        self.assertEqual(job['exit_code'],124)
        self.assertIn('state: FINISHED',(case['run']/'RUN_METADATA.txt').read_text())
        self.assertTrue(self.store.snapshot()['controller']['online'])

    def test_actual_attempt_rejects_corrupt_associations_and_metadata(self):
        from copy import deepcopy
        from tests.periodic.vasp.result_case import digest, write_json
        case=self.case();self.launch(case);self.assertEqual(self.finish(case)['status'],'Done')
        metadata=case['run']/'RUN_METADATA.txt';original=metadata.read_text()
        copied=case['root']/'copied-metadata.txt';copied.write_text(original)
        incar=case['run']/'INCAR';original_incar=incar.read_text()
        for problem in ('missing-receipt','copied-receipt','wrong-attempt','wrong-input','wrong-output','missing-terminal','malformed-terminal','contradictory-status','copied-metadata','changed-effective-input'):
            with self.subTest(problem=problem):
                spec=deepcopy(case['spec']);metadata.write_text(original);incar.write_text(original_incar)
                if problem=='missing-receipt': spec['execution']['receipt']=str(case['root']/'absent.json')
                elif problem=='copied-receipt':
                    copy=case['root']/'receipt-copy.json';copy.write_bytes(case['receipt'].read_bytes());spec['execution']['receipt']=str(copy)
                elif problem=='wrong-attempt': spec['execution']['attempt_id']='0'*32
                elif problem=='wrong-input': metadata.write_text(original.replace('source: '+str(case['inputs']),'source: '+str(case['root'])))
                elif problem=='wrong-output': metadata.write_text(original.replace('output: '+str(case['run']),'output: '+str(case['root'])))
                elif problem=='missing-terminal': metadata.write_text(original.replace('state: FINISHED\n',''))
                elif problem=='malformed-terminal': metadata.write_text(original.replace('launcher_status: 0','launcher_status: unknown'))
                elif problem=='contradictory-status': metadata.write_text(original.replace('status: 0\n','status: 7\n'))
                elif problem=='copied-metadata': spec['execution']['runner_record']['path']=str(copied)
                elif problem=='changed-effective-input': incar.write_text(original_incar+'ENCUT=301\n')
                spec['execution']['runner_record']['sha256']=digest(Path(spec['execution']['runner_record']['path']))
                write_json(case['spec_path'],spec)
                wait_for_fixture_sources([metadata,incar,case['spec_path'],copied])
                with self.assertRaises(ResultFinalizationError):
                    finalize_result(case['run'],policy_path=case['policy_path'],spec_path=case['spec_path'],scratch_root=case['scratch'],record_directory='refused')
                self.assertFalse((case['scratch']/'refused').exists())

    def test_plan_use_source_change_and_output_collision_refuse(self):
        sys.path.insert(0,str(PORT/'scripts'))
        import run_vasp as runner
        import launch
        case=self.case()
        with patch.object(runner,'binary_identity',return_value=(Path(sys.executable),'invented')), \
             patch.object(launch,'mpi_command',return_value=([sys.executable,'-c','raise AssertionError("must not launch")'],dict(os.environ))), \
             patch.object(subprocess,'check_output',return_value='TEST ONLY Open MPI 5.0.9\n'), \
             patch.object(runner,'git_identity',return_value='invented'), \
             patch.object(launch,'supervise') as supervise:
            plan=runner.plan(runner.parser().parse_args([arg for arg in case['argv'][1:] if arg != '--managed-foreground']))
            case['run'].mkdir();sentinel=case['run']/'sentinel';sentinel.write_text('untouched')
            with self.assertRaises(FileExistsError): runner.execute(plan)
            self.assertEqual(sentinel.read_text(),'untouched')
            sentinel.unlink();case['run'].rmdir()
            (case['inputs']/'POSCAR').write_text((case['inputs']/'POSCAR').read_text()+'\n')
            self.assertEqual(runner.execute(plan),1)
            self.assertIn('changed after preflight',(case['run']/'RUN_METADATA.txt').read_text())
            supervise.assert_not_called()


class FixedCellTests(unittest.TestCase):
    relaxation=True
    setUp=ManagedForegroundTests.setUp
    tearDown=ManagedForegroundTests.tearDown
    case=ManagedForegroundTests.case
    launch=ManagedForegroundTests.launch
    finish=ManagedForegroundTests.finish
    test_fixed_cell_actual_shell_binding_and_reverification=ManagedForegroundTests.test_static_and_fixed_cell_actual_shell_binding_and_reverification
    test_exit_zero_scientific_failure_refuses=ManagedForegroundTests.test_nonzero_and_scientific_failure_refuse_finalization

class ScopeTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0,str(PORT/'scripts'))
        import launch
        self.launch=launch

    def test_standalone_completion_and_nonzero_exit(self):
        for status in (0,7):
            with self.subTest(status=status):
                result=self.launch.supervise([sys.executable,'-c',f'raise SystemExit({status})'],5,stop_before=0)
                self.assertEqual(result['status'],status)
                self.assertEqual(result['reason'],'completed')

    def test_preexisting_same_session_sibling_refuses_before_launch(self):
        import cmw.jobs.ownership as ownership
        with patch.dict(os.environ,{'CMW_JOBS_OWN_SESSION':'1'}), \
             patch.object(os,'getpid',return_value=20),patch.object(os,'getpgrp',return_value=10), \
             patch.object(os,'getsid',return_value=10), \
             patch.object(ownership,'identity',return_value={'pid':10}), \
             patch.object(ownership,'owner_alive',return_value=True), \
             patch.object(ownership,'group_members',return_value=[10,20,30]), \
             patch.object(subprocess,'Popen') as popen:
            with self.assertRaisesRegex(ValueError,'sole foreground'):
                self.launch.supervise(['never-executed'],1,managed_foreground=True)
            popen.assert_not_called()

    def test_uncertain_cleanup_is_not_repeated(self):
        import cmw.jobs.ownership as ownership
        from cmw.jobs.store import JobsError
        def refused(owner, signum, *, include_leader=True):
            raise JobsError('modeled identity replacement')
        with patch.dict(os.environ,{'CMW_JOBS_OWN_SESSION':'1'}), \
             patch.object(os,'getpid',return_value=20),patch.object(os,'getpgrp',return_value=10), \
             patch.object(os,'getsid',return_value=10),patch.object(os,'getpgid',return_value=30), \
             patch.object(ownership,'identity',return_value={'pid':10}), \
             patch.object(ownership,'owner_alive',return_value=True), \
             patch.object(ownership,'group_members',side_effect=[[10,20],[10,20,30]]), \
             patch.object(ownership,'signal_session',side_effect=refused,spec=ownership.signal_session) as signalling, \
             patch.object(subprocess,'Popen') as popen:
            # Preserve the signature inspection while modeling a refused shared gate.
            import inspect
            with patch.object(self.launch.inspect,'signature',return_value=inspect.Signature([inspect.Parameter('include_leader',inspect.Parameter.KEYWORD_ONLY,default=True)])):
                popen.return_value.poll.return_value=None
                with self.assertRaisesRegex(JobsError,'identity replacement'):
                    self.launch.supervise(['never-executed'],.001,managed_foreground=True)
            self.assertEqual(signalling.call_count,1)
            self.assertFalse(signalling.call_args.kwargs['include_leader'])


if __name__=='__main__': unittest.main()
