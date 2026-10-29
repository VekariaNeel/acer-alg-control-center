#!/usr/bin/env bash
# Kbuild splits M= on whitespace even when the shell argument is quoted.
# Stage only build sources in a fresh path without spaces, then copy back .ko.
set -euo pipefail
driver_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
kdir=${KDIR:-/lib/modules/$(uname -r)/build}
if [[ ! -f "$kdir/Makefile" ]]; then
    printf 'Missing kernel build tree: %s\n' "$kdir" >&2
    exit 1
fi
build_dir=$(mktemp -d /tmp/control-center-build.XXXXXXXX)
cleanup() { rm -rf -- "$build_dir"; }
trap cleanup EXIT
cp -- "$driver_dir/Makefile" "$driver_dir/acer_al15g52.c" \
    "$driver_dir/acer_protocol.h" "$driver_dir/acer_controls.h" "$build_dir/"
printf 'Building in %s (source: %s)\n' "$build_dir" "$driver_dir"
make -C "$kdir" M="$build_dir" modules
install -m 0644 -- "$build_dir/acer_al15g52.ko" "$driver_dir/acer_al15g52.ko"
printf 'Built: %s/acer_al15g52.ko\n' "$driver_dir"
printf '%s\n' 'If a trusted signature is required, sign this module after building.'
