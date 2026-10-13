"""Controlled runner contracts with benign model processes; no MPI or engine runs."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import launch
import run_vasp


class OptionsTests(unittest.TestCase):
    def test_controlled_plan_refuses_incomplete_contract_before_inputs(self):
        base = ['--input', '/missing-test-input', '--output', '/missing-test-output', '--timeout', '20']
        cases = [(['--controlled-suspension'], 'managed-foreground'),
                 (['--execution-budget', '10'], 'requires --controlled'),
                 (['--controlled-suspension', '--managed-foreground'], 'execution-budget'),
                 (['--controlled-suspension', '--managed-foreground', '--execution-budget', 'nan'], 'execution-budget'),
                 (['--controlled-suspension', '--managed-foreground', '--execution-budget', '10', '--stop-before', '1'], 'STOPCAR')]
        for options, message in cases:
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, message):
                run_vasp.plan(run_vasp.parser().parse_args(base + options))
        with patch.dict(os.environ, {'CMW_SUSPENSION_CONTEXT': '/invented/context.json'}):
            with self.assertRaisesRegex(ValueError, 'explicit --controlled'):
                run_vasp.plan(run_vasp.parser().parse_args(base))

    def test_local_explicit_mpi_signal_route_and_environment_refusal(self):
        with patch.dict(os.environ, {}, clear=True):
            command, environment = launch.mpi_command(['/benign-program'], 2, 'native',
                managed_foreground=True, controlled_suspension=True)
            self.assertEqual(command, [launch.MPI, '-np', '2', '--host', 'localhost:2',
                                      '--forward-signals', 'SIGTSTP,SIGCONT', '/benign-program'])
        for key in ('PRTE_MCA_ras', 'OMPI_MCA_timeout', 'SLURM_JOB_ID', 'PMIX_MCA_psec'):
            with patch.dict(os.environ, {key: 'invented'}, clear=True), self.assertRaisesRegex(ValueError, 'overrides'):
                launch.mpi_command(['/benign-program'], 2, 'native',
                    managed_foreground=True, controlled_suspension=True)

    def test_no_inferred_awake_or_advance_stop(self):
        for options in ({'awake': True}, {'stop_before': 1}, {'managed_foreground': False}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, 'Controlled suspension'):
                launch.supervise(['/never-launched'], 20, control=object(), execution_budget=10,
                                 **{'managed_foreground': True, **options})


class CoordinatedSupervisorTests(unittest.TestCase):
    def run_model(self, *, hard=2, execution=1, paused=.3):
        import cmw.jobs.ownership as ownership
        class Process:
            pid = 30
            returncode = None
            def poll(self):
                if control.ticks >= 5 or control.termination:
                    self.returncode = -15 if control.termination else 0
                return self.returncode
        process = Process()
        class Control:
            ticks = 0
            intervals = []
            termination = None
            def register(self, pid, strategy):
                self.registered = (pid, strategy)
            def poll(self):
                self.ticks += 1
                return 'hold' if self.ticks in (2, 3, 4) else 'run'
            @property
            def elapsed(self): return self.ticks * .1
            @property
            def suspended_seconds(self): return paused
            @property
            def unsuspended_elapsed(self): return self.elapsed - paused
            def domain_drained(self): return process.returncode is not None
            def execution_budget_exhausted(self, budget): return self.unsuspended_elapsed >= budget
            def request_termination(self, reason, exit_code=124): self.termination = (reason, exit_code)
        control = Control()
        with patch.dict(os.environ, {'CMW_JOBS_OWN_SESSION': '1'}), \
             patch.object(os, 'getpid', return_value=20), patch.object(os, 'getpgrp', return_value=10), \
             patch.object(os, 'getsid', return_value=10), patch.object(os, 'getpgid', return_value=30), \
             patch.object(ownership, 'identity', return_value={'pid': 10}), \
             patch.object(ownership, 'owner_alive', return_value=True), \
             patch.object(ownership, 'group_members', side_effect=lambda *a, **k: [10, 20] if process.returncode is not None or control.ticks == 0 else [10, 20, 30]), \
             patch.object(launch.subprocess, 'Popen', return_value=process), \
             patch.object(launch.time, 'sleep'), patch.object(os, 'killpg') as killpg, \
             patch.object(ownership, 'signal_session') as signal_session:
            # Keep the required protected-leader signature available to the legacy guard.
            import inspect
            with patch.object(launch.inspect, 'signature', return_value=inspect.Signature([
                    inspect.Parameter('include_leader', inspect.Parameter.KEYWORD_ONLY, default=True)])):
                result = launch.supervise(['/benign-model'], hard, managed_foreground=True,
                                          control=control, execution_budget=execution)
            killpg.assert_not_called(); signal_session.assert_not_called()
        self.assertEqual(control.registered, (30, 'openmpi'))
        return result, control

    def test_same_child_remains_live_through_hold_and_genuine_completion(self):
        result, control = self.run_model(execution=.4)
        self.assertEqual((result['status'], result['child_status'], result['reason']), (0, 0, 'completed'))
        self.assertIsNone(control.termination)
        self.assertEqual(result['confirmed_suspended_seconds'], .3)
        self.assertAlmostEqual(result['unsuspended_elapsed_seconds'], .2)

    def test_hard_deadline_is_not_extended_by_suspension(self):
        result, control = self.run_model(hard=.25)
        self.assertEqual(control.termination, ('timeout', 124))
        self.assertEqual((result['status'], result['child_status']), (124, -15))

    def test_execution_budget_is_separate_from_hard_deadline(self):
        result, control = self.run_model(execution=.15, paused=0)
        self.assertEqual(control.termination, ('execution-budget', 124))
        self.assertEqual((result['status'], result['child_status']), (124, -15))
