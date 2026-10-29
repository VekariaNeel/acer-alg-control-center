#!/usr/bin/env bash
# Build/load the bridge for a read-only collection; never invoke setters.
set -euo pipefail
driver_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
app_dir=$(cd -- "$driver_dir/.." && pwd)
report=$PWD/control-center-fedora-probe.json
loaded_here=0
module_path=

usage() {
    printf '%s\n' 'Usage: bash driver/probe-fedora.sh [--module /path/to/acer_al15g52.ko]'
    printf '%s\n' 'Default: build from source, temporarily load, collect, unload.'
    printf '%s\n' '--module: use an existing module without rebuilding or changing its signature.'
}
if [[ ${1:-} == --help && $# == 1 ]]; then
    usage
    exit 0
elif [[ ${1:-} == --module && $# == 2 && -f $2 ]]; then
    module_path=$(cd -- "$(dirname -- "$2")" && pwd)/$(basename -- "$2")
elif [[ $# != 0 ]]; then
    usage >&2
    exit 2
fi
kernel_release=$(uname -r)

cleanup() {
    if [[ $loaded_here == 1 ]]; then
        if ! sudo rmmod acer_al15g52; then
            printf '%s\n' 'The module is still loaded. Unload with: sudo rmmod acer_al15g52' >&2
        fi
    fi
}
trap cleanup EXIT

if [[ $(uname -s) != Linux || $kernel_release == *microsoft* ]]; then
    printf '%s\n' 'Run this probe directly on the target Acer under Fedora, not in WSL.' >&2
    exit 1
fi
if [[ $(id -u) == 0 ]]; then
    printf '%s\n' 'Run this script as your normal user. It requests sudo only for loading/unloading the module.' >&2
    exit 1
fi
if [[ $(cat /sys/class/dmi/id/sys_vendor) != Acer ||
      $(cat /sys/class/dmi/id/product_name) != 'Aspire Lite AL15G-52' ||
      $(cat /sys/class/dmi/id/bios_version) != 1.07.01RAC2 ]]; then
    printf '%s\n' 'This probe only supports Acer Aspire Lite AL15G-52 BIOS 1.07.01RAC2.' >&2
    exit 1
fi
if [[ ! -d /sys/module/acer_al15g52 ]]; then
    if [[ -z $module_path ]]; then
        if ! command -v make >/dev/null || ! command -v gcc >/dev/null ||
           [[ ! -e /lib/modules/$kernel_release/build/Makefile ]]; then
            printf '%s\n' 'Install the matching Fedora build dependencies, then run this script again:' >&2
            printf 'sudo dnf install gcc make "kernel-devel-%s"\n' "$kernel_release" >&2
            exit 1
        fi
        make -C "$driver_dir"
        module_path=$driver_dir/acer_al15g52.ko
    fi
    if [[ $(modinfo -F name "$module_path") != acer_al15g52 ||
          $(modinfo -F vermagic "$module_path" | cut -d ' ' -f 1) != "$kernel_release" ]]; then
        printf '%s\n' 'Module name or kernel version does not match. Build for the running kernel, then sign the new module.' >&2
        exit 1
    fi
    if ! sudo insmod "$module_path"; then
        printf '%s\n' 'The module did not load. If the error says Key was rejected, sign it with an enrolled module-signing key (see driver/README.md).' >&2
        printf 'After signing, reuse it without rebuilding: bash %q --module %q\n' "${BASH_SOURCE[0]}" "$module_path" >&2
        exit 1
    fi
    loaded_here=1
fi
python3 "$app_dir/main.py" --diagnose --output "$report"
python3 - "$report" <<'PY'
import json
import sys
from pathlib import Path
state = json.loads(Path(sys.argv[1]).read_text())
bridge = state.get("acer", {})
if bridge.get("available"):
    print("Acer firmware reads succeeded. Fan RPM and firmware charge state are in the report.")
else:
    print("Bridge did not return validated data: " + bridge.get("reason", "unknown reason"))
print("Report: " + str(Path(sys.argv[1]).resolve()))
print("No firmware setters were executed by this diagnostic probe.")
sys.exit(0 if bridge.get("available") else 1)
PY
