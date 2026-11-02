"""Local integration: real isolated CMW queue, synthetic Python payloads only.

Run with the existing CMW Python and its src directory on PYTHONPATH.
No VASP executable, production queue or scientific output is touched.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from cmw.jobs.store import Store
from cmw.jobs.runtime import start, stop, reap_detached
from cmw.jobs.ownership import group_members

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
ORCHESTRATOR = '/Volumes/Scratch/run_wp1_05_01_after_orca.py'


def wait_for(predicate, seconds=15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        result = predicate()
        if result:
            return result
        time.sleep(.05)
    raise AssertionError('Synthetic lifecycle timed out')


class ManagedTests(unittest.TestCase):
    def test_production_managed_launch_requires_cmw_owner(self):
        result = subprocess.run(
            [sys.executable, '-B', ORCHESTRATOR, '--cmw-managed', '--phases', 'IIb',
             '--vasp-timeout', '604800', '--start-if-no-orca'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('CMW', result.stderr)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wp1-cmw-test-')
        self.root = Path(self.temp.name).resolve()
        self.store = Store(self.root / 'state')

    def tearDown(self):
        if self.store.path.exists():
            for j in self.store.snapshot()['jobs']:
                if j['status'] in {'Starting', 'Run'}:
                    self.store.change(j['id'], 'cancel', confirm=True)
            wait_for(lambda: all(j['status'] not in {'Starting','Run','Cancelling'}
                                 for j in self.store.snapshot()['jobs']))
            stop(self.store)
            wait_for(lambda: not self.store.snapshot()['controller']['online'])
        reap_detached()
        self.temp.cleanup()

    def enqueue(self, code):
        return self.store.add(argv=[sys.executable, '-B', '-c', code], cwd=self.root,
                              name='synthetic WP1', engine='Synthetic',
                              env={'CMW_JOBS_STATE': str(self.store.root), 'CMW_JOBS_OWN_SESSION': '1'})

    def payload(self, outcome='normal'):
        marker = str(self.root / 'members.json')
        ready = str(self.root / 'leaf-ready')
        leaf = (f'import signal,time,pathlib; signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                f'pathlib.Path({ready!r}).touch(); time.sleep(60)')
        body = (f'import os,json,pathlib,subprocess,sys,time; '
                f'p=subprocess.Popen([sys.executable,"-c",{leaf!r}]); '
                f'exec("while not pathlib.Path({ready!r}).exists(): time.sleep(.01)"); '
                f'pathlib.Path({marker!r}).write_text(json.dumps([os.getpid(),p.pid,os.getpgrp()])); ')
        if outcome == 'normal':
            body += 'p.kill(); p.wait(); time.sleep(.2)'
        elif outcome == 'failure':
            body += 'p.kill(); p.wait(); sys.exit(7)'
        else:
            body += 'time.sleep(60)'
        inner = (f'import sys; sys.path.insert(0,{str(SCRIPTS)!r}); import launch; '
                 f'r=launch.supervise([sys.executable,"-c",{body!r}],60,managed_foreground=True); '
                 f'sys.exit(r["status"])')
        budget = 6 if outcome == 'timeout' else 60
        return (f'import runpy,sys,signal; w=runpy.run_path({ORCHESTRATOR!r}); '
                f'o=w["LauncherOwner"](managed=True); w["configure_cmw"](o,{budget}); '
                f'signal.signal(signal.SIGTERM,o.receive); signal.signal(signal.SIGINT,o.receive); '
                f'sys.exit(o.run([sys.executable,"-c",{inner!r}],print))')

    def test_success_and_failure(self):
        self.enqueue(self.payload())
        self.enqueue(self.payload('failure'))
        start(self.store)
        wait_for(lambda: [j['status'] for j in self.store.snapshot()['jobs']] == ['Done','Fail'])
        jobs = self.store.snapshot()['jobs']
        self.assertLessEqual(jobs[0]['finished_at'], jobs[1]['started_at'])
        self.assertEqual(jobs[1]['exit_code'], 7)

    def exercise_cancel(self, timeout):
        job = self.enqueue(self.payload('timeout' if timeout else 'cancel'))
        later = self.enqueue('raise RuntimeError("must not start")')
        unrelated = subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'], start_new_session=True)
        try:
            start(self.store)
            wait_for(lambda: (self.root / 'members.json').exists())
            parent, leaf, pgid = json.loads((self.root / 'members.json').read_text())
            live = self.store.snapshot()['jobs'][0]
            self.assertEqual(pgid, live['group']['pid'])
            self.assertEqual(os.getpgid(parent), pgid)
            self.assertEqual(os.getpgid(leaf), pgid)
            if not timeout:
                self.store.change(job['id'], 'cancel', confirm=True)
            try:
                wait_for(lambda: self.store.snapshot()['jobs'][0]['status'] in {'Cancelled','Unknown'})
            except AssertionError:
                print(json.dumps(self.store.snapshot(), default=str), flush=True)
                print(Path(live['logs']['stdout']).read_text(), flush=True)
                print(Path(live['logs']['stderr']).read_text(), flush=True)
                raise
            self.assertFalse(group_members(pgid))
            stopped = self.store.snapshot()['jobs'][0]
            if stopped['status'] == 'Unknown':
                self.assertTrue(stopped['cancel_requested'])
                self.assertEqual(stopped['reason'], 'Process group absence cannot be verified')
                print('CMW retained Unknown after OS group-absence permission error; no live members or next dispatch', flush=True)
            self.assertIsNone(self.store.snapshot()['jobs'][1]['started_at'])
            self.assertIsNone(unrelated.poll())
        finally:
            unrelated.terminate(); unrelated.wait(timeout=3)

    def test_cancel_drains_all_members(self):
        self.exercise_cancel(False)

    def test_budget_requests_cmw_cancel(self):
        self.exercise_cancel(True)

    def test_unowned_session_refused(self):
        code = (f'import sys;sys.path.insert(0,{str(SCRIPTS)!r});import launch;'
                'launch.supervise(["/usr/bin/true"],1,managed_foreground=True)')
        result = subprocess.run([sys.executable,'-c',code],start_new_session=True,capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'inherited dedicated', result.stderr)

    def run_real_mpi(self, cancel=False):
        body = (f'import os,pathlib,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); pathlib.Path({str(self.root)!r},'
                '"rank-"+os.environ["OMPI_COMM_WORLD_RANK"]).write_text(str(os.getsid(0))); '
                + ('time.sleep(60)' if cancel else ''))
        inner = (f'import sys;sys.path.insert(0,{str(SCRIPTS)!r});import launch;'
                 f'cmd,env=launch.mpi_command([sys.executable,"-c",{body!r}],8,"synthetic",managed_foreground=True);'
                 'r=launch.supervise(cmd,30,env=env,managed_foreground=True);sys.exit(r["status"])')
        outer = (f'import runpy,sys,signal;w=runpy.run_path({ORCHESTRATOR!r});'
                 'o=w["LauncherOwner"](managed=True);w["configure_cmw"](o,60);'
                 'signal.signal(signal.SIGTERM,o.receive);signal.signal(signal.SIGINT,o.receive);'
                 f'sys.exit(o.run([sys.executable,"-c",{inner!r}],print))')
        queued = self.enqueue(outer)
        start(self.store)
        if cancel:
            wait_for(lambda: len(list(self.root.glob('rank-*'))) == 8)
            self.store.change(queued['id'], 'cancel', confirm=True)
        wait_for(lambda: self.store.snapshot()['jobs'][0]['status'] in {'Done','Fail','Cancelled','Unknown'}, seconds=35)
        job = self.store.snapshot()['jobs'][0]
        if job['status'] == 'Unknown':
            print(job['reason'], Path(job['logs']['stderr']).read_text(), flush=True)
        if cancel:
            self.assertEqual(job['status'], 'Cancelled')
            self.assertFalse(group_members(job['group']['pid'], session=True))
        else:
            self.assertEqual(job['status'], 'Done', Path(job['logs']['stderr']).read_text())
        files = list(self.root.glob('rank-*'))
        self.assertEqual(len(files), 8)
        self.assertEqual({int(p.read_text()) for p in files}, {job['group']['pid']})

    def test_real_mpi_ranks_remain_in_cmw_session(self):
        self.run_real_mpi()

    def test_real_mpi_cancellation(self):
        self.run_real_mpi(cancel=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
