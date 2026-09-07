# Local launcher validation

Date: 2026-09-07. **PASS for the bounded launcher contract on this Mac.**
Implementation remained uncommitted working-tree changes against
`4c3811dc6c57f14d3b74f7fd7af5bd34515d63bf`.

## Scope and environment

The public `scripts/run-vasp.sh` used the existing native Mach-O arm64 VASP 6.6.1
std/gam/ncl binaries, pinned Homebrew OpenMPI 5.0.9, synthetic topology and one
library thread per rank on the M3 Max. There was no rebuild, dependency change,
licensed-source patch, installation, production calculation or remote operation.
Tests were sequential and limited to the existing two-atom silicon fixtures.

Private inputs/results are under
`private/launcher-tests/real-20260907-180140/`; raw files and fingerprints remain
ignored. Original PBE/Gamma/SOC fixtures came from the VASP-5 installation's existing
validation directory; these are input precedents only. Matched VASP-6 PBE comparison
used `private/validation/std-pbe-r1`, with the same 300 eV / Normal numerical inputs.
The 400 eV / Accurate tiny HSE fixture came from `private/validation/hse-kpoints-opt`.
No energy comparison mixed those numerical settings.

## Deterministic tests

`python3 -B -m unittest discover -s tests -v`: **15 tests passed in 3.351 seconds**.
No VASP was executed by this suite. Covered contracts:

- CLI help, mandatory positive real-run budgets and file-free dry-run;
- spaces, aliases/nesting/protected paths, existing outputs and exclusive ownership;
- missing/empty inputs, auxiliary basename and reserved-file restrictions;
- INCAR case/comments/semicolons/continuations, duplicate resolution, NPAR removal,
  preservation of unrelated science and parallel divisibility;
- restart-policy conflicts and donor overlap;
- Gamma/SOC/active optional-point guards and disabled LKPOINTS_OPT;
- real independent staging, metadata, no accidental old-output/restart inheritance;
- unassessed incomplete output, detected WAVECAR fallback, NELM checkpoint reporting;
- static LABORT, ionic LSTOP and preservation of an existing STOPCAR;
- timeout, SIGINT and SIGTERM through synthetic descendants, bounded escalation,
  child status, unrelated-process survival and exit-code 7 preservation;
- compatibility of the low-level launcher CLI and its existing defaults.

The final assertions exercise the actual staging/supervisor code; public arbitrary
program execution was not added for testing. Temporary synthetic directories were
removed by the tests. Signal/timeout failure cases used synthetic processes.

## Real Si2 calculations

All final cases below exited normally with actual version 6.6.1, NELECT=8 and finite
energy/force/stress output. Electronic convergence was confirmed for the ordinary
static SCF cases. Frozen-density and checkpoint cases have separate statuses.
Each real launch had a 60-second hard budget, except HSE optional points at 120 s.
Total owned execution wall time, including the initial failed validation case,
was **71.918 seconds** (15 real launches). No cap was extended.

| Case | Ranks / controls | Energy (eV/cell) | Electronic steps | VASP elapsed (s) | Result |
| --- | --- | ---: | ---: | ---: | --- |
| PBE baseline | 1; NCORE=1, KPAR=1 | -8.28298469 | 12 | 0.483 | Matched reference within 1e-6 eV |
| PBE MPI | 8; NCORE=1, KPAR=1 | -8.28298469 | 12 | 20.949 | Matched reference within 1e-6 eV |
| Non-default NCORE | 8; NCORE=2, KPAR=1 | -8.28298469 | 12 | 18.594 | Actual OUTCAR band decomposition verified |
| Non-default KPAR | 8; NCORE=1, KPAR=2 | -8.28298469 | 12 | 7.771 | Actual OUTCAR two-group k-point decomposition verified |
| Gamma std | 2 | 6.18461832 | 12 | 0.334 | Agrees with gam within 1e-6 eV |
| Gamma gam | 2; selected gam executable | 6.18461832 | 12 | 0.274 | Gamma equivalence passed |
| SOC ncl | 2; selected ncl executable | 6.18436875 | 12 | 0.755 | LSORBIT resolved true |
| Fresh checkpoint donor | 2; private LWAVE/LCHARG enabled explicitly | -8.28298469 | 12 | 0.397 | Nonempty WAVECAR/CHGCAR produced |
| WAVECAR restart | 2; ISTART=1, ICHARG=0 | -8.28298468 | 2 | 0.264 | Runtime WAVECAR accepted |
| CHGCAR restart | 2; ISTART=0, ICHARG=1 | -8.28298467 | 6 | 0.357 | Runtime CHGCAR accepted |
| Both-file restart | 2; ISTART=1, ICHARG=1 | -8.28298467 | 2 | 0.502 | Both accepted at runtime |
| Fixed charge, changed main mesh | 2; ISTART=0, ICHARG=11 | 6.00253656 | 6 | 0.247 | CHGCAR accepted; SCF convergence NOT ASSESSED |
| Corrected checkpoint test | 1; NELM=1, NELMIN=1 | 3.76635105 | 1 | 0.186 | NOT CONFIRMED; nonempty WAVECAR, validity unassessed |
| HSE06/ACE + KPOINTS_OPT | 2; NCORE=1, KPAR=1 | -10.24360022 | 28 | 15.355 | Hybrid SCF followed by optional-point evaluation |

The three converged restart energies agreed with the fresh donor within
1e-6 eV/cell. Restart copies had different inodes from their donor, and donor
WAVECAR/CHGCAR and relevant inputs remained unchanged. The changed-mesh fixed-charge
energy is not compared with the original mesh energy.

HSE runtime settings showed LHFCALC=true, LFOCKACE=true and HFSCREEN=0.2.
`check-kpoints-opt.py` passed: one segment, four expected points, eight bands,
32 finite optional eigenvalues, maximum reciprocal residual 3.33e-9, and SCF
preceding optional evaluation. This was the tiny Si2 path, not the beta 12×12×4 case.

Separate public preflight calls rejected missing CHGCAR, truncated CHGCAR and a
cell mismatch before output creation. A PBE-donor → HSE-orbital initialization
**dry-run** passed without creating files; that functional change was not itself
run as an additional real restart. The public baseline dry-run also left its
private directory listing unchanged.

## Checkpoint finding and correction

The initial `checkpoint` run exited zero and printed an EDIFF termination footer
with NELM=1 despite large electronic residual changes. The initial metadata
incorrectly said confirmed, causing the test driver to stop. That original case
and metadata were retained untouched as evidence, not approved as convergence.

The runner now refuses positive SCF confirmation when iterations reach the resolved
NELM or an electronic STOPCAR request exists. A deterministic regression test
reproduces the misleading footer condition. A new `checkpoint-fixed` real run
returned process status zero but scientific status NOT CONFIRMED, while writing
WAVECAR. A run converging exactly at NELM is conservatively unconfirmed. The shared
legacy observables reader was not changed; the user-facing runner applies its own
stricter acceptance condition. See [STOPCAR](https://vasp.at/wiki/STOPCAR) for the
limits of electronic-step checkpoint stopping.

## Protection checks and repository boundary

All **27 before/after SHA-256 comparisons passed**: three VASP executables,
12 original std/gam/ncl fixture files, five original HSE fixture files and seven
protected VASP-5/VASP-6 build entrypoint files. The full VASP-6 upstream metadata
snapshot was unchanged across **4,582 files** (relative paths, size, mtime, mode).
This is selected content hashing plus tree metadata comparison, not an exhaustive
content hash of both licensed source trees. Source trees were not used for Git.

Every tested new source input remained unchanged across its invocation. The fresh
donor's selected checkpoints and inputs also passed before/after content checks.
No FYP files, original fixtures or previous validation results were edited.
Synthetic signal tests verified that an unrelated live process survived; cleanup
was scoped to the owned process group, with no global process-killing operation.

Only independent launcher code/tests and Markdown documentation were added;
`launch.py` was refactored compatibly, the repository safety checker permits the
new `tests/` root, and README links were updated. No source, POTCAR, executable,
raw scientific log or sensitive input fingerprint was placed in tracked content.
Nothing was staged, committed, pushed, tagged or released.

## Remaining limits

This establishes launcher behavior and small Si2 numerical agreement on this host,
not ZnIn2S4 scientific acceptance or a production performance recommendation. The
8-rank tiny cases were slower than one rank; no tuning conclusion is implied.
Native MPI, general wavefunction compatibility, SOC restarts, dense hybrids,
ionic completion, and recovery from actual VASP timeout/interruption were not
validated. Signals and STOPCAR callbacks were tested synthetically rather than by
interrupting expensive scientific runs. No resulting checkpoint is certified
usable solely from its existence; ordinary complete restarts were explicitly
accepted and numerically checked in the bounded cases above.

See [the launcher guide](../../docs/LAUNCHER.md) for supported syntax, restart
limits, exact example commands and process-versus-scientific status semantics.
