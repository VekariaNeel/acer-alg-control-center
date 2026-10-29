# Release notes — 0.5.1

Control Center for Fedora brings system monitoring, supported fan and
performance controls, keyboard backlight settings, and FlexiCharger battery
limits together in a GTK application.

The 0.5.1 release includes a keyboard lighting palette with 36 presets, a
rainbow hue slider, a custom RGB color picker, and a preview. Changes are sent
to the device when you select Apply.

The source package includes the application, Fedora installation scripts,
and the model-specific kernel driver source. The setup script builds the driver
for the running kernel; no prebuilt kernel module or signing key is included.
See the [README](README.md) for compatibility checks and installation.

The supported target is Acer Aspire Lite AL15G-52 with BIOS `1.07.01RAC2` and
the expected firmware and hardware identity. The owner reports working
installation and controls on the tested Fedora laptop. Other models, BIOS
versions, and kernels are not established as compatible. Screenshots use
simulated device data.
