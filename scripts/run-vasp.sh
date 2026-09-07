#!/usr/bin/env bash
set -euo pipefail
. "$(dirname -- "$0")/environment.sh"
exec python3 -B "$PORT_ROOT/scripts/run_vasp.py" "$@"
