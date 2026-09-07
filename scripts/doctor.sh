#!/usr/bin/env bash
set -euo pipefail
. "$(dirname -- "$0")/environment.sh"
test "$(uname -m)" = arm64
test -x /opt/homebrew/opt/make/libexec/gnubin/make
test "$("$PORT_MPI/bin/mpifort" --showme:command)" = "$OMPI_FC"
printf 'source=%s\n' "$PORT_SOURCE"
sw_vers
"$OMPI_FC" --version | head -n 1
"$OMPI_CC" --version | head -n 1
"$PORT_MPI/bin/mpirun" --version | head -n 1
"$PORT_MPI/bin/mpifort" --showme:command
"$PORT_MPI/bin/mpifort" --showme:link
"$PORT_MAKE" --version | head -n 1
for library in /opt/homebrew/Cellar/openblas/0.3.34/lib/libopenblas.dylib /opt/homebrew/Cellar/scalapack/2.2.3/lib/libscalapack.dylib /opt/homebrew/Cellar/fftw/3.3.11/lib/libfftw3.dylib; do
    test -f "$library"
    file -L "$library"
done
test -f /opt/homebrew/Cellar/fftw/3.3.11/include/fftw3.f
printf 'Fortran wrapper selection and required dependency files: PASS\n'
