# Local calculation launcher

`scripts/run-vasp.sh` stages a new execution directory, checks supported input and
restart contracts, and runs one existing validated VASP executable. It lives only
in this external port repository so licensed upstream source and installations
remain separate. It neither builds VASP nor installs a command globally.

The thin shell entry point loads `scripts/environment.sh` and replaces itself with
`scripts/run_vasp.py` (Python standard library; Python 3.11+). Python imports the
existing `scripts/launch.py`: `mpi_command` owns pinned OpenMPI/synthetic topology
construction and `supervise` owns the MPI session, deadline and cleanup. There is
no nested timeout wrapper. `run-mpi.sh` retains its existing CLI, native default,
600-second default and 1–8-rank range; its shared supervisor now also handles
SIGTERM and surviving descendants. The new public runner requires its own explicit
execution budget and defaults to synthetic MPI.

This is local-only execution. There is no queue, remote submission, daemon, retry,
automatic tuning, arbitrary-program option or in-place resume. A later scheduler
could invoke this CLI; no scheduler integration is implemented here.

## Options

| Option | Contract/default |
| --- | --- |
| `--input PATH` | Required existing scientific-input directory |
| `--output PATH` | Required new execution directory; parent must already exist |
| `--binary std\|gam\|ncl` | `std`; resolves only the recorded binary in this port |
| `--ranks INTEGER` | `1`; supported range 1–8 |
| `--ncore INTEGER`, `--kpar INTEGER` | Explicit override, else unambiguous INCAR value, else 1 |
| `--mpi-mode synthetic\|native` | `synthetic`; native is explicit diagnostics, without fallback |
| `--restart none\|wavecar\|chgcar\|both` | `none`; deliberate restart-file selection |
| `--restart-from PATH` | Defaults to input for a selected restart; invalid with `none` |
| `--timeout SECONDS` | Positive finite execution budget, required for a real launch |
| `--stop-before SECONDS` | `0` (disabled); nonnegative and smaller than timeout |
| `--extra-input BASENAME` | Repeatable, explicitly named regular auxiliary input |
| `--dry-run` | Validate/print the resolved plan; creates no files and starts no MPI/VASP |
| `--help` | CLI help |

Dry-run performs read-only binary identity, file/header and space checks. It may
read substantial CHGCAR data; it is not a scientific correctness check. MPI version
is probed immediately before real staging. Runtime banner identity is checked
after execution, without treating the VASP executable as a version utility.

## Staging and parallel controls

Input and donor directories are read-only. Paths with spaces work when quoted.
Existing output paths, symlink aliases, input/donor overlap, all destinations under
`/Applications/Academic`, and repository destinations outside ignored `private/`
are rejected. Directory creation is exclusive. Once owned, a failed directory is
retained with failure metadata. There is no overwrite/delete option.

Only INCAR, POSCAR, POTCAR, KPOINTS, a present KPOINTS_OPT, explicitly selected
restart files and approved auxiliary basenames are copied. Individual input files
must be regular files, not symlinks. Copies are independent; restart output cannot
write through to a donor. Old outputs, STOPCAR, submission scripts and unselected
restart files are not inherited. CONTCAR is never substituted for POSCAR. Extra
inputs cannot traverse directories or replace reserved inputs/restarts/outputs.
Staging free space is checked; future runtime output volume is not predicted.

The staged INCAR contains exactly one active NCORE and KPAR. Their precedence is
CLI → unambiguous INCAR → 1, recorded with original values. An active NPAR requires
explicit `--ncore`; that override removes active NPAR assignments and is recorded.
Conflicting NCORE/KPAR duplicates need an explicit corresponding override.
Scientific settings are otherwise preserved, including settings sharing a line
with a parallel tag. The original INCAR is never changed.

Supported INCAR syntax is unquoted `tag=value`, case-insensitive tags, whitespace,
`#`/`!` comments, semicolon separators and backslash continuations. Quoted/nested
syntax anywhere in active text and ambiguous duplicate scientific assignments
are rejected. This deliberately small parser does not implement the full VASP
input language; use an ordinary unambiguous input rather than relying on tag order.

Ranks, NCORE and KPAR must be positive, ranks must divide by KPAR, and ranks/KPAR
must divide by NCORE. Multi-image/NEB and additional decomposition controls are
rejected. OpenMP, OpenBLAS and Accelerate library thread counts are fixed to one
through the existing process-local environment. No global environment is changed.
KPAR > 1 produces a method/performance warning; divisibility is not tuning evidence.

## Restart contract

Selection stages files; it never rewrites ISTART or ICHARG.

| Selection | Files | Supported effective ISTART | Supported effective ICHARG |
| --- | --- | --- | --- |
| `none` | Neither | 0 | 0 or 2 |
| `wavecar` | WAVECAR | 1 | 0 or 2 |
| `chgcar` | CHGCAR | 0 | 1 or 11 |
| `both` | Both | 1 | 1 or 11 |

Absent ISTART defaults to 1 with selected WAVECAR, otherwise 0. Absent ICHARG
defaults to 0 for ISTART=1, otherwise 2. Therefore CHGCAR/both modes normally
require an explicit appropriate ICHARG in the scientific input. Contradictions
are rejected before staging. See the official [ISTART](https://vasp.at/wiki/ISTART)
and [ICHARG](https://vasp.at/wiki/ICHARG) semantics.

CHGCAR checks stream the structure, density/spin and augmentation blocks, reject
obvious truncation, and compare the electron integral (1e-3 electrons tolerance).
Named species/order/counts must match, with cell/site tolerances of 1e-7; Cartesian
positions are converted for comparison only. Changing KPOINTS alone is permitted
for CHGCAR reuse. Stored augmentation channels are not a general PAW-completeness
certificate; see [CHGCAR](https://vasp.at/wiki/CHGCAR).

WAVECAR checks cover little-endian collinear 45200/45210 headers, record lengths,
spin, lattice, explicit ENCUT/NBANDS and basic coefficient-record dimensions.
Donor POSCAR, POTCAR, INCAR spin, OUTCAR electron count and main KPOINTS are compared
when available. Missing donor records leave explicit compatibility limits.
Coefficients are not parsed or validated. Matching-cell/cutoff/known-mesh reuse is
the initial supported scope; arbitrary geometry, cutoff and band transformations
are not supported. See [WAVECAR](https://vasp.at/wiki/WAVECAR).

PBE → HSE orbital initialization is allowed: functional equality is not required.
Actual VASP messages separately report accepted/rejected/unknown restart evidence.
A detected WAVECAR rejection or fresh-start fallback makes an otherwise successful
run return 65. Unknown evidence remains unknown; inspect the retained logs.

ISTART=2/3, noncollinear/SOC restarts, frozen-density meta-GGA/DFT+U and fixed-charge
hybrid workflows are deliberately unsupported. Fresh SOC runs use `--binary ncl`.
No new checkpoint is certified as a usable restart solely because it exists.

## Supported sampling and feature guards

This interface requires KPOINTS. It accepts ordinary automatic Gamma/Monkhorst
meshes, explicit weighted coordinates and Line-mode endpoints; optional labels
need `#` or `!`. POSCAR requires named species, one scale factor and ordinary
Direct/Cartesian coordinates, with optional selective dynamics. VASP-4 unnamed
species, three-factor scales, KSPACING-only inputs and multi-directory workflows
are outside this interface.

The gamma binary requires genuine Gamma-only main sampling. SOC/noncollinear
requests require ncl. Active KPOINTS_OPT requires an automatic uniform main mesh
and a Line-mode optional path; gam is rejected and hybrids require NCORE=1.
A present optional file with LKPOINTS_OPT=false is staged but disabled, and is
reported distinctly. Unsupported optional representations are rejected.

Hybrid Damped/All, omitted/default HFRCUT with hybrid optional points, ISYM=0 and
KPAR>1 generate informational warnings. The launcher changes none of these
scientific choices and does not claim ACE acceleration for Damped/All. Review
[KPOINTS_OPT](https://vasp.at/wiki/KPOINTS_OPT) for the method contract. The tested
host needs synthetic OpenMPI topology; native mode has not been revalidated here.

## Deadline, checkpoint and completion semantics

The hard execution budget starts when MPI is launched, after staging. At the
deadline, SIGINT or SIGTERM, the single supervisor terminates only its owned
process group, gives it up to 10 seconds of cleanup grace, then escalates to
SIGKILL if needed and reaps its direct child. Deadline enforcement can therefore
be followed by bounded cleanup time. Existing outputs are retained; there is no
retry or mode switch. Descendants that deliberately detach from the owned process
group are outside the supervisor contract; ordinary MPI ranks stay in that group.

With `--stop-before`, the launcher exclusively creates STOPCAR before the deadline:
LABORT for static work (next electronic boundary), LSTOP for NSW>0 (next ionic
boundary). An existing STOPCAR is preserved. The hard deadline still applies.
A long step might not observe STOPCAR in time. Electronic stopping can leave an
unconverged checkpoint; see [STOPCAR](https://vasp.at/wiki/STOPCAR). LWAVE/LCHARG
are never enabled automatically. Metadata reports absent/new/updated/unchanged
checkpoint files and that their validity is NOT ASSESSED.

A bounded `caffeinate -i` child prevents idle sleep during the owned run and is
cleaned up afterward. This does not promise operation with a closed lid and does
not alter system power settings.

| Exit status | Meaning |
| --- | --- |
| 0 | Process completed and version/restart rejection checks passed; inspect scientific status |
| 2 | Argument/preflight refusal (or an error before ownership) |
| 1 | Failure after staging began; owned directory retained |
| 65 | Child exited zero but version was unverified/mismatched or WAVECAR was rejected |
| 124 / 130 / 143 | Timeout / SIGINT / SIGTERM |
| Other nonzero | Underlying program status where meaningful; negative signal status is normalized |

RUN_METADATA.txt records requested/effective settings, selected binary identity,
repository commit/dirty state, input identities, staged-file hashes, original and
effective INCAR identities, limited environment, actual MPI version, runtime VASP
banner, timestamps/deadline, termination and separate child status. stdout.log and
stderr.log sit beside ordinary VASP output. There is no second manifest/database.
Ignored input content is identified separately from repository commit identity.
Local POTCAR/restart fingerprints are not exported in the public report.

Only supported static SCF runs with finite observables, a normal footer and EDIFF
evidence can be confirmed. Reaching NELM or requesting LABORT prevents confirmation,
even if an EDIFF footer appears. A run converging exactly at NELM is conservatively
unconfirmed. Fixed-charge, ionic completion and incomplete/unsupported output are
NOT ASSESSED. Process success and checkpoint existence are not scientific success.

## Examples on the audited Mac

These private Si2 inputs and donor were created by the launcher tests. They are
not distributed with Git. Each output below must be new; choose another name for
a repeat. The existing `runs` parent is used, without installation or global PATH
changes. Restart input explicitly supplies ISTART=1, ICHARG=0; the donor stays read-only.

```sh
PORT='/Users/liangze/Desktop/squiddy tools/vasp-6.6.1-macos-arm64-port'
CASE="$PORT/private/launcher-tests/real-20260907-180140"

# Plan only; no output directory or metadata is created.
"$PORT/scripts/run-vasp.sh" --input "$CASE/inputs/baseline" \
  --output "$CASE/runs/example-dry" --dry-run

# Fresh PBE Si2 calculation.
"$PORT/scripts/run-vasp.sh" --input "$CASE/inputs/baseline" \
  --output "$CASE/runs/example-fresh" --ranks 1 --timeout 60

# Resume from a donor into a new execution directory.
"$PORT/scripts/run-vasp.sh" --input "$CASE/inputs/wavecar" \
  --output "$CASE/runs/example-wavecar" --restart wavecar \
  --restart-from "$CASE/runs/donor" --ranks 2 --timeout 60

# Tiny HSE06/ACE plus optional path; existing private fixture settings are retained.
"$PORT/scripts/run-vasp.sh" --input "$CASE/inputs/hse-opt" \
  --output "$CASE/runs/example-hse-opt" --binary std --mpi-mode synthetic \
  --ranks 2 --ncore 1 --kpar 1 --timeout 120
```

## Validation and limits

Run deterministic tests from the repository root with
`python3 -B -m unittest discover -s tests -v`. They require the local port/toolchain
but do not run VASP. Synthetic temporary directories are created and removed under
`private/launcher-tests`; create that parent if setting up a different checkout.
The private real-test driver is not invoked by unittest.

See [LAUNCHER_VALIDATION.md](../validation/reports/LAUNCHER_VALIDATION.md) for the
15 deterministic tests and bounded sequential Si2 evidence. Those checks establish
this launcher contract on this Mac. They do not approve a ZnIn2S4 workflow, dense
hybrid production, general restart compatibility, ionic relaxation or checkpoint
recovery after abrupt termination. Existing port-level scientific validation and
its limitations remain in [VALIDATION_REPORT.md](../VALIDATION_REPORT.md).
