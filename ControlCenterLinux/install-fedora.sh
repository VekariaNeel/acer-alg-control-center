#!/usr/bin/env bash
set -euo pipefail

# Run explicitly with sudo after installing dependencies. Does not replace the
# desktop's power daemon, install kernel modules, or change hardware settings.
if [[ $(id -u) != 0 ]]; then
    printf '%s\n' 'Run: sudo bash install-fedora.sh' >&2
    exit 1
fi
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
destination=/opt/control-center-clone
if [[ -L "$destination" ]]; then
    printf '%s\n' 'Refusing a symlink at /opt/control-center-clone.' >&2
    exit 1
fi
/usr/bin/install -d -o root -g root -m 0755 "$destination"
for file in main.py ui.py style.css services.py acer.py README.md FEDORA_REPORT.md; do
    /usr/bin/install -o root -g root -m 0644 "$source_dir/$file" "$destination/$file"
done
# An executable with an isolated Python shebang gives pkexec a distinct program
# identity. The policy never authorizes a general-purpose Python interpreter.
/usr/bin/install -o root -g root -m 0755 "$source_dir/core.py" "$destination/core.py"
/usr/bin/install -D -o root -g root -m 0644 "$source_dir/local.controlcenter.hardware.policy" /usr/share/polkit-1/actions/local.controlcenter.hardware.policy
# Remove the retired input backend on upgrades, including its elevated worker.
rm -f -- "$destination/macros.py" "$destination/input_helper.py"
/usr/bin/install -d -o root -g root -m 0755 "$destination/driver"
/usr/bin/install -o root -g root -m 0644 "$source_dir/driver/README.md" "$destination/driver/README.md"
/usr/bin/install -o root -g root -m 0644 "$source_dir/driver/PROTOCOL.md" "$destination/driver/PROTOCOL.md"
/usr/bin/install -D -o root -g root -m 0755 "$source_dir/control-center-clone" /usr/local/bin/control-center-clone
/usr/bin/install -D -o root -g root -m 0644 "$source_dir/local.controlcenter.Fedora.desktop" /usr/share/applications/local.controlcenter.Fedora.desktop
printf '%s\n' 'Installed. Launch Control Center Clone from Applications, or run control-center-clone.'
printf '%s\n' 'Hardware controls are authorized for your active local desktop session without per-change passwords.'
printf '%s\n' 'No hardware settings, kernel modules or power services were changed.'
