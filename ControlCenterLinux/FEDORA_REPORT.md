# Native Fedora observations for release 0.5.1

The firmware probe was run on one Acer Aspire Lite AL15G-52 with BIOS
`1.07.01RAC2`, Fedora 44 Workstation, and kernel `7.1.8-200.fc44.x86_64`.
The original diagnostic files are not included; the observations below are a
summary of that test. The project owner subsequently reported that installation
and controls work on the tested laptop. This does not establish compatibility
with other models, BIOS releases, or kernels.

| Observation | Interpretation at the time of the probe |
| --- | --- |
| `CLV0001` bound to `acer_al15g52` | The firmware bridge loaded and returned data. |
| Two fans and type-6 keyboard reported | The response matched the expected hardware identity. |
| Fan readings 2275/2218 RPM and firmware temperatures 60/20°C | Readings were obtained; the low GPU temperature needs comparison when the GPU is active. |
| FlexiCharger enabled at 70–80% and battery at 80%, not charging | The reported charging state was consistent with the battery snapshot. |
| No standard Linux fan, keyboard LED or battery threshold interfaces found | The generic Linux interfaces alone did not provide those controls on that boot. |

The original probe established getter behavior; it did not by itself verify
physical effects of setter commands. The owner later reported working controls,
but exact results can vary by hardware and environment. See the
[driver protocol](driver/PROTOCOL.md) for readback limitations and the
[installation guide](../README.md) for compatibility and setup instructions.
