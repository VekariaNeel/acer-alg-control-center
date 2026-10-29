#!/usr/bin/env bash
# Explicit Fedora setup. Never enroll keys, disable Secure Boot or apply settings.
set -Eeuo pipefail
app_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
kernel_release=$(uname -r)
stage='checking the target system'
app_installed=0
log=$app_dir/setup-fedora.log
setup_failed() {
    local status=$1
    trap - ERR
    printf '\nSetup stopped during %s (exit %s).\n' "$stage" "$status" >&2
    if [[ $app_installed == 1 ]]; then
        printf '%s\n' 'The desktop app is installed. Open it with: /usr/local/bin/control-center-clone' >&2
        printf '%s\n' 'Firmware controls still require the Acer driver to finish setup.' >&2
    else
        printf '%s\n' 'The desktop installation has not completed.' >&2
    fi
    printf 'Setup log: %s\n' "$log" >&2
    exit "$status"
}
if [[ $(id -u) == 0 || $(uname -s) != Linux || $kernel_release == *microsoft* ]]; then
    printf '%s\n' 'Run as your normal user directly on the Acer Fedora installation.' >&2
    exit 1
fi
if [[ $(cat /sys/class/dmi/id/sys_vendor) != Acer ||
      $(cat /sys/class/dmi/id/product_name) != 'Aspire Lite AL15G-52' ||
      $(cat /sys/class/dmi/id/bios_version) != 1.07.01RAC2 ]]; then
    printf '%s\n' 'The firmware bridge supports AL15G-52 BIOS 1.07.01RAC2 only.' >&2
    exit 1
fi
exec > >(tee -a "$log") 2>&1
trap 'setup_failed "$?"' ERR
printf '\nControl Center setup started: %s\n' "$(date -Is)"
stage='installing desktop dependencies'
sudo dnf install python3 python3-gobject gtk4 wireplumber polkit
stage='installing the desktop app and launcher'
sudo bash "$app_dir/install-fedora.sh"
app_installed=1
printf '%s\n' 'Desktop app installed. Continuing with the Acer driver…'
stage='installing kernel build dependencies'
sudo dnf install gcc make "kernel-devel-$kernel_release" mokutil
stage='building the Acer driver'
make -C "$app_dir/driver"
module_path=$app_dir/driver/acer_al15g52.ko
key=${CC_MODULE_KEY:-/etc/pki/mok/ControlCenterLinux.priv}
certificate=${CC_MODULE_CERT:-/etc/pki/mok/ControlCenterLinux.der}
secure_boot=0
if mokutil --sb-state 2>/dev/null | grep -qi 'SecureBoot enabled'; then
    secure_boot=1
fi
enrolled=0
if sudo test -f "$key" && sudo test -f "$certificate"; then
    stage='checking the enrolled module-signing key'
    key_test_status=0
    key_test_output=$(sudo env LC_ALL=C mokutil --ignore-keyring --test-key "$certificate" 2>&1) || key_test_status=$?
    printf '%s\n' "$key_test_output"
    printf 'mokutil key-test exit status: %s\n' "$key_test_status"
    # mokutil 0.7.2 returns 1 for an enrolled key and 0 for an unenrolled
    # key. Later versions use conventional exit status. Require the exact
    # affirmative MOK message as well as a recognized status; never accept
    # success status alone, a pending request, a blocked key or read failure.
    if [[ ( $key_test_status == 0 || $key_test_status == 1 ) &&
          $key_test_output == "$certificate is already enrolled" ]]; then
        enrolled=1
    fi
fi
if [[ $enrolled == 1 ]]; then
    stage='signing the Acer driver'
    sudo "/usr/src/kernels/$kernel_release/scripts/sign-file" sha256 "$key" "$certificate" "$module_path"
elif [[ $secure_boot == 1 ]]; then
    printf '%s\n' 'Secure Boot is enabled. Use an existing enrolled key and rerun setup with:' >&2
    printf '%s\n' 'CC_MODULE_KEY=/path/to/key.priv CC_MODULE_CERT=/path/to/cert.der bash setup-fedora.sh' >&2
    printf '%s\n' 'No key was generated/enrolled and no boot security setting was changed.' >&2
    stage='checking the enrolled module-signing key'
    setup_failed 1
fi
if [[ $(modinfo -F name "$module_path") != acer_al15g52 ||
      $(modinfo -F vermagic "$module_path" | cut -d ' ' -f 1) != "$kernel_release" ]]; then
    printf '%s\n' 'The built module does not match the running kernel.' >&2
    stage='validating the built module'
    setup_failed 1
fi
stage='loading and installing the Acer driver'
if [[ -d /sys/module/acer_al15g52 ]]; then
    sudo rmmod acer_al15g52
fi
sudo install -D -m 0644 "$module_path" "/lib/modules/$kernel_release/extra/acer_al15g52.ko"
sudo depmod -a "$kernel_release"
sudo modprobe acer_al15g52
# Load only the bridge at boot. Loading exposes interfaces and applies no settings.
printf '%s\n' acer_al15g52 | sudo tee /etc/modules-load.d/control-center-clone.conf >/dev/null
printf '%s\n' 'Setup complete. Launch Control Center Clone from Applications.'
printf '%s\n' 'Terminal launcher: /usr/local/bin/control-center-clone'
printf '%s\n' 'No fan, RGB, power, charging or input settings have been applied.'
printf '%s\n' 'After a kernel update, rerun this setup to rebuild and sign for the new kernel.'
printf 'Setup log: %s\n' "$log"
