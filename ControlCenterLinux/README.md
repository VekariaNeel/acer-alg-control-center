# Control Center Clone for Fedora — 0.5.1

Native GTK 4 controls for Acer Aspire Lite AL15G-52, BIOS 1.07.01RAC2.
A redesigned dark GTK interface with mint accents, compact live metric cards,
clear navigation and expandable settings. The three sections are System,
Keyboard Backlight and FlexiCharger. Lighting includes a draft-only keyboard
preview, 36 color presets, a rainbow hue slider and a full custom RGB picker;
battery care includes a live charge gauge.
Flexikey and its input worker have been removed from the Linux application.
Linux uses no Windows DLLs, drivers or Wine. This repository contains the
Linux release.

## Set up on your Fedora boot

Extract the new archive, open a terminal in its `ControlCenterLinux` folder,
and run as your normal user:

```bash
bash setup-fedora.sh
control-center-clone
```

Paths with spaces are supported.
Setup installs the desktop dependencies, app, launcher and root-owned helpers
first. It then builds the driver in a temporary directory, signs it with an
existing enrolled key, installs it for the running kernel and loads it. It adds a
boot-load entry for the bridge; loading the bridge applies no settings.

Setup saves `setup-fedora.log` in this extracted folder. If a later driver step
fails, the desktop app remains installed and the error identifies the failed step.

### If the terminal says `control-center-clone: command not found`

The launcher was not installed, or `/usr/local/bin` is absent from that shell's
PATH. The diagnostic command can work without installation or GTK, so a saved
diagnostic does not confirm that setup finished. From the extracted folder:

```bash
sudo bash install-fedora.sh
/usr/local/bin/control-center-clone
```

To launch directly from the extracted source, use `python3 main.py` (as your
normal desktop user), or `bash ./control-center-clone`.
The direct source launch still requires the desktop dependencies; protected
writes need the installed helpers, and firmware controls need a loaded driver.
Read `setup-fedora.log` if driver setup did not complete; rerunning only the
diagnostic will not install or load the driver.

By default setup looks for a signing key and certificate at these paths:

```text
/etc/pki/mok/ControlCenterLinux.priv
/etc/pki/mok/ControlCenterLinux.der
```

If your enrolled key is elsewhere:

```bash
CC_MODULE_KEY=/path/to/key.priv CC_MODULE_CERT=/path/to/certificate.der bash setup-fedora.sh
```

Setup does not generate/enroll keys or change Secure Boot. If Secure Boot is
enabled and the key is missing or not enrolled, it stops with instructions.
The kernel still verifies module trust. Build the driver included in this
release; no prebuilt `.ko` is bundled.
After a kernel update, rerun setup to build/sign for the new running kernel.

Setup checks the affirmative enrollment message because some `mokutil`
versions return a nonzero exit status for an already enrolled certificate.

This is a source install for a regular DNF-based Fedora desktop. Immutable
Fedora variants need their own host installation workflow. The installer has been checked in a temporary staged filesystem with ownership
changes stubbed; no root Fedora installation was performed from this workspace.

## Implemented controls

| Section | Implementation |
| --- | --- |
| System | CPU/GPU telemetry, RAM/storage/batteries, temperatures and fans; Acer performance profiles and Linux PPD/TuneD profiles; fan modes, offset and curves; keyboard flags, webcam, GNOME touchpad, display brightness and audio/microphone; diagnostic export and expandable details |
| Keyboard Backlight | Draft-only keyboard preview, 36 presets, rainbow hue slider and custom RGB picker; static RGB, brightness 0–4, sleep timer and generic Linux keyboard LED controls |
| FlexiCharger | Live battery gauge; recommended 70–80%, custom advertised thresholds, disable limits with 95–100%; generic battery thresholds |

Controls appear when the loaded driver exposes their readable interfaces.
Changing drafts does nothing until Apply. Refresh updates readings without
resetting drafts; **Refresh devices** rebuilds controls from current state.
The GUI runs as your normal user. Installation adds a Polkit action authorizing
only `/opt/control-center-clone/core.py` from the active local desktop, so
hardware changes do not ask for your password every time. Inactive and remote
sessions are denied. This executable is root-owned and starts Python in isolated
mode; it validates the action, device, value and kernel path on every call.
Kernel setters also validate requests and serialize complete transactions.
No general interpreter or shell receives password-free authorization. See the
[Polkit execution documentation](https://polkit.pages.freedesktop.org/polkit/pkexec.1.html)
for executable-specific actions.

Custom curves preserve both native endpoints, including the captured GPU
endpoint of 99°C/100%. Applying selects and verifies Maximum, uploads and
checks the curve, then selects Custom. A failed upload can leave Maximum
requested; refresh current state before another action. Charging updates verify
the complete configuration. Keyboard flag changes preserve unrelated flags.
There is no raw ACPI command, EC memory or overclocking interface.

## What has been verified

The native Fedora 44 / kernel 7.1.8-200.fc44 probe established live
firmware getters: fan readings 2275/2218 RPM, temperatures 60/20°C, and enabled
70–80% charging state. See [the report](FEDORA_REPORT.md).

The project owner reports that installation and controls work on the tested
Fedora laptop. Offline checks also exercised the C encoder, simulated sysfs,
helper boundaries, policy scope and GTK Apply routing. This does not establish
compatibility with other hardware, firmware or kernel versions.

Once installed on Fedora, check Maximum then Automatic fans, a visible RGB and
brightness change, and charging readback. Export diagnostics after trying the
controls: acknowledged actions and resulting raw firmware state are included.
The baseline diagnostic remains read-only and does not need GTK or root:

```bash
python3 main.py --diagnose --output control-center-fedora-diagnostics.json
```

Firmware performance profiles are implemented, but Linux desktop policy is
separate. Windows FnKey's optional GPU/ASPM/power-plan orchestration is not
reproduced identically. RGB and brightness return command acknowledgements and
raw EC values; keyboard sleep reports the last acknowledged timeout this module
load, not an independently measured elapsed timeout. The low captured GPU
temperature needs comparison when that GPU is active. Unsupported lighting
effects, Fn+number features, USB sleep charging and tuning are not advertised
for this verified machine and are not exposed.

[Driver build/signing instructions](driver/README.md) ·
[Firmware protocol evidence](driver/PROTOCOL.md)
