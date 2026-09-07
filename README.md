# Local VASP 6.6.1 port for macOS ARM64

Independent build and validation tooling for the locally licensed VASP 6.6.1 source on this Apple M3 Max. Read [VALIDATION_REPORT.md](VALIDATION_REPORT.md) for measured results and capability limits; a successful build alone does not establish scientific correctness.

- Upstream: `/Applications/Academic/vasp.6.6.1`, preserved unchanged.
- Toolchain: GCC/GFortran 16.1.0, OpenMPI 5.0.9, OpenBLAS 0.3.34, ScaLAPACK 2.2.3, FFTW 3.3.11.
- Local executables: `macos-arm64/bin/vasp_std`, `vasp_gam`, `vasp_ncl`; all three passed their build and runtime gates.
- Configuration: `config/makefile.include.macos-arm64`, independently written from the current release's GNU configuration requirements.
- Build instructions: [docs/BUILD.md](docs/BUILD.md).
- Validation definitions: [docs/VALIDATION.md](docs/VALIDATION.md).

This repository does not contain or grant rights to VASP, its executables, source, test potentials, or PAW data. Obtain and use those under the appropriate VASP license. Licensed build staging and calculations stay exclusively in ignored `macos-arm64/` and `private/` directories. Do not force-add those directories. Raw compiler logs may contain licensed excerpts and must remain private. Source fingerprints and potential identity checks also remain private.

No global shell or MPI configuration is changed. The launcher pins Homebrew OpenMPI and sets one library thread per rank. This host requires the selectable synthetic-topology mode after a reproduced PRRTE/hwloc crash; see the validation report. No remote publication is part of this port task.
