"""Pinned experimental binary selection (--binary-manifest); no VASP is executed.

The executable is a private copy of /usr/bin/true, the aggregator is a synthetic
stub and MPI supervision is patched, so only the runner's own selection,
environment and metadata contracts are exercised.
"""
from datetime import datetime, timezone
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import run_vasp as runner
import launch

POSCAR = 'Si synthetic fixture\n5.43\n0 .5 .5\n.5 0 .5\n.5 .5 0\nSi\n2\nDirect\n0 0 0\n.25 .25 .25\n'
AGGREGATOR = '''import json, sys
args = dict(zip(sys.argv[2::2], sys.argv[3::2]))
data = {"schema": "vmb.attempt-evidence.v1", "attempt_id": args["--attempt-id"], "evidence": "COMPLETE"}
open(args["--output"], "x").write(json.dumps(data))
print(json.dumps({"evidence": "COMPLETE", "consumed": 3}), file=sys.stderr)
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ManifestTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'private/launcher-tests').mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='manifest ', dir=ROOT / 'private/launcher-tests')
        self.root = Path(self.temp.name).resolve()
        self.host = self.root / 'host'
        (self.host / 'private/binary-manifests').mkdir(parents=True)
        self.source = self.root / 'input'
        self.source.mkdir()
        for name, text in {'INCAR': 'ENCUT=300\n', 'POSCAR': POSCAR,
                           'POTCAR': 'synthetic only; ZVAL = 4.0\n', 'KPOINTS': 'm\n0\nGamma\n2 2 2\n'}.items():
            (self.source / name).write_text(text)
        self.output = self.root / 'output'
        self.exe = self.root / 'relink/vasp_std_vmb'
        self.exe.parent.mkdir()
        shutil.copy('/usr/bin/true', self.exe)
        self.aggregator = self.root / 'vmb_evidence.py'
        self.aggregator.write_text(AGGREGATOR)
        self.cellar = self.root / 'Cellar/libdemo.dylib'
        self.cellar.parent.mkdir()
        self.cellar.write_bytes(b'synthetic library')
        self.opt = self.root / 'opt-libdemo.dylib'
        self.opt.symlink_to(self.cellar)
        self.patches = [patch.object(runner, 'ROOT', self.host),
                        patch.dict(os.environ, {'VMB_REPORT': '/tmp/inherited', 'VMB_MODE': 'off'}),
                        patch.dict(launch.TOOLCHAIN, dict(launch.TOOLCHAIN))]
        for item in self.patches:
            item.start()
        os.environ.pop('CMW_JOBS_ATTEMPT_ID', None)

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def manifest(self, name='gpu-force', **changes):
        data = {'schema': 'vasp-port.binary-manifest.v1', 'name': name, 'status': 'reviewed',
                'executable': {'path': str(self.exe), 'sha256': sha(self.exe), 'bytes': self.exe.stat().st_size},
                'vasp': {'version': '6.6.1', 'variant': 'std'},
                'backend': {'name': 'vasp-metal-backend', 'version': '1.2.3', 'source_commit': 'c' * 40,
                            'source_digest': 'd' * 64, 'source_dirty': True, 'library_sha256': 'e' * 64,
                            'report_schema': 'vmb.rank-report.v1',
                            'aggregator': {'path': str(self.aggregator), 'sha256': sha(self.aggregator)}},
                'build': {'objects': '/private/objects', 'object_count': 321},
                'toolchain': dict(launch.TOOLCHAIN),
                'runtime_dependencies': [{'path': str(self.opt), 'resolved': str(self.cellar),
                                          'sha256': sha(self.cellar)}],
                'selection': {'mode': 'force', 'shadow_check': True}}
        for dotted, value in changes.items():
            target = data
            *parents, leaf = dotted.split('__')
            for key in parents:
                target = target[key]
            target[leaf] = value
        path = self.host / 'private/binary-manifests' / (name + '.json')
        path.write_text(json.dumps(data))
        path.chmod(0o600)
        return path

    def plan(self, *extra, name='gpu-force'):
        args = runner.parser().parse_args(['--input', str(self.source), '--output', str(self.output),
                                           '--timeout', '5', '--ranks', '4', '--binary-manifest', name, *extra])
        return runner.plan(args)

    def refused(self, *extra, name='gpu-force'):
        with self.assertRaises(runner.PreflightError) as caught:
            self.plan(*extra, name=name)
        return str(caught.exception)

    def test_selection_binds_executable_and_backend_environment(self):
        self.manifest()
        p = self.plan()
        self.assertEqual(p['binary'], self.exe)
        self.assertEqual(p['command'][-1], str(self.exe))
        env = p['env']
        self.assertEqual({k: v for k, v in env.items() if k.startswith('VMB_')},
                         {'VMB_MODE': 'force', 'VMB_CHECK': '1', 'VMB_EXPECT_WORLD_SIZE': '4',
                          'VMB_TELEMETRY': 'rank', 'VMB_REPORT_DIR': str(self.output / 'vmb-reports'),
                          'VMB_ATTEMPT_ID': p['selection']['attempt']})
        self.assertEqual(p['selection']['attempt_origin'], 'runner')
        self.assertRegex(p['selection']['attempt'], r'run-[0-9a-f]{32}\Z')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            runner.describe(p)
        self.assertIn('EXPERIMENTAL backend 1.2.3', out.getvalue())

    def test_cmw_attempt_identity(self):
        self.manifest()
        with patch.dict(os.environ, {'CMW_JOBS_ATTEMPT_ID': 'a' * 32}):
            p = self.plan()
        self.assertEqual((p['selection']['attempt'], p['selection']['attempt_origin']), ('a' * 32, 'cmw'))
        with patch.dict(os.environ, {'CMW_JOBS_ATTEMPT_ID': '../x'}):
            self.assertIn('Malformed CMW_JOBS_ATTEMPT_ID', self.refused())
        with patch.object(runner.os, 'getpgrp', return_value=1), patch.object(runner.os, 'getpid', return_value=2), \
                patch.object(runner.os, 'getsid', return_value=1), patch.dict(os.environ, {'CMW_JOBS_OWN_SESSION': '1'}):
            self.assertIn('require CMW_JOBS_ATTEMPT_ID', self.refused('--managed-foreground'))

    def test_changed_or_mismatched_identities_refuse(self):
        self.manifest()
        with self.exe.open('ab') as handle:
            handle.write(b'\0')
        self.assertIn('SHA-256 or size differs', self.refused())
        shutil.copy('/usr/bin/true', self.exe)
        cases = {'executable__sha256': '0' * 64, 'vasp__variant': 'gam', 'vasp__version': '6.5.0',
                 'status': 'draft', 'selection__mode': 'turbo', 'selection__shadow_check': 1,
                 'backend__report_schema': 'vmb.rank-report.v0', 'executable__path': str(self.opt),
                 'toolchain__PORT_GCC_VERSION': '99.0.0', 'backend__aggregator__sha256': '0' * 64,
                 'runtime_dependencies': [{'path': str(self.opt), 'resolved': str(self.cellar), 'sha256': '0' * 64}],
                 'name': 'other'}
        for key, value in cases.items():
            with self.subTest(key=key):
                self.manifest(**{key: value})
                self.refused()
        self.manifest()
        self.cellar.write_bytes(b'upgraded library')
        self.assertIn('differs from the binary manifest', self.refused())

    def test_dependency_retargeted_refuses(self):
        self.manifest()
        other = self.root / 'Cellar/libdemo-2.dylib'
        other.write_bytes(b'synthetic library')
        self.opt.unlink()
        self.opt.symlink_to(other)
        self.assertIn('now resolves elsewhere', self.refused())

    def test_manifest_location_and_file_safety(self):
        for name in ('../x', 'a/b', '', '.hidden', 'x' * 65):
            with self.subTest(name=name):
                self.refused(name=name)
        self.assertIn('not installed', self.refused(name='absent'))
        real = self.manifest('real')
        (self.host / 'private/binary-manifests/link.json').symlink_to(real)
        self.refused(name='link')
        real.chmod(0o664)
        self.refused(name='real')
        real.chmod(0o600)
        real.write_text('{"schema": NaN}')
        self.assertIn('Malformed binary manifest', self.refused(name='real'))

    def test_variant_and_suspension_scope(self):
        self.manifest()
        self.assertIn('variant differs', self.refused('--binary', 'ncl'))
        self.assertIn('not qualified for controlled suspension',
                      self.refused('--dry-run', '--managed-foreground', '--controlled-suspension', '--execution-budget', '4'))

    def test_stock_route_unchanged(self):
        with patch.object(runner, 'binary_identity', return_value=(Path('/usr/bin/true'), 'stock')) as stock:
            args = runner.parser().parse_args(['--input', str(self.source), '--output', str(self.output),
                                               '--timeout', '5'])
            p = runner.plan(args)
        stock.assert_called_once_with('std')
        self.assertIsNone(p['selection'])
        self.assertEqual(p['env'].get('VMB_REPORT'), '/tmp/inherited')  # stock environment untouched

    def test_metadata_records_selection_and_evidence(self):
        self.manifest()
        p = self.plan()

        def fake_supervise(command, timeout, **kwargs):
            self.assertTrue((self.output / 'vmb-reports').is_dir())
            self.assertEqual(kwargs['env']['VMB_REPORT_DIR'], str(self.output / 'vmb-reports'))
            return dict(status=0, child_status=0, reason='completed', advance_stop='disabled',
                        start_utc=datetime.now(timezone.utc).isoformat())
        with patch.object(launch, 'supervise', side_effect=fake_supervise), \
                patch.object(runner, 'git_identity', return_value='synthetic test'), \
                contextlib.redirect_stdout(io.StringIO()):
            # No OUTCAR, so the VASP version is unverified (65); selection evidence is still recorded.
            self.assertEqual(runner.execute(p), 65)
        lines = (self.output / 'RUN_METADATA.txt').read_text().splitlines()
        keys = [line.partition(': ')[0] for line in lines]
        running = keys.index('state', 1)
        for key in ('binary_selection', 'binary_manifest', 'backend', 'backend_mode', 'backend_check',
                    'backend_attempt_id', 'backend_report_dir'):
            self.assertLess(keys.index(key), running, key)
        for key in ('backend_evidence', 'backend_evidence_status', 'backend_summary'):
            self.assertGreater(keys.index(key), running, key)
        meta = dict(line.split(': ', 1) for line in lines)
        self.assertEqual(meta['binary'], str(self.exe))
        self.assertEqual(meta['backend_evidence_status'], 'COMPLETE')
        self.assertEqual(json.loads(meta['backend_summary'])['consumed'], 3)
        self.assertEqual(meta['backend_mode'], 'force')

    def test_aggregation_failure_is_recorded_not_hidden(self):
        self.manifest()
        p = self.plan()
        self.aggregator.write_text('raise SystemExit(1)\n')  # changed after selection
        with patch.object(launch, 'supervise', return_value=dict(
                status=0, child_status=0, reason='completed', advance_stop='disabled',
                start_utc=datetime.now(timezone.utc).isoformat())), \
                patch.object(runner, 'git_identity', return_value='synthetic test'), \
                contextlib.redirect_stdout(io.StringIO()):
            status = runner.execute(p)
        self.assertEqual(status, 1)  # pinned file changed before launch: launch refused, directory kept
        self.assertIn('changed before launch', (self.output / 'RUN_METADATA.txt').read_text())


    def launch_after(self, change):
        """Plan, apply a change between preflight and launch, and attempt execution."""
        self.manifest()
        p = self.plan()
        change()
        launched = []

        def fake_supervise(command, timeout, **kwargs):
            launched.append(command)
            return dict(status=0, child_status=0, reason='completed', advance_stop='disabled',
                        start_utc=datetime.now(timezone.utc).isoformat())
        with patch.object(launch, 'supervise', side_effect=fake_supervise), \
                patch.object(runner, 'git_identity', return_value='synthetic test'), \
                contextlib.redirect_stdout(io.StringIO()):
            status = runner.execute(p)
        return status, launched, (self.output / 'RUN_METADATA.txt').read_text()

    def test_prelaunch_detects_manifest_rewrite_with_preserved_stat(self):
        path = self.host / 'private/binary-manifests/gpu-force.json'

        def rewrite():
            info = path.stat()
            text = path.read_text()
            path.write_text(text.replace('"shadow_check": true', '"shadow_check": 1   '))
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
            self.assertEqual((path.stat().st_size, path.stat().st_mtime_ns), (info.st_size, info.st_mtime_ns))
        status, launched, metadata = self.launch_after(rewrite)
        self.assertEqual((status, launched), (1, []))
        self.assertIn('changed before launch', metadata)

    def test_prelaunch_detects_dependency_retarget(self):
        def retarget():
            twin = self.root / 'Cellar/libdemo-twin.dylib'
            twin.write_bytes(self.cellar.read_bytes())  # identical bytes, different file
            self.opt.unlink()
            self.opt.symlink_to(twin)
        status, launched, metadata = self.launch_after(retarget)
        self.assertEqual((status, launched), (1, []))
        self.assertIn('changed before launch', metadata)

if __name__ == '__main__':
    unittest.main()
