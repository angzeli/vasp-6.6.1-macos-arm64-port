#!/usr/bin/env bash
set -euo pipefail
. "$(dirname -- "$0")/environment.sh"
variant=${1:-std}
case "$variant" in std|gam|ncl) ;; *) echo 'usage: build.sh std|gam|ncl' >&2; exit 2;; esac
"$PORT_ROOT/scripts/doctor.sh" >/dev/null
build_dir="$PORT_ROOT/macos-arm64/build/$variant"
mkdir -p "$build_dir" "$PORT_ROOT/macos-arm64/bin" "$PORT_ROOT/private/logs"
for input in makefile .objects makedeps.awk; do
    cp "$PORT_SOURCE/src/$input" "$build_dir/$input"
done
cp "$PORT_ROOT/config/makefile.include.macos-arm64" "$build_dir/makefile.include"
log="$PORT_ROOT/private/logs/build-$variant-$(date +%Y%m%dT%H%M%S).log"
printf 'Building %s with two jobs; private log: %s\n' "$variant" "$log"
(
    date -u
    "$PORT_MAKE" -C "$build_dir" VERSION="$variant" SRCDIR="$PORT_SOURCE/src" BINDIR=. check
    "$PORT_MAKE" -C "$build_dir" VERSION="$variant" SRCDIR="$PORT_SOURCE/src" BINDIR=. dependencies -j1
    "$PORT_MAKE" -C "$build_dir" VERSION="$variant" SRCDIR="$PORT_SOURCE/src" BINDIR=. all -j2
    date -u
) >"$log" 2>&1
test -s "$build_dir/vasp_$variant"
file "$build_dir/vasp_$variant" | grep -q 'Mach-O 64-bit executable arm64'
cp "$build_dir/vasp_$variant" "$PORT_ROOT/macos-arm64/bin/vasp_$variant"
printf 'Installed local arm64 binary: %s\n' "$PORT_ROOT/macos-arm64/bin/vasp_$variant"
