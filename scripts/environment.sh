#!/usr/bin/env bash
# Process-local selection: never source this into a login profile.
PORT_ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PORT_SOURCE=/Applications/Academic/vasp.6.6.1
# Versions: config/toolchain-defaults.txt, overridden by the host-local private/toolchain.env.
port_toolchain=$(/usr/bin/python3 -I -B "$PORT_ROOT/scripts/toolchain.py" --shell) || return 1
eval "$port_toolchain"
unset port_toolchain
PORT_GNU=/opt/homebrew/Cellar/gcc/$PORT_GCC_VERSION
PORT_MPI=/opt/homebrew/Cellar/open-mpi/$PORT_OPENMPI_VERSION
PORT_MAKE=/opt/homebrew/bin/gmake
export OMPI_FC="$PORT_GNU/bin/gfortran"
export OMPI_CC="$PORT_GNU/bin/gcc-${PORT_GCC_VERSION%%.*}"
export OMPI_CXX="$PORT_GNU/bin/g++-${PORT_GCC_VERSION%%.*}"
export PATH="/opt/homebrew/opt/make/libexec/gnubin:$PORT_MPI/bin:$PORT_GNU/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
export PYTHONDONTWRITEBYTECODE=1
unset DYLD_LIBRARY_PATH DYLD_FALLBACK_LIBRARY_PATH LD_LIBRARY_PATH
