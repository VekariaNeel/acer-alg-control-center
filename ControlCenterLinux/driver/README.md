# Acer AL15G-52 Linux bridge — release 0.5.1, ABI 2

The model-specific module now includes typed, root-only setters for fans,
curves/offset, static RGB, brightness, FlexiCharger, keyboard flags/sleep,
webcam and firmware performance profiles. Compatibility remains exact:
**Acer Aspire Lite AL15G-52, BIOS 1.07.01RAC2, CLV0001, two fans/type-6 keyboard.**
See [PROTOCOL.md](PROTOCOL.md) for layouts, evidence, readback semantics and
the target-validation boundary. Raw telemetry getters remain compatible with
the earlier read-only bridge. ABI 1 modules cannot expose the new controls.

## Recommended setup

From the new source archive, run as your normal user on Fedora:

```bash
bash setup-fedora.sh
```

The application README describes the dependencies, existing signing-key paths,
installed module/boot-load entry and per-kernel rebuild requirement. New keys
are not generated or enrolled. The bridge performs no configuration changes
when loading, unloading or collecting diagnostics.

## Manual build, sign and temporary load

```bash
sudo dnf install gcc make "kernel-devel-$(uname -r)"
make -C driver
sudo /usr/src/kernels/$(uname -r)/scripts/sign-file sha256 \
  /etc/pki/mok/ControlCenterLinux.priv \
  /etc/pki/mok/ControlCenterLinux.der \
  "$PWD/driver/acer_al15g52.ko"
sudo insmod driver/acer_al15g52.ko
python3 main.py
# After closing the app, if you only loaded the module temporarily:
sudo rmmod acer_al15g52
```

Use paths for your existing enrolled key. Signing requires a newly built module
for the running kernel; do not force-load a module from another kernel. A
`Key was rejected by service` error is a trust failure, not a reason to disable
Secure Boot. The official [kernel signing documentation](https://docs.kernel.org/admin-guide/module-signing.html)
describes the signature mechanism.

Kbuild cannot use an external module directory containing spaces. The build
wrapper copies only the C source, two headers and Makefile into a fresh
`/tmp/control-center-build.*` directory, builds there, copies back `.ko`, then
cleans up. A failed build leaves the previous module intact; a successful build
replaces it and requires a new signature. The project can stay on your mounted
drive with spaces. The source archive contains no built modules or keys.

## Diagnostics without setting changes

The existing probe still only reads configuration; having setters in the
loaded driver does not execute them:

```bash
# Builds an unsigned new module before loading:
bash driver/probe-fedora.sh

# Reuse an existing matching signed module without rebuilding:
bash driver/probe-fedora.sh --module driver/acer_al15g52.ko
```

It validates the name/kernel, temporarily loads the module if needed, saves
`control-center-fedora-probe.json`, and unloads only a module it loaded. A
failed/invalid diagnostic report returns nonzero. An already loaded module is
left loaded. To use the UI's hardware controls, keep the module loaded through
setup or the manual commands above; a temporary probe unloads it afterward.

No arbitrary command selector, raw EC memory interface, hotkey handler,
background polling worker or boot-time setting application is included.
Physical readback of the new setters remains pending on the target Fedora boot.
