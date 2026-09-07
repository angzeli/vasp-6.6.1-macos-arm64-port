# VASP 6.6.1 macOS ARM64 porting tools

> [!IMPORTANT]
> This repository contains independently authored macOS ARM64 build, runtime,
> audit and validation tooling only. It does not contain or distribute VASP
> source code, VASP executables, or PAW/POTCAR datasets. Obtain and use VASP
> separately under an appropriate VASP license.

This repository preserves the external build and validation layer used to
compile licensed VASP 6.6.1 source into native Mach-O ARM64 executables on an
Apple M3 Max. It is a bring-your-own-source workflow, not a VASP distribution
or binary installer. This is an unofficial porting project, not an official
VASP-supported macOS distribution.

All three variants compiled without source patches. The recorded verdict is
**WORKING PORT WITH CAVEATS**, with high confidence for the tested native core
and bounded capabilities. See the [full validation report](VALIDATION_REPORT.md)
for measured results and limits.

## License and ownership

This project's independently authored tooling does not grant rights to VASP
software, source code, executables or PAW/POTCAR datasets. Interoperability
with separately licensed material does not relicense that material. Licensed
inputs and generated executables remain local and excluded from Git.

## What you need

- An authorized VASP **6.6.1** source tree outside this repository
- An Apple Silicon Mac and the installed native toolchain described below
- GNU Make and Python 3 for the build and validation wrappers
- Separately licensed potentials and local fixtures when running validation

The current tooling is pinned to the validated machine's paths. The licensed
source is `/Applications/Academic/vasp.6.6.1`; compiler and library prefixes are
recorded in `scripts/environment.sh` and
`config/makefile.include.macos-arm64`. These are not automatically discovered
or interchangeable with the VASP-5 configuration.

The validation harness reads existing authorized fixtures from
`/Applications/Academic/vasp.5.4.4/macos-arm64/validation`. The beta comparison
also depends on the local WP1 reference paths recorded in `scripts/benchmark.py`.
Those fixtures and potentials are not supplied by cloning this repository.
Review the explicit paths before adapting the tooling to another machine.

## Tested platform

| Component | Tested value |
| --- | --- |
| Machine | Apple M3 Max, 14 physical cores, 36 GiB memory |
| Host | macOS 26.3, arm64 |
| VASP | 6.6.1; build and validation on 7 September 2026 |
| GCC / GFortran | 16.1.0 |
| OpenMPI | 5.0.9 |
| OpenBLAS | 0.3.34 |
| ScaLAPACK | 2.2.3 |
| FFTW | 3.3.11 |
| GNU Make | 4.4.1 |

Compiler and dependency paths are explicit. The MPI Fortran wrapper is checked
against the selected GCC 16 compiler, avoiding the unrelated shell-default
GCC 14 / MPI 4 installation. Environment changes are process-local; no global
shell or MPI configuration is edited, and no dependency is installed or upgraded.

## What is automated

- Host architecture, dependency-file and MPI/Fortran compiler checks
- External builds using an independently authored configuration based on the
  current VASP 6.6.1 GNU template's requirements
- Separate `std`, `gam` and `ncl` build directories, with two compile jobs per variant
- Native Mach-O architecture and recursive dynamic-library inspection
- Explicit native or synthetic-topology MPI launch with bounded ranks and timeouts
- Private silicon smoke tests, MPI comparisons and SOC/noncollinear checks
- HSE06/ACE, optional-path and meta-GGA capability tests
- Bounded r2SCAN and r2SCAN+rVV10 force/stress finite differences
- Safe numerical summaries, binary provenance and a local repository-boundary check

No VASP-5 legacy source fixes are applied. HDF5, VASP OpenMP, GPU acceleration,
Libxc, Wannier90, qd and optional external interfaces are disabled in this build.

## Shortest build workflow

From the repository root, begin with the standard executable:

```sh
./scripts/doctor.sh
./scripts/build.sh std
```

The wrapper reads the licensed upstream tree and stages required build inputs
under ignored `macos-arm64/build/std/`. Configuration stays in `config/`, raw
build logs stay in `private/logs/`, and a successful executable is installed
under `macos-arm64/bin/`. No build output is written into the upstream tree.

After the standard smoke and MPI gates pass, build and validate `gam`, then
`ncl`, following [the gated build workflow](docs/BUILD.md). The scripts support
`./scripts/build.sh gam` and `./scripts/build.sh ncl`; they do not implement the
VASP-5 port's `--variant all` or `--dry-run` interface.

Expected local products are:

- `macos-arm64/bin/vasp_std`
- `macos-arm64/bin/vasp_gam`
- `macos-arm64/bin/vasp_ncl`

The retained workspace already contains the tested binaries and validation
cases. These instructions describe reconstruction; documentation changes do
not require rebuilding. Existing build directories may be reused by the build
wrapper, while validation refuses to overwrite an existing case directory.

## Running MPI

Run the launcher from a calculation directory containing your authorized inputs:

```sh
/path/to/vasp-6.6.1-macos-arm64-port/scripts/run-mpi.sh \
  --ranks 4 --mode synthetic --timeout 600 -- \
  /path/to/vasp-6.6.1-macos-arm64-port/macos-arm64/bin/vasp_std
```

On the tested M3 Max, ordinary OpenMPI 5 launch failed in PRRTE/hwloc topology
construction before VASP started. The verified workaround uses a synthetic
topology derived from the physical core count, with `--bind-to none --map-by slot`.
It changes launch placement, not scientific source.

The launcher supports **1–8 ranks**, uses one library thread per rank, preserves
exit status and terminates its own process group on timeout or interruption.
`--mode native` selects ordinary MPI; `--mode synthetic` explicitly selects the
workaround. There is no `auto` mode or automatic retry of a scientific calculation.
A different host needs its own launch-mode verification.

The core validation drivers read the verified mode from the local, ignored
`private/mpi-mode.txt`. This file is not supplied by Git; it must contain
`native` or `synthetic` after that mode has been checked on the target host.
See [the build guide](docs/BUILD.md) and [the recorded MPI results](VALIDATION_REPORT.md).

## Validation status

Completed native checks include:

| Capability | Recorded result | Scope |
| --- | --- | --- |
| `vasp_std` / PBE | PASS | 1/2/4/8-rank silicon SCFs; energies agree at recorded precision |
| `vasp_gam` | PASS | Gamma-only SCF agrees with std |
| `vasp_ncl` | PASS | Bounded SOC/noncollinear smoke |
| HSE06 and ACE | CONFIRMED | Converged small-fixture calculations; ACE on/off energies agree |
| `KPOINTS_OPT` | CONFIRMED | Generic test and reduced beta path, evaluated after regular SCF |
| SCAN and r2SCAN | CONFIRMED | Runtime identities and distinct numerical trajectories |
| r2SCAN+rVV10 | CONFIRMED | Modern rVV10 route and resolved runtime parameters |
| r2SCAN methods' derivatives | PASS | Two force-displacement and two strain steps per method on silicon |
| HDF5 | NOT BUILT / NOT TESTED | Optional Fortran dependency not enabled |

All three executables were checked as native Mach-O arm64 with resolved native
library dependencies. The r2SCAN checks excluded the previous VASP-5 silent-PBE
fallback. Both r2SCAN methods passed the predeclared force and stress tolerances;
these checks cover one coordinate and one normal stress component, not every
chemical environment or production relaxation/EOS/phonon workflow.

A matched native VASP 5.4.4 / 6.6.1 beta ZnIn2S4 PBE-D3(BJ) comparison passed.
The energy difference was **8×10⁻⁸ eV per formula unit**, with matching electron
counts and acceptable force/stress differences. This is a cross-version native
comparison, not the VASP-5 repository's Linux/macOS comparison.

The reduced beta HSE preflight used a **3×3×2** regular mesh and converged in
18 iterations. It then evaluated all nine retained Stage 04 path segments:
**27 optional points and 1,080 finite eigenvalues**, with matching ordered
reciprocal coordinates. Total walltime was **1,122.456 seconds**.

The dense **12×12×4** HSE cases, with and without ACE, each reached a 1,200-second
job limit before completing an electronic iteration. No dense-mesh speedup
against the historical 25,465-second VASP-5 iteration is established. Full-mesh
HSE convergence and production band sampling remain to be validated before
replacing WP1 Stage 05 production results.

See [the validation definitions](docs/VALIDATION.md) and
[the complete measured report](VALIDATION_REPORT.md). No scientific calculation
was rerun to prepare this README.

## Repository boundary and safety

Tracked files contain only independent tooling, configuration, documentation,
safe numerical summaries and provenance metadata. Licensed source staging,
VASP binaries, PAW/POTCAR data, raw compiler/runtime logs and heavy calculation
outputs remain in ignored `macos-arm64/` and `private/` directories. Root
`build/`, `bin/` and source/potential archives are excluded as well.

Before committing, review explicitly staged paths and run:

```sh
python3 -B scripts/check-repository.py
```

The checker validates the tracked/index file boundary and representative ignore
rules. It does not replace manual review for proprietary content or secrets,
or an audit of reachable history before publication. Do not force-add private
files. No GitHub Actions workflow is currently included in this repository.

## Repository map

| Area | Role |
| --- | --- |
| `config/` | Independently authored, explicitly pinned VASP-6 build configuration |
| `scripts/` | Build, dependency audit, MPI, validation and repository-safety tooling |
| `validation/reports/` | Safe retained numerical summaries |
| `provenance/` | Build identity, executable hashes and dependency metadata |
| `docs/` | Build, validation and factual port-history guides |
| `VALIDATION_REPORT.md` | Measured results, capability matrix and unresolved limits |
| `macos-arm64/` | Ignored local build staging and executables; not distributed |
| `private/` | Ignored licensed fixtures, calculations and raw logs; not distributed |

## Documentation

- [Build workflow and MPI launcher](docs/BUILD.md)
- [Validation definitions and tolerances](docs/VALIDATION.md)
- [Measured validation results](VALIDATION_REPORT.md)
- [Port history and repository boundary](docs/PORTING_HISTORY.md)
- [Build provenance](provenance/build-info.txt)
- [Binary hashes](provenance/binary-sha256.txt)
- [Dependency report](provenance/dependency-report.txt)
