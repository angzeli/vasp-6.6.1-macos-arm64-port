"""Toolchain version selection: tracked defaults, host-local overrides, strict parsing."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import toolchain


class ToolchainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'config').mkdir()
        (self.root / 'private').mkdir()
        shutil.copy(ROOT / 'config/toolchain-defaults.txt', self.root / 'config/toolchain-defaults.txt')

    def tearDown(self):
        self.temp.cleanup()

    def local(self, text):
        (self.root / 'private/toolchain.env').write_text(text)

    def test_defaults_without_local_file(self):
        values, source = toolchain.load(self.root)
        self.assertEqual(source, 'config/toolchain-defaults.txt')
        self.assertEqual(values, toolchain.read(ROOT / 'config/toolchain-defaults.txt'))

    def test_local_overrides_only_given_keys(self):
        self.local('# host\nPORT_OPENMPI_VERSION=5.0.11\nPORT_PRRTE_VERSION=4.1.0_1\n')
        values, source = toolchain.load(self.root)
        self.assertEqual(source, 'private/toolchain.env')
        self.assertEqual(values['PORT_OPENMPI_VERSION'], '5.0.11')
        self.assertEqual(values['PORT_PRRTE_VERSION'], '4.1.0_1')
        defaults = toolchain.read(ROOT / 'config/toolchain-defaults.txt')
        self.assertEqual(values['PORT_FFTW_VERSION'], defaults['PORT_FFTW_VERSION'])

    def test_rejects_unknown_keys_and_unsafe_values(self):
        for text in ('PORT_UNKNOWN_VERSION=1.0\n', 'PORT_GCC_VERSION=16.2.0; rm -rf /\n',
                     'PORT_GCC_VERSION=$(id)\n', 'PORT_GCC_VERSION=\n', 'PATH=/tmp\n', 'just text\n'):
            with self.subTest(text=text):
                self.local(text)
                with self.assertRaises(ValueError):
                    toolchain.load(self.root)

    def test_shell_exports_are_quoted_and_complete(self):
        out = subprocess.check_output([sys.executable, '-I', '-B', str(ROOT / 'scripts/toolchain.py'), '--shell'], text=True)
        lines = out.splitlines()
        self.assertTrue(all(line.startswith('export PORT_') for line in lines))
        self.assertIn('PORT_TOOLCHAIN_SOURCE', out)
        for key in toolchain.read(ROOT / 'config/toolchain-defaults.txt'):
            self.assertIn(f'export {key}=', out)


if __name__ == '__main__':
    unittest.main()
