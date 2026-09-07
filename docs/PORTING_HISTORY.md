# Port history and repository boundary

This records the actual retained commit history. It is a presentation of work
completed on 7 September 2026, not a reconstruction of fictitious intermediate
build states. The three original commits remain unchanged.

## Existing VASP 6.6.1 history

| Commit | Actual scope |
|---|---|
| `76ae6fb` — build: add VASP 6.6.1 macOS ARM64 configuration | Repository exclusions; current-release GNU configuration; pinned toolchain; external std/gam/ncl build wrapper; native dependency inspection; private source-integrity check; isolated MPI launcher |
| `de2c6f3` — test: validate VASP 6.6.1 ARM64 runtime | Safe build/binary/dependency provenance; core and advanced validation drivers; completed generic runtime and derivative summaries; beta comparison drivers |
| `20f48c1` — docs: document VASP 6.6.1 port and capabilities | Build and validation guides; final measured report; optional-path coordinate checker; beta numerical summaries, including explicitly incomplete dense HSE benchmarks |

The build used GCC/GFortran 16.1.0, OpenMPI 5.0.9, OpenBLAS 0.3.34,
ScaLAPACK 2.2.3 and FFTW 3.3.11. All three variants compiled without source
patches. Ordinary MPI launch reproduced a PRRTE/hwloc topology failure;
the explicitly selected synthetic-topology mode passed the runtime gates.
These are recorded results, not new tests performed during publication.

## Comparison with the actual VASP 5.4.4 history

The read-only reference was the local `vasp-5.4.4-macos-arm64-port` repository.
Its history separates these concerns:

| Reference commit | Concern | Where VASP 6.6.1 records the analogous concern |
|---|---|---|
| `98725ae` chore | Safe repository boundary | Original build commit and the boundary follow-up below |
| `30c4482` docs | Source/build provenance | Runtime validation commit and `provenance/` |
| `8292747` build | Native toolchain workflow | Original build commit |
| `c2864a0` build | Legacy source compatibility work | No equivalent: the VASP 6.6.1 build needed no source patch |
| `240ef40` runtime | Apple Silicon PRRTE handling | Original build commit's isolated launcher; failure and fallback recorded in the validation report |
| `1f0e752` build | std/gam/ncl variants | Original build wrapper already supports all three variants |
| `6f36b88` test | Native runtime validation | Runtime validation commit |
| `a671aed` docs | Reproducibility guide | Original documentation commit and this history guide |
| `8dba864` docs | Cross-platform scientific comparison | VASP-6 report instead records the actual native 5.4.4/6.6.1 beta comparison and modern-functional checks |
| `9edfd4d` docs | Public-release documentation | Private repository preparation only; no visibility change, tag or release |

The reference informs scope and conventional commit style, not commit count.
Splitting already committed build/runtime/variant files would rewrite legitimate
history, so those candidate commits were deliberately not recreated. No old
source patch, public-release claim, backdated commit or invented validation
step was introduced.

## Repository connection and follow-up

At the start of this follow-up, local `main` was clean at `20f48c1` with no
remote. GitHub identified the requested repository as private, with default
branch `main`, no branches and no commits. `origin` was added as:

`https://github.com/angzeli/vasp-6.6.1-macos-arm64-port.git`

The focused follow-up commits are:

- `9912c40` — `chore: harden VASP 6.6.1 repository exclusions`: protect
  root `build/`, root `bin/` and source/potential archives, and extend the existing
  boundary check.
- The commit containing this guide — `docs: record VASP 6.6.1 port history and repository boundary`:
  map the retained history to the reference, clarify the README's licensing
  boundary, and distinguish the original local validation task from publication.

The authorized publication uses a normal push of `main`, preserving every
existing commit. No force push, history rewrite, tag, release or visibility
change is part of this work. An HTTPS Git connection timed out; a session-local
SSH-over-443 route was verified with host keys obtained from GitHub's HTTPS API.
The stored origin URL remains HTTPS and global Git/SSH settings are unchanged.

## What may enter Git

Only independently authored configuration, scripts, documentation and safe
numerical/provenance summaries belong in the tracked tree. This project does
not distribute VASP source, VASP binaries, PAW datasets or POTCAR files. Users
must obtain VASP separately under an appropriate VASP license.

Licensed source staging, local binaries, copied potentials, calculations and
raw compiler/runtime logs remain in ignored `macos-arm64/` and `private/`
directories. Local Python caches are ignored as well. Do not force-add them.
A filename or binary hash mentioned in text is metadata, not redistribution of
that file. The tracked hashes describe executables only; private source and
potential content is not included.

Before committing, stage explicit paths and run `python3 -B scripts/check-repository.py`.
Before publishing, inspect all reachable history as well as the current index:
ignore rules do not remove anything already committed. Review file types,
sizes and content for licensed material and credentials. The automated checker
is a guardrail, not a substitute for that content review.

No VASP build, HSE calculation, numerical revalidation, upstream edit or change
to the VASP 5.4.4 reference repository was performed to create this history.
The measured capability limits remain in [the validation report](../VALIDATION_REPORT.md).
