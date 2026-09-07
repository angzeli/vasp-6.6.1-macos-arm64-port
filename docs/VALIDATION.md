# Validation contract

All calculations live under ignored `private/validation/`. The scripts refuse to overwrite an existing case directory. Raw outputs and licensed POTCAR files never enter Git. Tables under `validation/reports/` contain numerical summaries only. A return code of zero is insufficient: validation also requires release identity, SCF convergence, normal timing footer, finite energy, electron count, force and stress arrays.

The core silicon fixtures are read from the existing authorized VASP 5.4.4 installation. The std fixture is unchanged across 1/2/4/8 ranks; the energy spread tolerance is 1e-6 eV per cell and electron counts must agree. The gamma comparison uses the same gamma-point inputs in std and gam with a 1e-6 eV energy tolerance. The ncl case activates SOC in the existing small noncollinear fixture.

After the core gates, run the bounded capability phases:

```sh
python3 scripts/validate-capabilities.py methods
python3 scripts/validate-capabilities.py hybrids
python3 scripts/validate-capabilities.py derivatives
```

These phases compare PBE, SCAN, r2SCAN and r2SCAN+rVV10 on identical silicon geometry and sampling; check resolved functional parameters and nonidentical energy trajectories; compare HSE06 with ACE disabled/enabled; and parse finite optional-point eigenvalues. The HSE ACE energy tolerance is 1e-5 eV per cell. HSE06 uses 25% screened PBE exchange with screening 0.2 inverse Angstrom and the supported Davidson algorithm for ACE. The optional-point case retains a regular SCF mesh and uses `NCORE=1`.

The r2SCAN+rVV10 route explicitly selects the modern nonlocal kernel with `IVDW_NL=2`, `BPARAM=11.95`, `CPARAM=0.0093`, and aspherical PAW corrections. These are public input settings, not a numerical correctness guarantee. [VASP nonlocal functional documentation](https://vasp.at/wiki/Nonlocal_vdW-DF_functionals), [ACE documentation](https://vasp.at/wiki/LFOCKACE), [optional k points](https://vasp.at/wiki/KPOINTS_OPT)

Derivative checks use a silicon atom displaced by 0.04 Angstrom from the original symmetric structure, `ENCUT=700 eV`, fixed 48/96 FFT grids, disabled symmetry, and electronic convergence of 1e-9 eV. They differentiate **free energy (TOTEN)** consistently with the finite-smearing force/stress outputs. Two central-difference steps are used for each observable:

- Force: F_x = −[E(x+h)−E(x−h)]/(2h), with h = 0.01 and 0.005 Angstrom. Acceptance: absolute error ≤0.003 eV/Angstrom.
- Stress: sigma_xx = −[E(+epsilon)−E(−epsilon)]/(2 epsilon V), with epsilon = 0.001 and 0.0005 and fixed fractional positions. Convert eV/Angstrom³ to kbar with 1602.1766208. Acceptance: absolute error ≤0.5 kbar. VASP uses positive stress for compression. [Stress convention](https://vasp.at/wiki/ISIF)

Both r2SCAN and the combined method must pass both observables at the tested steps. Passing these small tests does not establish convergence for ZnIn2S4, arbitrary potentials, all six stress components, or phonon accuracy. Failed checks remain failures; thresholds must not be loosened to obtain a pass.

Only after the generic gates pass, the beta comparison uses existing production references as read-only inputs. Native VASP 5.4.4 and 6.6.1 PBE-D3(BJ) calculations share the same seven-atom POSCAR, POTCAR, 500 eV cutoff, 12×12×4 mesh, 40 bands, and functional definition. Only bounded parallelization/output controls are made explicit. A private VASP-6 PBE WAVECAR can seed the HSE timing cases. The historical approximately 25465-second VASP-5 HSE iteration is a user-provided reference, not a fresh matched benchmark.

`scripts/benchmark.py` has separate `pbe`, `damped`, `ace`, and `preflight` phases. HSE timing cases allow at most two electronic iterations and 1200 seconds each. They are not SCF convergence tests. The beta optional-point preflight is explicitly reduced to a 3×3×2 regular mesh and three samples on each of the nine Stage 04 path segments, retaining topology and reciprocal coordinates. It is not the full Stage 05 workload or a converged band-gap calculation. Limits and any incomplete runs must be retained in the final report.

After a completed optional-path case, run `python3 scripts/check-kpoints-opt.py PRIVATE_CASE_DIRECTORY`. It expands the requested reciprocal line segments, compares the ordered output coordinates modulo reciprocal-lattice translations, checks the expected number of finite band energies, and verifies that the optional driver followed the regular SCF summary. Coordinate tolerance is 1e-6 in reciprocal fractional units. This validates path topology and output structure, not k-point convergence or the accuracy of a densely sampled gap.

HDF5 remains **NOT BUILT / NOT TESTED**. There is no production relaxation, EOS, pressure-enthalpy, phonon, or full Stage 05 campaign in this validation task.
