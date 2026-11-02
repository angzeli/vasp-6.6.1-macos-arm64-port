#!/usr/bin/env bash
set -euo pipefail
. "$(dirname -- "$0")/environment.sh"
test "$(uname -m)" = arm64
test -x /opt/homebrew/opt/make/libexec/gnubin/make
test "$("$PORT_MPI/bin/mpifort" --showme:command)" = "$OMPI_FC"
printf 'source=%s\n' "$PORT_SOURCE"
printf 'toolchain versions from %s\n' "$PORT_TOOLCHAIN_SOURCE"
sw_vers
"$OMPI_FC" --version | head -n 1
"$OMPI_CC" --version | head -n 1
"$PORT_MPI/bin/mpirun" --version | head -n 1
"$PORT_MPI/bin/mpifort" --showme:command
"$PORT_MPI/bin/mpifort" --showme:link
"$PORT_MAKE" --version | head -n 1
cellar=/opt/homebrew/Cellar
for library in "$cellar/openblas/$PORT_OPENBLAS_VERSION/lib/libopenblas.dylib" "$cellar/scalapack/$PORT_SCALAPACK_VERSION/lib/libscalapack.dylib" "$cellar/fftw/$PORT_FFTW_VERSION/lib/libfftw3.dylib"; do
    test -f "$library"
    file -L "$library"
done
test -f "$cellar/fftw/$PORT_FFTW_VERSION/include/fftw3.f"
printf 'Fortran wrapper selection and required dependency files: PASS\n'
