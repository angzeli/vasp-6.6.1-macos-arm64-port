"""Deterministic runner contracts; no VASP is executed by this test module."""
import ast
import contextlib
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import run_vasp as runner
import launch

POSCAR='Si synthetic fixture\n5.43\n0 .5 .5\n.5 0 .5\n.5 .5 0\nSi\n2\nDirect\n0 0 0\n.25 .25 .25\n'
MESH='mesh\n0\nGamma\n2 2 2\n0 0 0\n'
OPT='path\n4\nLine-mode\nReciprocal\n0 0 0 ! G\n.5 .5 .5 ! L\n'


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='synthetic ',dir=ROOT/'private/launcher-tests')
        self.root=Path(self.temp.name);self.source=self.root/'input space';self.source.mkdir()
        for n,s in {'INCAR':'ENCUT=300\nEDIFF=1E-6\n','POSCAR':POSCAR,'POTCAR':'synthetic only; ZVAL = 4.0\n','KPOINTS':MESH}.items():
            (self.source/n).write_text(s)
        self.output=self.root/'output space'
        self.binary=Path('/usr/bin/true')
        self.mock=patch.object(runner,'binary_identity',return_value=(self.binary,'synthetic'))
        self.mock.start()

    def tearDown(self):
        self.mock.stop();self.temp.cleanup()

    def args(self,*extra):
        return runner.parser().parse_args(['--input',str(self.source),'--output',str(self.output),'--timeout','5',*extra])

    def make(self,incar=None,*extra):
        if incar is not None:(self.source/'INCAR').write_text(incar)
        return runner.plan(self.args(*extra))

    def test_parallel_parser_preserves_science(self):
        original='encut=300; NcOrE = 2 ! keep comment\nKPAR=1; HFSCREEN=.2 # text\nMAGMOM = 0 \\\n 0\nNPAR=8\n'
        p=self.make(original,'--ranks','8','--ncore','4')
        parsed=runner.Incar(p['effective'])
        self.assertEqual(parsed.values('NCORE'),['4']);self.assertEqual(parsed.values('KPAR'),['1'])
        self.assertFalse(parsed.values('NPAR'))
        for key in ['ENCUT','HFSCREEN','MAGMOM']:
            self.assertEqual(parsed.get(key),runner.Incar(original).get(key))
        self.assertIn('HFSCREEN=.2 # text',p['effective'])
        self.assertEqual(p['origins'],{'NCORE':'CLI','KPAR':'INCAR'})

    def test_duplicates_and_npar(self):
        p=self.make('NCORE=1; ncore=1\nKPAR=1; kpar=1\n')
        self.assertEqual(len(runner.Incar(p['effective']).values('NCORE')),1)
        for text in ['NCORE=1; NCORE=2','KPAR=1; KPAR=2','NPAR=1','ENCUT=300; ENCUT=400', 'NCORE="1"', 'NCORE=(1)', 'NCORE=1 KPAR=1']:
            with self.subTest(text=text),self.assertRaises(runner.PreflightError):self.make(text)
        self.assertEqual(self.make('NCORE=1;NCORE=2','--ncore','1')['parallel']['NCORE'],1)

    def test_defaults_and_divisibility(self):
        self.assertEqual(self.make()['parallel'],{'NCORE':1,'KPAR':1})
        self.assertEqual(self.make(None,'--ranks','8','--ncore','2','--kpar','2')['parallel'],{'NCORE':2,'KPAR':2})
        for extra in [('--ranks','9'),('--ranks','0'),('--ncore','0'),('--ranks','8','--kpar','3'),('--ranks','8','--kpar','2','--ncore','3')]:
            with self.subTest(extra=extra),self.assertRaises(runner.PreflightError):self.make(None,*extra)
        for tag in ['IMAGES=2','NOMEGAPAR=2','NCORE_IN_IMAGE1=4','LCLIMB=T']:
            with self.subTest(tag=tag),self.assertRaises(runner.PreflightError):self.make(tag)

    def test_paths_and_exclusive_destination(self):
        for destination in [self.source,self.source/'nested',ROOT/'scripts/new-run',Path('/Applications/Academic/new-run')]:
            args=self.args();args.output=destination
            with self.subTest(path=destination),self.assertRaises(runner.PreflightError):runner.plan(args)
        alias=self.root/'alias';alias.symlink_to(self.source,target_is_directory=True)
        args=self.args();args.output=alias/'nested'
        with self.assertRaises(runner.PreflightError):runner.plan(args)
        p=self.make();self.output.mkdir()
        with self.assertRaises(runner.PreflightError):self.make()
        # A destination created by a competing claimant after preflight is untouched.
        (self.output/'sentinel').write_text('other owner')
        with patch.object(runner,'git_identity',return_value='test'),patch.object(subprocess,'check_output',return_value='mpirun (Open MPI) 5.0.9\n'):
            with self.assertRaises(FileExistsError):runner.execute(p)
        self.assertEqual(list(self.output.iterdir()),[self.output/'sentinel'])

    def test_required_files_and_extra_inputs(self):
        for name in runner.REQUIRED:
            path=self.source/name;original=path.read_bytes();path.write_bytes(b'')
            with self.subTest(name=name),self.assertRaises(runner.PreflightError):self.make()
            path.write_bytes(original)
        path=self.source/'KPOINTS';path.unlink()
        with self.assertRaises(runner.PreflightError):self.make()
        path.write_text(MESH)
        for name in ['../x','STOPCAR','WAVECAR','OUTCAR.old','x;touch y','script.sh','sub/file']:
            with self.subTest(name=name),self.assertRaises(runner.PreflightError):self.make(None,'--extra-input',name)
        (self.source/'kernel data').write_text('synthetic auxiliary')
        self.assertIn('kernel data',self.make(None,'--extra-input','kernel data')['files'])

    def test_restart_mismatches_and_overlap(self):
        for incar,extra in [('ISTART=1',()),('ICHARG=1',()),('',('--restart','wavecar')),('ISTART=0;ICHARG=2',('--restart','chgcar'))]:
            with self.subTest(incar=incar,extra=extra),self.assertRaises(runner.PreflightError):self.make(incar,*extra)
        with self.assertRaises(runner.PreflightError):self.make(None,'--restart-from',str(self.source))
        donor=self.root/'donor';donor.mkdir();args=self.args('--restart','wavecar','--restart-from',str(donor));args.output=donor/'result'
        with self.assertRaises(runner.PreflightError):runner.plan(args)
        self.assertFalse(self.output.exists())

    def test_kpoints_and_soc_guards(self):
        (self.source/'KPOINTS_OPT').write_text(OPT)
        with self.assertRaises(runner.PreflightError):self.make(None,'--binary','gam')
        with self.assertRaises(runner.PreflightError):self.make('LHFCALC=T','--ranks','2','--ncore','2')
        with self.assertRaises(runner.PreflightError):self.make('LHFCALC=T;ICHARG=11')
        (self.source/'KPOINTS').write_text(OPT)
        with self.assertRaises(runner.PreflightError):self.make()
        (self.source/'KPOINTS').write_text('gamma\n0\nGamma\n1 1 1\n')
        p=self.make('LKPOINTS_OPT=F','--binary','gam');self.assertFalse(p['active_opt'])
        (self.source/'KPOINTS_OPT').write_text('bad but disabled')
        self.assertFalse(self.make('LKPOINTS_OPT=F')['active_opt'])
        with self.assertRaises(runner.PreflightError):self.make('LKPOINTS_OPT=T')
        (self.source/'KPOINTS_OPT').unlink()
        for tag in ['LSORBIT=T','LNONCOLLINEAR=T']:
            with self.subTest(tag=tag),self.assertRaises(runner.PreflightError):self.make(tag)
        self.assertEqual(self.make('LSORBIT=T','--binary','ncl')['args'].binary,'ncl')

    def test_dry_run_no_files_and_help(self):
        before=set(self.root.rglob('*'))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(['--input',str(self.source),'--output',str(self.output),'--dry-run']),0)
        self.assertEqual(before,set(self.root.rglob('*')))
        result=subprocess.run([str(ROOT/'scripts/run-vasp.sh'),'--help'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0);self.assertIn('--restart-from',result.stdout)
        for extra in [('--timeout','0'),('--timeout','nan'),('--stop-before','5'),('--stop-before','-1')]:
            with self.subTest(extra=extra),self.assertRaises(runner.PreflightError):runner.plan(self.args(*extra))
        args=self.args();args.timeout=None
        with self.assertRaises(runner.PreflightError):runner.plan(args)

    def test_checkpoint_and_unknown_restart_are_not_convergence(self):
        p=self.make();self.output.mkdir()
        (self.output/'stdout.log').write_text('vasp.6.6.1\n')
        (self.output/'OUTCAR').write_text('General timing and accounting\n')
        data,version,rejected=runner.output_evidence(p)
        self.assertTrue(version);self.assertFalse(rejected)
        self.assertEqual(data['scientific_convergence'],'NOT ASSESSED')
        p['args'].restart='wavecar';p['files']['WAVECAR']=self.source/'WAVECAR'
        (self.output/'stdout.log').write_text('vasp.6.6.1\nWAVECAR not read\n')
        data,_,rejected=runner.output_evidence(p)
        self.assertTrue(rejected);self.assertIn('REJECTED',data['restart_observed'])

    def test_nelm_footer_does_not_prove_convergence(self):
        p=self.make('NELM=1;NELMIN=1');self.output.mkdir()
        (self.output/'stdout.log').write_text('vasp.6.6.1\n')
        result=dict(energy_eV=1.,nelect=8.,normal=True,converged=True,iterations=1,params={'NELM':'1'})
        with patch.object(runner,'read_case',return_value=result):
            evidence,_,_=runner.output_evidence(p)
        self.assertEqual(evidence['scientific_convergence'],'NOT CONFIRMED (NELM limit or electronic stop request)')

    def test_stopcar_exclusive_callback_and_nonzero_exit(self):
        out=self.root/'stop';out.mkdir();(out/'STOPCAR').write_text('user stop request')
        def stop():
            try:
                with (out/'STOPCAR').open('x') as f:f.write('LABORT = .TRUE.\n')
            except FileExistsError:return 'existing STOPCAR preserved'
        result=launch.supervise([sys.executable,'-c','import time; time.sleep(10)'],.3,stop_before=.2,on_stop=stop,grace=.2)
        self.assertEqual(result['status'],124);self.assertIn('preserved',result['advance_stop'])
        self.assertEqual((out/'STOPCAR').read_text(),'user stop request')
        result=launch.supervise([sys.executable,'-c','raise SystemExit(7)'],2,grace=.2)
        self.assertEqual((result['status'],result['child_status']),(7,7))

    def test_actual_staging_metadata_and_stop_callback(self):
        (self.source/'OUTCAR').write_text('old output must stay at input')
        (self.source/'WAVECAR').write_bytes(b'accidental restart must not be staged')
        original=(self.source/'INCAR').read_bytes()
        p=self.make(None,'--stop-before','1')
        def fake_supervise(*args,**kwargs):
            self.assertTrue(kwargs['awake'])
            self.assertEqual(args[1],5)
            message=kwargs['on_stop']()
            self.assertEqual((self.output/'STOPCAR').read_text(),'LABORT = .TRUE.\n')
            return dict(status=7,child_status=7,reason='completed',advance_stop=message)
        with patch.object(launch,'supervise',side_effect=fake_supervise),patch.object(runner,'git_identity',return_value='synthetic test'):
            with contextlib.redirect_stdout(io.StringIO()):status=runner.execute(p)
        self.assertEqual(status,7)
        self.assertEqual((self.source/'INCAR').read_bytes(),original)
        self.assertFalse((self.output/'WAVECAR').exists())
        self.assertFalse((self.output/'OUTCAR').exists())
        self.assertNotEqual((self.source/'POTCAR').stat().st_ino,(self.output/'POTCAR').stat().st_ino)
        metadata=(self.output/'RUN_METADATA.txt').read_text()
        self.assertIn('child_status: 7',metadata)
        self.assertIn('scientific_convergence: NOT ASSESSED',metadata)
        self.assertEqual(set(x.name for x in self.output.iterdir()),set(runner.REQUIRED)|{'RUN_METADATA.txt','stdout.log','stderr.log','STOPCAR'})

    def test_ionic_stop_preserves_existing_request(self):
        p=self.make('NSW=1','--stop-before','1')
        def fake_supervise(*args,**kwargs):
            kwargs['on_stop']()
            stop=self.output/'STOPCAR'
            self.assertEqual(stop.read_text(),'LSTOP = .TRUE.\n')
            stop.write_text('LABORT = .TRUE. # user request\n')
            self.assertIn('preserved',kwargs['on_stop']())
            self.assertEqual(stop.read_text(),'LABORT = .TRUE. # user request\n')
            return dict(status=7,child_status=7,reason='completed')
        with patch.object(launch,'supervise',side_effect=fake_supervise),patch.object(runner,'git_identity',return_value='synthetic test'):
            with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(runner.execute(p),7)

    def test_low_level_cli_remains_compatible(self):
        result=dict(status=7,child_status=7,reason='completed',elapsed_s=.1)
        with patch.object(launch,'mpi_command',return_value=(['synthetic'],{})) as command,patch.object(launch,'supervise',return_value=result) as supervisor,contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(launch.main(['--','/usr/bin/true']),7)
            command.assert_called_once_with(['/usr/bin/true'],1,'native')
            supervisor.assert_called_once_with(['synthetic'],600,env={})

    def test_timeout_and_signals_clean_descendants_only(self):
        unrelated=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],start_new_session=True)
        try:
            for sig,expected in [(None,124),(signal.SIGINT,130),(signal.SIGTERM,143)]:
                marker=self.root/f'leaf-{expected}'
                leaf='import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)'
                child=f'import subprocess,sys,time,pathlib; p=subprocess.Popen([sys.executable,"-c",{leaf!r}]);pathlib.Path({str(marker)!r}).write_text(str(p.pid));time.sleep(60)'
                code=f'import sys;sys.path.insert(0,{str(ROOT/"scripts")!r});from launch import supervise;r=supervise([sys.executable,"-c",{child!r}],{.5 if sig is None else 10},grace=.3);print(repr(r));sys.exit(r["status"])'
                parent=subprocess.Popen([sys.executable,'-B','-c',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
                end=time.monotonic()+3
                while not marker.exists() and time.monotonic()<end:time.sleep(.02)
                self.assertTrue(marker.exists())
                if sig:parent.send_signal(sig)
                stdout,stderr=parent.communicate(timeout=5)
                self.assertEqual(parent.returncode,expected,(stdout,stderr))
                result=ast.literal_eval(stdout.strip());self.assertIsNotNone(result['child_status'])
                pid=int(marker.read_text());time.sleep(.1)
                state=subprocess.run(['ps','-o','stat=','-p',str(pid)],capture_output=True,text=True).stdout.strip()
                self.assertTrue(not state or state.startswith('Z'),state)
                self.assertIsNone(unrelated.poll())
        finally:
            unrelated.terminate();unrelated.wait(timeout=3)


if __name__=='__main__':unittest.main()
