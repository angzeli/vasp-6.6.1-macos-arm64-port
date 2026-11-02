"""Synthetic CHGCAR restart contracts; no licensed data or VASP execution."""
import io
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import run_vasp as runner

POSCAR = 'synthetic\n1\n5 0 0\n0 5 0\n0 0 5\nH\n6\nDirect\n' + '0 0 0\n' * 6
AUG = ''.join(f'augmentation occupancies {i} 1\n0.0\n' for i in range(1, 7))
CHARGE = '\n2 1 1\n6.0 6.0\n' + AUG
SPIN = '2 1 1\n1.0 -1.0\n' + AUG
MOMENTS = '0.0 0.0 0.0 0.0 1.0\n0.0\n'


class ChgcarTests(unittest.TestCase):
    def check(self, body, spin=2, electrons=6):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'CHGCAR'
            path.write_text(POSCAR + body)
            original = path.read_bytes()
            target = runner.structure(io.StringIO(POSCAR))
            result = runner.charge_header(path, target, electrons, spin)
            self.assertEqual(path.read_bytes(), original)
            return result

    def test_native_atomic_moments_and_legacy_no_moments(self):
        for moments in (MOMENTS, '', MOMENTS.replace('0.0', '0.0D+00')):
            with self.subTest(moments=moments):
                self.assertIn('2 density blocks', self.check(CHARGE + moments + SPIN))

    def test_nonmagnetic_unchanged(self):
        self.assertIn('1 density blocks', self.check(CHARGE, spin=1))

    def test_invalid_atomic_moments(self):
        for moments in ('0.0\n', MOMENTS + '0.0\n', MOMENTS * 2,
                        MOMENTS.replace('1.0', 'nan'), MOMENTS.replace('1.0', 'inf'),
                        MOMENTS.replace('1.0', 'garbage')):
            with self.subTest(moments=moments), self.assertRaises(runner.PreflightError):
                self.check(CHARGE + moments + SPIN)
        with self.assertRaises(runner.PreflightError):
            self.check(CHARGE + '0.0\n')

    def test_atomic_moment_placement(self):
        for body, spin in ((MOMENTS + CHARGE + SPIN, 2),
                           (CHARGE + SPIN + MOMENTS, 2), (CHARGE + MOMENTS, 1)):
            with self.subTest(body=body), self.assertRaises(runner.PreflightError):
                self.check(body, spin=spin)

    def test_grid_and_density_guards(self):
        for tail in ('', SPIN.replace('2 1 1', '3 1 1'),
                     SPIN.replace('1.0 -1.0', '1.0'), SPIN + SPIN,
                     SPIN.replace('1.0 -1.0', 'nan -1.0')):
            with self.subTest(tail=tail), self.assertRaises(runner.PreflightError):
                self.check(CHARGE + MOMENTS + tail)

    def test_augmentation_guards(self):
        for charge in (CHARGE.replace('augmentation occupancies 6 1\n0.0\n', ''),
                       CHARGE.replace('occupancies 6 1', 'occupancies 5 1'),
                       CHARGE.replace('occupancies 6 1\n0.0', 'occupancies 6 2\n0.0')):
            with self.subTest(charge=charge), self.assertRaises(runner.PreflightError):
                self.check(charge + MOMENTS + SPIN)

    def test_electron_integral_guard(self):
        with self.assertRaises(runner.PreflightError):
            self.check(CHARGE + MOMENTS + SPIN, electrons=7)


if __name__ == '__main__':
    unittest.main()
