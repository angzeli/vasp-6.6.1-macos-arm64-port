# VASP 6.6.1 macOS ARM64 Build and Validation

## Verdict

**B — WORKING PORT WITH CAVEATS. Confidence: HIGH for the tested native core and small-fixture capabilities.**

All three executables compiled without source patches and passed their requested native runtime gates. The 1/2/4/8-rank standard calculations agree. HSE06, ACE, KPOINTS_OPT, SCAN, r2SCAN, r2SCAN+rVV10 and SOC have runtime evidence. Both r2SCAN methods passed the bounded force/stress derivative tests. Ordinary OpenMPI launch fails in PRRTE/hwloc on this host; the explicitly tested synthetic-topology mode works. HDF5 and other optional interfaces remain disabled.

The matched beta PBE-D3(BJ) comparison passes across the two native releases. A reduced beta HSE/ACE regular mesh converged, followed by the complete retained nine-segment optional-path topology. The dense 12×12×4 HSE timing cases both hit their 20-minute job caps before completing an electronic iteration. Full-mesh HSE convergence, production band sampling and a speedup against the historical VASP-5 reference therefore remain unvalidated.

This is local validation, not a claim that every VASP feature, material, potential, relaxation, EOS or phonon workflow is certified. The full WP1 Stage 05 production calculation was not launched.

## Build identity and preservation

| Item | Recorded value |
|---|---|
| Release | Source and executable identify VASP 6.6.1; source release date 17 July 2026 |
| Licensed upstream | `/Applications/Academic/vasp.6.6.1` |
| External port | `/Users/liangze/Desktop/squiddy tools/vasp-6.6.1-macos-arm64-port` |
| Build/validation date | 7 September 2026 |
| Host | Apple M3 Max; arm64; macOS 26.3, build 25D125; 36 GiB memory; 14 physical cores |
| GNU C/C++/Fortran | GCC 16.1.0, explicitly selected under `/opt/homebrew/Cellar/gcc/16.1.0` |
| MPI | Homebrew OpenMPI 5.0.9, explicitly selected under `/opt/homebrew/Cellar/open-mpi/5.0.9` |
| Math | OpenBLAS 0.3.34, ScaLAPACK 2.2.3, FFTW 3.3.11 |
| Build policy | Two compile jobs; current-release GNU template requirements; no experimental CPU tuning |
| Disabled | HDF5/MPI-IO, OpenMP, GPU, Libxc, Wannier90, qd and optional external interfaces |

The MPI wrapper's resolved Fortran command was verified as GCC 16. The shell-default GCC 14/user-prefix MPI 4 installation was not used. Each binary's recursive dependency inspection covered 18 native images with identical non-system library closures, no unresolved dependencies and no x86-only image. Linkage includes the selected MPI, GNU Fortran/C++ runtimes, ScaLAPACK, OpenBLAS and FFTW. Homebrew install names use `opt` symlinks; retaining the recorded dependency versions matters for reproducibility.

The upstream build-input fingerprint matches before and after compilation. Its `bin/` and `build/` remain empty, and no upstream configuration was created. Source staging, generated source, objects, raw logs, copied potentials and calculations exist only in ignored private/build directories. No source edit or VASP-5 patch was applied. Exact official archive provenance was not independently authenticated.

Compiler warnings were retained, principally legacy argument/rank diagnostics accepted by the current GNU compatibility option. Warning-line counts were 1047/1151/967 for std/gam/ncl; these are not warning-free build claims. Private logs retain the evidence without exposing licensed source excerpts in this report.

## Executables

All binary paths below are relative to the external port root.

| Executable | Compile | arm64 | Runtime | Verdict |
|---|---|---|---|---|
| `macos-arm64/bin/vasp_std` | PASS, 247 s | Native Mach-O | PBE at 1/2/4/8 ranks; advanced tests | PASS |
| `macos-arm64/bin/vasp_gam` | PASS, 241 s | Native Mach-O | Gamma-only PBE; agrees with std | PASS |
| `macos-arm64/bin/vasp_ncl` | PASS, 242 s | Native Mach-O | Two-rank SOC/noncollinear smoke | PASS |

| Executable | SHA-256 |
|---|---|
| std | `4d147f16d515b1c6000b1053cfe5b234a63fb29789bb051346dc9019d59567db` |
| gam | `da18877ed6b287282b13b84ec805d68cebd6c1f39b6c3e147a6f07434bfbc1cb` |
| ncl | `61b06973424d6eb6410e4ab137af0242c076b84190db46595edc9362200a0b40` |

## Core MPI and PBE results

The unchanged two-atom silicon fixture used a 2×2×2 mesh and 300 eV cutoff. Every case identified 6.6.1, converged in 12 electronic steps with 8 electrons, returned zero, produced the normal timing footer, and had finite energy, forces and stress. No NaN/Infinity or dynamic-library failure was found.

| Ranks | Energy, eV/cell | VASP elapsed, s | Launcher walltime, s | Result |
|---:|---:|---:|---:|---|
| 1 | −8.28298469 | 0.217 | 0.993 | PASS |
| 2 | −8.28298469 | 0.142 | 0.295 | PASS |
| 4 | −8.28298469 | 0.118 | 0.286 | PASS |
| 8 | −8.28298469 | 0.159 | 0.346 | PASS |

The energy spread is zero at the recorded precision, within the 1e-6 eV/cell tolerance. These subsecond tests do not provide a useful performance scaling benchmark.

For the separate Gamma-only fixture, std and gam both returned **6.18461832 eV**. The ncl SOC case returned **6.18436875 eV**, with normal convergence and explicitly enabled SOC. These deliberately tiny, coarse-sampling fixtures establish execution/equivalence, not physical convergence of bulk silicon.

Ordinary two-rank launch reproduced the `prte_hwloc_base_get_topo_signature` crash before VASP ran. The synthetic `Package:1 Core:14 PU:1` mode with no binding and slot mapping passed. The launcher derives the core count rather than hard-coding 14, limits ranks to 1–8, pins the MPI executable, and uses one OpenBLAS/OpenMP thread per rank. Its timeout test returned 124 and its nonzero-exit test preserved status 7. It never automatically retries a scientific calculation.

## Capability matrix

“CONFIRMED” means the stated bounded runtime behavior was observed, not universal production certification.

| Capability | Result | Evidence | Limitation |
|---|---|---|---|
| PBE | CONFIRMED | Core rank tests; separate method control | Material convergence remains application-specific |
| HSE06 | CONFIRMED | Resolved exact-exchange settings, converged small HSE calculation | Dense beta results are separately reported below |
| ACE | CONFIRMED | Resolved on/off states; matching converged HSE energies | No general speedup claim from a small fixture |
| KPOINTS_OPT | CONFIRMED | Generic four-point case and beta nine-segment case; ordered coordinates and finite eigenvalues verified after regular SCF | Requires std/ncl; hybrid tests use NCORE=1; beta sampling is reduced |
| SCAN | CONFIRMED | Runtime selection and distinct converged numerical trajectory | No SCAN derivative suite in this task |
| r2SCAN | CONFIRMED | Runtime R2SCAN XC table and functional components; distinct PBE/SCAN trajectories; derivative checks pass | Only the tested silicon fixture/component coverage |
| r2SCAN+rVV10 | CONFIRMED | Runtime R2SCAN plus rVV10 kernel 2 and resolved parameters; derivative checks pass | No ZnIn2S4 relaxation/EOS/phonon certification |
| SOC/noncollinear | CONFIRMED | Native ncl binary and existing SOC fixture pass | No expensive ZnIn2S4 SOC calculation |
| HDF5 | NOT BUILT / NOT TESTED | Explicitly disabled in configuration | Required Fortran dependency was not supplied |

The 400 eV silicon identity controls converged as follows:

| Method | Energy, eV/cell | Iterations | Launcher walltime, s |
|---|---:|---:|---:|
| PBE | −8.28987443 | 14 | 0.987 |
| SCAN | −17.47803986 | 14 | 3.023 |
| r2SCAN | −14.98210208 | 15 | 2.817 |
| r2SCAN+rVV10 | −14.81563716 | 14 | 12.472 |

The r2SCAN result is supported by resolved runtime XC information and a different numerical trajectory, not merely an accepted INCAR tag. The old VASP-5 silent-PBE fallback is excluded on this fixture. For the combined method, the runtime identifies the modern rVV10 kernel, `BPARAM=11.95` and `CPARAM=0.0093`. Absolute energies across different functionals are identity diagnostics here, not a ranking of methods. [Official nonlocal functional settings](https://vasp.at/wiki/Nonlocal_vdW-DF_functionals)

HSE06 with ACE disabled/enabled converged in 28 iterations to **−10.24360022 eV** in both cases. Launcher walltimes were **7.320 s / 5.018 s** (about 1.46× for this tiny cold-start comparison). The four-point optional-path case took 5.972 s and preserved the same regular-mesh energy. Its optional driver started only after the regular SCF summary, and its two batches converged before normal termination. [ACE algorithm scope](https://vasp.at/wiki/LFOCKACE), [optional-point workflow](https://vasp.at/wiki/KPOINTS_OPT)

## Force and stress finite differences

All 18 displaced/strained calculations converged normally. Tests used 700 eV, fixed 48/96 FFT grids, EDIFF=1e-9 eV, a 0.04 Å initial displacement, and no symmetry. The differentiated energy is TOTEN/free energy, consistent with finite smearing. Force is minus the displacement derivative. Stress is minus the fixed-fractional-coordinate strain derivative divided by the unstrained volume, with **1602.1766208 kbar per eV/Å³**. [VASP stress convention](https://vasp.at/wiki/ISIF)

| Method | Observable | Step | Analytic | Finite difference | Absolute error | Result |
|---|---|---:|---:|---:|---:|---|
| r2SCAN | F_x, eV/Å | 0.010 Å | −0.7285598 | −0.7282620 | 0.0002978 | PASS |
| r2SCAN | F_x, eV/Å | 0.005 Å | −0.7285598 | −0.7282890 | 0.0002708 | PASS |
| r2SCAN | sigma_xx, kbar | 0.0010 | 83.4425652 | 83.3652579 | 0.0773073 | PASS |
| r2SCAN | sigma_xx, kbar | 0.0005 | 83.4425652 | 83.3620556 | 0.0805096 | PASS |
| r2SCAN+rVV10 | F_x, eV/Å | 0.010 Å | −0.7269871 | −0.7266880 | 0.0002991 | PASS |
| r2SCAN+rVV10 | F_x, eV/Å | 0.005 Å | −0.7269871 | −0.7267150 | 0.0002721 | PASS |
| r2SCAN+rVV10 | sigma_xx, kbar | 0.0010 | 78.4352171 | 78.3602762 | 0.0749408 | PASS |
| r2SCAN+rVV10 | sigma_xx, kbar | 0.0005 | 78.4352171 | 78.3568738 | 0.0783432 | PASS |

The predeclared tolerances were **0.003 eV/Å** and **0.5 kbar**; they were not relaxed. Both step sizes pass. These checks cover one displaced coordinate and one normal-strain component on one potential/structure. They do not certify all stress components, arbitrary chemical environments, production cutoff/k-point convergence, or phonons.

## Beta ZnIn2S4 comparison and HSE preflight

### Matched PBE-D3(BJ) calculation

Both current native installations were run afresh on identical seven-atom beta ZnIn2S4 inputs: one formula unit, S4/In2/Zn1 ordering, 62 electrons, 500 eV, Gamma-centered 12×12×4 regular mesh (69 irreducible points), 40 bands, 8 MPI ranks, NCORE=1 and KPAR=1. The resolved GGA, D3(BJ) correction (IVDW=12), smearing, spin and symmetry settings agree; both report six space-group operations. POSCAR/POTCAR/KPOINTS identity was checked locally without putting potential content or hashes in Git. Output-file controls were reduced, with a VASP-6 WAVECAR retained privately for the matched HSE starts.

| Quantity | Native 5.4.4 | Native 6.6.1 | Comparison |
|---|---:|---:|---|
| Free energy, eV/f.u. | −28.75501253 | −28.75501261 | Absolute difference 8.0×10⁻⁸ eV/f.u.; PASS |
| Electrons | 62 | 62 | Identical |
| SCF iterations | 16 | 16 | Both converged normally |
| Launcher walltime, s | 50.467 | 52.069 | Single runs; no performance claim |
| Sampled regular-mesh gap, eV | 0.3029 | 0.3029 | PASS; not a full-path gap |
| Mean pressure, kbar | 0.08951928 | 0.09391928 | Difference 0.00440000 kbar; PASS |

Maximum force-component and stress-component differences were **1.549×10⁻⁵ eV/Å** and **0.00443723 kbar**. Acceptance limits were 1e-4 eV/f.u. for energy, 0.001 eV for the sampled gap, 0.001 eV/Å for forces and 0.1 kbar for stress. All comparisons passed. The older stored Linux reference was not substituted for a fresh native 5.4.4 run.

### Dense-mesh HSE timing limits

The user's historical VASP-5 beta reference is approximately **25,465 s (7.07 h) for its first HSE electronic iteration**. That is a user-provided observation, not a new matched timing measured here.

The two clean VASP-6 timing cases used the same beta structure, potential, 500 eV cutoff, 12×12×4 mesh, 40 bands and HSE06 definition. Each read an identical copy of the converged VASP-6 PBE WAVECAR. Both used 8 ranks, NCORE=1, KPAR=1 and PRECFOCK=Normal. The first used ALGO=Damped, TIME=0.4 and ACE off; the second used ALGO=Normal and ACE on. NELM/NELMIN were limited to two steps, with NELMDL=0 and a separate 1200-second job limit.

| Case | Launcher walltime | Completed electronic iterations | Exit | Interpretation |
|---|---:|---:|---:|---|
| Conservative Damped, ACE off | 1200.082 s | 0 | 124 | Reached wall limit before the first iteration completed |
| Normal, ACE on | 1200.085 s | 0 | 124 | Reached wall limit before the first iteration completed |

**No dense-mesh time per completed electronic iteration, converged HSE energy, or speedup ratio can be reported.** A job cap includes startup and is not an iteration duration. In particular, dividing 25,465 by 1200 would give an unsupported speedup claim. The small-fixture ACE comparison above remains valid only for that fixture.

Sampled sums of resident memory across eight ranks were about **2984 MiB** for Damped and **2472 MiB** for ACE, with roughly 797%/791% aggregate CPU use. These snapshots are neither peak measurements nor unique physical-memory totals. Two one-second ACE rank samples showed exact-exchange/FFTW work in one rank and MPI reduction/progress in another. This supports compute/communication activity during the bounded observation, without proving dense-mesh convergence or excluding every communication problem. Both capped jobs were terminated, and their ranks were cleared before proceeding.

One earlier 59.222-second Damped launch was interrupted after discovering that a comparison reader treated VASP-5/6 XML parameter placement as identical. The outputs were retained as `beta-hse-damped-aborted-comparison-reader` and excluded from timings. The reader was corrected to check resolved OUTCAR settings, the completed PBE comparison passed, and the clean independent timing cases above were then run. No scientific outputs were edited or rerun to conceal this control error.

### Reduced beta HSE and optional-path preflight

**PASS.** This deliberately small preflight retained the beta structure, potential and 500 eV cutoff, while reducing the regular mesh to **3×3×2 (six irreducible points)**. It used 8 ranks, 40 bands, NCORE=1, KPAR=1, ALGO=Normal and ACE. Runtime parameters confirm 25% exact exchange, screening 0.2 Å⁻¹ and ACE enabled. A cold-start HSE SCF converged at EDIFF=1e-6 eV in **18 iterations**, with 62 electrons and regular-mesh free energy **−32.42338382 eV/f.u.** Forces and stress were finite; the maximum force component was 0.36525266 eV/Å. This is an electronic convergence check, not a relaxed HSE structure.

Only after the regular SCF summary did the optional-point driver begin. All Stage 04 line-segment endpoints and labels were retained unchanged: **Γ–M, M–K, K–Γ, Γ–A, A–L, L–H, H–A, L–M and H–K**. Sampling was reduced from 40 to three points per segment, giving **27 points × 40 bands = 1080 finite eigenvalues**. The ordered output coordinates agree with the requested reciprocal path modulo lattice translations, with maximum residual **3.35×10⁻⁹**, below the 1e-6 tolerance. No manually combined weighted-plus-zero-weight list was needed.

All five optional batches converged in nine steps each; final absolute energy changes were 6.7373e-7, 6.7424e-7, 3.9305e-7, 4.6821e-7 and 2.4653e-7 eV. The output was parseable and the calculation terminated normally. Launcher walltime was **1122.456 s (18.71 min)**; the VASP elapsed field was 1122.13 s. The first four regular SCF warmup loops took 0.184–0.280 s. The subsequent HSE loops, steps 5–18, took **17.8904–19.2793 s**, with median **17.9718 s**. These timings are for the reduced mesh and cannot establish a speedup over the historical dense-mesh iteration.

A preflight snapshot summed to **1770 MiB RSS** and 791.6% CPU across eight ranks; it is not a peak-memory measurement. No task VASP ranks remained after completion. The preflight validates the sequencing, path topology and output handling. It does not establish the production 12×12×4 SCF convergence, the original 40-sample-per-segment band path, or a converged HSE gap.

### WP1 Stage 05 decision

- **HSE SCF:** the port is operational on the generic fixture and reduced beta mesh. It is recommended for a controlled Stage 05 migration/validation trial. Immediate replacement of the production calculation at its original mesh is **not yet approved by this evidence**; its convergence and practical cost remain unresolved.
- **HSE bands via KPOINTS_OPT:** the workflow works on the generic and reduced beta tests and is the supported replacement route for the VASP-5 manually weighted path construction. The exact Stage 04 topology is preserved. Full regular-mesh and path-sampling convergence must be established before treating its bands/gap as production results.

**Recommended next action, not executed:** create a separate private Stage 05 validation case using these recorded binaries and launcher. Allow a measured HSE iteration on the target regular mesh under an explicit larger wall budget, then assess convergence and cost before a full SCF. Once the target regular mesh is converged, evaluate and converge the optional path sampling with NCORE=1. Retain the current WP1 production files unchanged until those gates pass. No full Stage 05 production workflow was launched in this task.

## Operational limits and repository boundary

The practical launch caveat is the host's PRRTE/hwloc topology failure; use the verified explicit synthetic mode. The old shell-default MPI 4 and GCC 14 chain remains untouched and must not be selected for this port. HDF5, GW/qd-related workflows, VASP OpenMP and accelerator paths are not validated. VASP OpenMP compilation is disabled; a math-library dependency nevertheless links the native `libomp` runtime, with library threads limited by the launcher. Compiler warnings remain available privately for future feature-specific diagnosis.

During the original build/validation task, all source handling was local. The upstream tree, VASP 5 installation and WP1 production inputs/outputs were not modified. No dependency installation/upgrade, global shell edit, source patch, remote repository creation or push was performed. Git contains only independently authored configuration, scripts, documentation and permitted numerical/provenance metadata. It excludes VASP source, binaries, potentials, objects, private staging and heavy runtime files.

The original build, generic runtime and documentation/evidence commits are `76ae6fb`, `de2c6f3` and `20f48c1`. That build/validation task ended without a remote or push. The separately authorized repository connection is described in [the port history](docs/PORTING_HISTORY.md); it does not change or rerun the scientific validation reported here.

Build instructions and test definitions are in `docs/BUILD.md` and `docs/VALIDATION.md`; numerical tables are under `validation/reports/`; executable identities and linkage records are under `provenance/`. Raw evidence remains under ignored `private/` and `macos-arm64/build/`.
