# AL15G-52 Linux control protocol — release 0.5.1

This is an original Linux adapter for Acer Aspire Lite AL15G-52, BIOS
1.07.01RAC2, two fans and type-6 keyboard. It uses the same firmware transport
as the Windows clone. No Windows DLL or kernel driver is loaded on Linux.

## Evidence

The tested laptop's DSDT was exported through Windows' firmware-table API and
disassembled by ACPICA iASL 20260408. The original disassembly and manifest are
not included in this repository. Relevant locations in the analyzed DSDT were:

- `_SB.DCHU._DSM`, line 102195: UUID
  `93f224e4-fbdc-4bbf-add6-db71bdc0afad`; dispatches functions to PK04, PK0E,
  GCMD and SCMD.
- PK04, lines 102884–103059: keyboard getter 24/setter 25; charging getter
  30/setter 31. Charging setter buffer is `{31,enabled,start,stop}`. Keyboard
  setter is `{25,fn,windows,swap,other,other}`; only the first three flags are
  exposed by this model's adapter.
- PK0D, line 103221: raw RGB, brightness, fan mode and curve knots. The native
  capture returns fan mode 2 for Automatic. SCMD 121/subcommand 1 maps
  Automatic 0 to EC mode 2, Maximum 1 to 16, Custom 6 to 4.
- PK0E, line 103276: classic curve upload. It writes the two middle knots and
  slopes. It does not write the first/final knots; those remain firmware-owned.
- SCMD, lines 106437–106618: function 103 receives a little-endian DWORD.
  Subcommands 240/241/242 set the three zones; 244 sets brightness. The original
  managed caller's type-6 encoding is B/2, R/2, G/2 in DWORD bytes 2/1/0.
  The green/turquoise correction matches the installed caller.
- SCMD 121, line 107050 onwards: subcommands 1 (fan mode), 14 (offset),
  24 (keyboard sleep) and 25 (performance profile). Offset writes GFOF; profile
  writes the CPCM AML variable and dispatches the firmware transition. Existing
  DTT selection is preserved for Performance; no turbo/overclocking option is added.
- Camera: GCMD 6 is the status getter; SCMD 34 is the setter. A getter value
  other than 0/1 is unavailable, rather than an assumed switch state.

REA/Ghidra 12.1.4 decompiled `SetDCHU_Data` at `0x1800028a0` and
`SetDCHU_DataEx` at `0x180002ae0` from the pinned native library, SHA-256
`dab807b5d4a621893ef5c5c1941e9d8ce91dda6b2518e931f4bb4727dfd80e98`.
The associated analysis record is not included in this repository.
Both exports copy supplied bytes into a zeroed 256-byte buffer and invoke
the same UUID, revision 0, requested function and one-buffer package. SetData
checks integer acknowledgements; SetDataEx's returned function number is not
proof that a setter succeeded. The Linux bridge therefore checks response
types and acknowledgements itself and verifies semantic readback where present.

Managed call layouts were also examined during development; those files are not
included here. Recovered pseudocode is not original vendor source. No setter
was executed during static analysis.

## Typed sysfs ABI 2

Attributes live beneath the bound CLV0001 device's `control_center` directory.
Raw telemetry/specs/charging getters remain available from ABI 1. The following
attributes are readable by users and writable only by root (0644).
There is no arbitrary function selector, payload, ACPI path or EC memory API.

| Attribute | Write value | Read value / confirmation |
| --- | --- | --- |
| `fan_mode` | `0` Automatic or `1` Maximum | Logical 0/1/6, derived from live firmware mode |
| `fan_offset` | Percentage 0–100, Automatic only | Raw GFOF 0–255, read through a fixed AML object |
| `fan_curve` | CPU T2,D2,T3,D3 followed by GPU T2,D2,T3,D3 (8 decimal values) | All four knots for each fan (16 T/duty-percent values) |
| `keyboard_rgb` | R G B, each 0–255 | Nine raw EC RGB bytes for left/middle/right zones |
| `keyboard_brightness` | Level 0–4 | Raw KBBH byte, not a fabricated logical level |
| `charge_limits` | Enabled Start Stop | Live charging getter; exact configuration verified |
| `keyboard_flags` | Index 0 Fn-lock / 1 Windows-key / 2 swap, then enabled 0/1 | Three raw 1/2 flags; complete five-byte flag readback checked |
| `keyboard_sleep` | 0 off, or 5–7199 seconds | Last acknowledged request this module load; -1 before any request |
| `camera` | 0 off or 1 on | Live firmware status, unavailable if getter is unsupported |
| `power_mode` | 0 Quiet / 1 Power Saving / 2 Performance / 3 Entertainment | Firmware CPCM state, not measured CPU/GPU performance |

The entire validate/read-modify-write/readback transaction holds one mutex.
Charging choices must come from the current getter; disabling uses the original
95–100% payload. Keyboard changes preserve unselected flags. Offsets require
Automatic and the firmware feature-96 gate. No writes occur at module load,
unload, app startup, refresh or diagnostic export.

Curves require increasing temperatures and duties, preserve the actual native
endpoints (GPU ends at 99°C in the supplied capture), and do not expose zero-duty
manual control. The driver validates the entire curve before mutation, selects
Maximum and verifies it, uploads the curve, verifies the middle knots, then
selects Custom. An upload/readback failure after Maximum leaves maximum cooling
requested. A multi-step failure can partially apply: the UI reports failure and
the user should refresh before retrying. Firmware thermal overrides remain active.

Lighting and sleep expose command acknowledgements with raw/cached state;
logical scaling, visible color and elapsed-time behavior still need target
validation. Saved Windows preferences are not copied into firmware or presented
as independent Linux readback. Successful readback never claims physical effect.

## Validation boundary and parity

The Fedora 44 probe establishes that the original three getters worked
on kernel 7.1.8-200.fc44.x86_64. The ABI 2 C encoder is compiled and exercised
offline with those captured buffers; the complete module is compiled against
the extracted Linux 7.0.0-14 headers. New setters have **not been executed on
the Acer under Fedora during this implementation**. Fedora builds/signs the
module for its running kernel when the user runs setup.

Firmware profiles and desktop PPD/TuneD policy have separate controls. Windows
FnKey's conditional GPU profiles, ASPM and Windows power-plan orchestration are
not identical to this Linux transition. Unsupported breathing/cycle effects,
Fn+number controls, USB sleep charging and overclocking are not exposed for
this machine. Flexikey and its input worker are not included in the Linux
application.

References: [Linux ACPI API](https://github.com/torvalds/linux/blob/master/include/linux/acpi.h),
[module signing](https://docs.kernel.org/admin-guide/module-signing.html).
