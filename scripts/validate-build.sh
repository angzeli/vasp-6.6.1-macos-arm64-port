#!/usr/bin/env bash
set -euo pipefail
. "$(dirname -- "$0")/environment.sh"
exec python3 "$PORT_ROOT/scripts/validate.py" "$@"
