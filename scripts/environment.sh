#!/usr/bin/env bash
# Process-local selection: never source this into a login profile.
PORT_ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PORT_SOURCE=/Applications/Academic/vasp.6.6.1
PORT_GNU=/opt/homebrew/Cellar/gcc/16.1.0
PORT_MPI=/opt/homebrew/Cellar/open-mpi/5.0.9
PORT_MAKE=/opt/homebrew/bin/gmake
export OMPI_FC="$PORT_GNU/bin/gfortran"
export OMPI_CC="$PORT_GNU/bin/gcc-16"
export OMPI_CXX="$PORT_GNU/bin/g++-16"
export PATH="/opt/homebrew/opt/make/libexec/gnubin:$PORT_MPI/bin:$PORT_GNU/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
export PYTHONDONTWRITEBYTECODE=1
unset DYLD_LIBRARY_PATH DYLD_FALLBACK_LIBRARY_PATH LD_LIBRARY_PATH
