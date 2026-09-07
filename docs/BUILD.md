# Building locally

The build was designed for the installed paths on this Mac. Run `scripts/doctor.sh` before rebuilding. It verifies native host architecture, dependency files, and that the MPI Fortran wrapper selects GCC 16 rather than the shell-default older compiler/MPI chain. Compiler and runtime selection is process-local in `scripts/environment.sh` and the make configuration.

The authoritative upstream configuration reference is VASP **6.6.1** `arch/makefile.include.gnu`. The independently authored configuration preserves its MPI, ScaLAPACK, FFTW, OpenBLAS/LAPACK and `fock_dblbuf` requirements. It uses conservative GNU optimization and the release's argument-compatibility option. Experimental CPU tuning and the template's broad warning suppression were omitted. Per-file optimization categories still follow the release build system. Warnings are retained in private logs; none was hidden by source edits.

Optional HDF5, parallel HDF5, OpenMP, GPU, Libxc, Wannier90, qd and external plugins are disabled. Internal release source modules may still compile behind their normal guards; this does not enable an external interface.

From the repository root, execute the gates sequentially:

```sh
./scripts/doctor.sh
./scripts/build.sh std
./scripts/validate-build.sh std
./scripts/build.sh gam
./scripts/validate-build.sh gam
./scripts/build.sh ncl
./scripts/validate-build.sh ncl
```

Validation expects the locally recorded launch mode in `private/mpi-mode.txt`. The initial task established it by trying native launch, recognizing the documented PRRTE/hwloc topology-signature failure, then testing the explicit synthetic mode. It is not a global MPI setting.

Each build copies only required build inputs from upstream into the ignored variant directory. It generates dependencies serially and compiles with two jobs. Upstream source paths are read-only inputs; the release's generated include and object files are written in staging. Successful binaries are installed under `macos-arm64/bin/` only. Build failures return a nonzero status and retain their timestamped private log; no failed executable is promoted. No VASP-5 compatibility or scientific patch is imported.

`scripts/audit-binary.py` checks the executable's Mach-O ARM64 identity and recursively resolves non-system dynamic dependencies, allowing system dyld-cache libraries. It rejects x86-only images and the old MPI/GCC runtime families. Its metadata includes a binary SHA-256; it never copies binary content to a report.

`scripts/source-integrity.py` computes a compact fingerprint over `src/`, `arch/`, and the root makefile. Its output belongs in `private/` only. Compare the private before/after records to verify preservation of the build inputs. This is a local integrity check, not authentication against an official archive.

The launch interface is:

```sh
/absolute/path/to/port/scripts/run-mpi.sh --ranks 8 --mode synthetic --timeout 600 -- /absolute/path/to/port/macos-arm64/bin/vasp_std
```

Run it from a calculation directory. It supports 1–8 ranks, returns the program/launcher status, and terminates its own launch process group on timeout or interruption. Synthetic mode derives the physical core count and disables binding; it is a reliability workaround, not a placement optimization. Native mode remains selectable for future revalidation. The launcher never retries an already-started VASP calculation automatically.
