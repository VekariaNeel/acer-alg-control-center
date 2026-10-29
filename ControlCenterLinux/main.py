#!/usr/bin/python3
"""Fedora GTK 4 Control Center. Startup and refresh only read hardware state."""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Control Center Clone for Fedora")
    parser.add_argument("--diagnose", action="store_true", help="Export read-only hardware/driver evidence without GTK")
    parser.add_argument("--output", type=Path, help="Diagnostic JSON output path")
    args = parser.parse_args()
    if platform.system() != "Linux":
        parser.error("This application runs on Linux. The Windows WPF clone remains available separately.")
    if args.output and not args.diagnose:
        parser.error("--output requires --diagnose.")
    from core import LinuxHardware, VERSION
    if args.diagnose:
        # No GUI, command runner, elevation or service activation is needed.
        output = json.dumps(LinuxHardware().snapshot(), indent=2) + "\n"
        try:
            if args.output:
                args.output.write_text(output, encoding="utf-8")
                print(f"Read-only diagnostics saved to {args.output.resolve()}")
            else:
                print(output, end="")
            return 0
        except OSError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if os.geteuid() == 0:
        parser.error("Run the desktop app as your normal user.")
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gdk, Gio, GLib, Gtk
    except (ImportError, ValueError):
        print("Install the Fedora UI dependencies: sudo dnf install python3-gobject gtk4", file=sys.stderr)
        return 1
    from services import DesktopServices
    from ui import COLOR_PRESETS, battery_preview, color_swatch, keyboard_preview

    def label(text, css=None):
        widget = Gtk.Label(label=text, xalign=0, wrap=True, selectable=True)
        if css:
            widget.add_css_class(css)
        return widget

    def box(spacing=12, horizontal=False):
        return Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL if horizontal else Gtk.Orientation.VERTICAL,
                       spacing=spacing)

    def fmt(value, suffix="", digits=0):
        return "Unavailable" if value is None else f"{value:.{digits}f}{suffix}"

    class ControlCenter(Gtk.Application):
        def __init__(self):
            super().__init__(application_id="local.controlcenter.Fedora", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
            self.services = DesktopServices()
            self.state = None
            self.busy = False
            self.pending_apply = None
            self.closed = False
            self.pages = []
            self.controls = []
            self.preview_controls = []
            self.action_history = []
            self.syncing_color = False

        def do_activate(self):
            if getattr(self, "window", None):
                self.window.present()
                return
            self.window = Gtk.ApplicationWindow(application=self, title="Control Center · Fedora")
            self.window.set_default_size(1180, 850)
            self.window.set_size_request(960, 680)
            self.window.connect("close-request", self.on_close)
            header = Gtk.HeaderBar()
            header_title = label("Control Center")
            header_title.set_wrap(False)
            header.set_title_widget(header_title)
            self.refresh_button = Gtk.Button(label="Refresh devices")
            self.refresh_button.add_css_class("flat")
            self.refresh_button.set_tooltip_text("Discover devices again and reload controls")
            self.refresh_button.connect("clicked", lambda _: self.refresh(True))
            header.pack_end(self.refresh_button)
            self.window.set_titlebar(header)
            root = box(0, True)
            self.window.set_child(root)
            rail = box(8)
            rail.add_css_class("rail")
            rail.set_size_request(218, -1)
            brand = box(12, True)
            brand.append(label("C", "brand-mark"))
            brand_text = box(2)
            brand_text.append(label("Control Center", "brand"))
            brand_text.append(label("LINUX EDITION", "device-note"))
            brand.append(brand_text)
            rail.append(brand)
            rail.append(label("WORKSPACE", "eyebrow"))
            self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                                   transition_duration=180, hexpand=True, vexpand=True)
            self.nav_buttons = {}
            for name, title, description, icon in (
                    ("system", "System", "Monitor & performance", "computer-symbolic"),
                    ("keyboard", "Keyboard Backlight", "Color & brightness", "input-keyboard-symbolic"),
                    ("charging", "FlexiCharger", "Battery & charge limits", "battery-symbolic")):
                button = Gtk.ToggleButton()
                button.add_css_class("nav")
                row = box(12, True)
                row.append(Gtk.Image(icon_name=icon, pixel_size=20))
                captions = box(0)
                captions.append(label(title, "nav-title"))
                captions.append(label(description, "nav-description"))
                row.append(captions)
                button.set_child(row)
                button.set_tooltip_text(title)
                button.connect("toggled", lambda button, name=name: self.stack.set_visible_child_name(name) if button.get_active() else None)
                rail.append(button)
                self.nav_buttons[name] = button
            self.stack.connect("notify::visible-child-name", self.sync_navigation)
            spacer = box()
            spacer.set_vexpand(True)
            rail.append(spacer)
            device = box(8)
            device.add_css_class("device")
            device.append(label("YOUR DEVICE", "device-note"))
            self.device_name = label("Detecting hardware…", "device-title")
            self.connection = label("Reading device interfaces", "device-note")
            device.append(self.device_name)
            device.append(self.connection)
            rail.append(device)
            edition = label("Fedora / Linux  ·  " + VERSION, "device-note")
            edition.set_margin_top(12)
            rail.append(edition)
            root.append(rail)
            body = box(0)
            body.set_hexpand(True)
            body.append(self.stack)
            statusbar = box(10, True)
            statusbar.add_css_class("statusbar")
            statusbar.append(Gtk.Image(icon_name="dialog-information-symbolic", pixel_size=14))
            self.status = label("Reading your hardware…", "status")
            self.status.set_hexpand(True)
            statusbar.append(self.status)
            body.append(statusbar)
            root.append(body)
            provider = Gtk.CssProvider()
            provider.load_from_path(str(Path(__file__).with_name("style.css")))
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                      Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            settings = Gtk.Settings.get_default()
            settings.set_property("gtk-application-prefer-dark-theme", True)
            self.window.present()
            self.refresh(True)
            GLib.timeout_add_seconds(4, self.tick)

        def on_close(self, *_):
            self.closed = True
            return False

        def tick(self):
            if self.closed:
                return False
            self.refresh(False)
            return True

        def work(self, operation, done, applying=False):
            if self.busy:
                return
            self.busy = True
            self.refresh_button.set_sensitive(False)
            if applying:
                for widget in self.controls + self.preview_controls:
                    widget.set_sensitive(False)

            def worker():
                try:
                    result, error = operation(), None
                except Exception as exc:
                    result, error = None, str(exc)
                GLib.idle_add(complete, result, error)

            def complete(result, error):
                self.busy = False
                if self.closed:
                    return False
                self.refresh_button.set_sensitive(True)
                if applying:
                    for widget in self.controls + self.preview_controls:
                        widget.set_sensitive(True)
                if error:
                    self.status.set_text(error)
                    self.status.add_css_class("error")
                else:
                    done(result)
                if self.pending_apply is not None:
                    pending, self.pending_apply = self.pending_apply, None
                    GLib.idle_add(self.apply, pending)
                return False

            threading.Thread(target=worker, daemon=True).start()

        def refresh(self, rebuild):
            def done(state):
                self.state = state
                if rebuild:
                    self.build_pages()
                    self.status.set_text("Up to date. Changes take effect when you select Apply.")
                    self.status.remove_css_class("error")
                self.update_metrics()
            self.work(self.services.snapshot, done)

        def apply(self, operation):
            if self.busy:
                if self.pending_apply is None:
                    self.pending_apply = operation
                    self.status.set_text("Setting queued until the current refresh finishes.")
                else:
                    self.status.set_text("A setting is already queued. Wait for it to finish.")
                return False
            self.status.set_text("Applying requested setting…")
            self.status.remove_css_class("error")

            def operation_and_read():
                result = operation()
                return result, self.services.snapshot()

            def done(pair):
                result, self.state = pair
                self.action_history.append(dict(utc=datetime.now(timezone.utc).isoformat(), result=result))
                self.action_history = self.action_history[-100:]
                self.status.set_text("Setting applied. Device readings refreshed.")
                self.status.set_tooltip_text(json.dumps(result, ensure_ascii=False))
                self.update_metrics()
            self.work(operation_and_read, done, applying=True)
            return False

        def sync_navigation(self, *_):
            active = self.stack.get_visible_child_name()
            for name, button in self.nav_buttons.items():
                button.set_active(name == active)

        def page(self, name, title, description):
            content = box(18)
            for method in (content.set_margin_top, content.set_margin_bottom, content.set_margin_start, content.set_margin_end):
                method(30)
            content.append(label({"system": "YOUR DEVICE, AT A GLANCE", "keyboard": "SET THE MOOD", "charging": "A LITTLE CARE GOES A LONG WAY"}[name], "eyebrow"))
            heading = box(12, True)
            title_label = label(title, "title")
            title_label.set_hexpand(True)
            heading.append(title_label)
            heading.append(label({"system": "OVERVIEW", "keyboard": "LIGHTING", "charging": "BATTERY CARE"}[name], "badge"))
            content.append(heading)
            content.append(label(description, "subtitle"))
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            scroll.set_child(content)
            self.stack.add_titled(scroll, name, title)
            self.pages.append(scroll)
            return content

        def section(self, parent, title, expanded=False):
            expander = Gtk.Expander(expanded=expanded)
            expander.add_css_class("group")
            expander.set_label_widget(label(title, "section-title"))
            content = box(14)
            expander.set_child(content)
            parent.append(expander)
            return content

        def metric(self, parent, column, row, title):
            tile = box(4)
            tile.add_css_class("card")
            tile.add_css_class("metric")
            tile.append(label(title, "eyebrow"))
            value = label("—", "metric-value")
            tile.append(value)
            detail = label("", "metric-detail")
            tile.append(detail)
            parent.attach(tile, column, row, 1, 1)
            return value, detail

        def card(self, parent, title, description=None):
            content = box(10)
            content.add_css_class("card")
            content.append(label(title, "card-title"))
            if description:
                content.append(label(description, "subtitle"))
            parent.append(content)
            return content

        def button(self, parent, text, callback):
            button = Gtk.Button(label=text, halign=Gtk.Align.START)
            if text.startswith("Apply") or text == "Recommended 70–80%":
                button.add_css_class("primary")
            button.connect("clicked", lambda _: callback())
            parent.append(button)
            self.controls.append(button)
            return button

        def spin(self, parent, title, current, maximum, minimum=0):
            row = box(12, True)
            caption = label(title)
            caption.set_hexpand(True)
            row.append(caption)
            widget = Gtk.SpinButton.new_with_range(minimum, maximum, 1)
            widget.set_value(current if current is not None else minimum)
            row.append(widget)
            parent.append(row)
            self.controls.append(widget)
            return widget

        def brightness_card(self, parent, device, action):
            content = self.card(parent, device["id"], "Set a draft value, then Apply. Refresh devices reloads draft controls.")
            maximum = device["maximum"]
            if not device["writable"] or not maximum or device["value"] is None:
                content.append(label("The driver does not expose a readable, writable brightness range."))
                return content
            spin = self.spin(content, f"Brightness (0–{maximum})", device["value"], maximum)

            def apply_brightness():
                value = spin.get_value_as_int()
                self.apply(lambda: self.services.apply_hardware(action, device["id"], value))
            self.button(content, "Apply brightness", apply_brightness)
            return content

        def acer_control(self, name):
            control = self.state.get("acer", {}).get("controls", {}).get(name, {})
            return control if control.get("available") and control.get("writable") else None

        def acer_apply(self, action, values):
            self.apply(lambda: self.services.apply_hardware(action, "CLV0001:00", values))

        def acer_power_controls(self, page):
            control = self.acer_control("power_mode")
            if not control:
                return
            content = self.card(page, "Acer firmware performance profile",
                                "Changes the firmware profile. Linux desktop power policy remains a separate control below.")
            names = ["Quiet", "Power Saving", "Performance", "Entertainment"]
            selection = Gtk.DropDown.new_from_strings(names)
            selection.set_selected(control["values"][0])
            content.append(selection)
            self.controls.append(selection)
            self.button(content, "Apply firmware profile", lambda: self.acer_apply("acer-power", selection.get_selected()))

        def acer_cooling_controls(self, page):
            control = self.acer_control("fan_mode")
            if not control:
                self.card(page, "Acer fan controls", "Load the new ABI 2 module to enable Automatic, Maximum, curves and offset.")
                return
            content = self.card(page, "Fan mode", "Automatic follows firmware policy. Maximum requests full cooling.")
            self.button(content, "Automatic fans", lambda: self.acer_apply("acer-fan", 0))
            self.button(content, "Maximum fans", lambda: self.acer_apply("acer-fan", 1))
            control = self.acer_control("fan_offset")
            if control:
                content = self.card(page, "Automatic fan offset", "Select Automatic first. Adds cooling demand to the firmware's automatic policy.")
                offset = self.spin(content, "Offset (%)", round(control["values"][0] * 100 / 255), 100)
                self.button(content, "Apply fan offset", lambda: self.acer_apply("acer-offset", offset.get_value_as_int()))
            control = self.acer_control("fan_curve")
            if control:
                content = self.card(page, "Custom CPU and GPU curves",
                                    "Edit the two middle knots. The first firmware knot and maximum-cooling endpoint stay fixed. "
                                    "Applying uses Maximum during upload and verifies the curve before selecting Custom.")
                fields = []
                for fan, name in enumerate(("CPU", "GPU")):
                    values = control["values"][fan * 8:fan * 8 + 8]
                    content.append(label(f"{name}: fixed start {values[0]}°C / {values[1]}%, end {values[6]}°C / {values[7]}%"))
                    for point in (1, 2):
                        fields.append(self.spin(content, f"{name} point {point + 1} temperature (°C)", values[point * 2], 99, 20))
                        fields.append(self.spin(content, f"{name} point {point + 1} duty (%)", values[point * 2 + 1], 99, 1))
                self.button(content, "Apply custom curves", lambda: self.acer_apply("acer-curve", [w.get_value_as_int() for w in fields]))

        def acer_keyboard_controls(self, page):
            if self.acer_control("keyboard_brightness"):
                content = self.keyboard_panel
                raw = self.acer_control("keyboard_brightness")["values"][0]
                levels = (0, 47, 95, 143, 191)
                level = self.spin(content, "Brightness (0 off, 1–4)", min(range(5), key=lambda i: abs(levels[i] - raw)), 4)
                self.keyboard_level = level
                level.connect("value-changed", lambda spin: self.preview_brightness(spin.get_value_as_int()))
                self.button(level.get_parent(), "Apply brightness", lambda: self.acer_apply("acer-brightness", level.get_value_as_int()))
                if self.acer_control("keyboard_rgb"):
                    entry = Gtk.Entry(placeholder_text="#RRGGBB", hexpand=True)
                    self.keyboard_color_entry = entry
                    entry.set_text("#" + "".join(f"{v:02X}" for v in self.acer_control("keyboard_rgb")["values"][:3]))
                    entry.connect("changed", lambda entry: self.preview_color(entry.get_text()))
                    color_row = box(10, True)
                    color_row.append(entry)
                    content.append(color_row)
                    self.controls.append(entry)
                    palette_heading = box(12, True)
                    palette_caption = label("COLOR PALETTE", "eyebrow")
                    palette_caption.set_wrap(False)
                    palette_heading.append(palette_caption)
                    self.selected_color_label = label("", "metric-detail")
                    self.selected_color_label.set_hexpand(True)
                    self.selected_color_label.set_xalign(1)
                    palette_heading.append(self.selected_color_label)
                    content.append(palette_heading)
                    self.hue_slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 360, 1)
                    self.hue_slider.set_draw_value(False)
                    self.hue_slider.add_css_class("hue-slider")
                    self.hue_slider.set_tooltip_text("Choose a hue from the full rainbow · preview only")
                    self.hue_slider.update_property([Gtk.AccessibleProperty.LABEL], ["Rainbow hue"])
                    self.hue_slider.connect("value-changed", self.select_hue)
                    self.preview_controls.append(self.hue_slider)
                    content.append(self.hue_slider)
                    swatches = Gtk.Grid(column_spacing=5, row_spacing=5, column_homogeneous=True)
                    self.palette_buttons = {}
                    for index, (name, color) in enumerate(COLOR_PRESETS):
                        swatch = Gtk.Button(hexpand=True)
                        swatch.add_css_class("palette-swatch")
                        swatch.set_child(color_swatch(color))
                        self.preview_controls.append(swatch)
                        swatch.set_tooltip_text(name + " · " + color + " · preview only")
                        swatch.update_property([Gtk.AccessibleProperty.LABEL], [name + " " + color])
                        swatch.connect("clicked", lambda _, color=color: entry.set_text(color))
                        swatches.attach(swatch, index % 12, index // 12, 1, 1)
                        self.palette_buttons[color] = swatch
                    content.append(swatches)
                    custom = box(10, True)
                    custom_caption = label("Custom color", "metric-detail")
                    custom_caption.set_hexpand(True)
                    custom.append(custom_caption)
                    dialog = Gtk.ColorDialog(title="Choose keyboard backlight color", with_alpha=False)
                    self.color_picker = Gtk.ColorDialogButton(dialog=dialog)
                    self.color_picker.set_tooltip_text("Choose any RGB color · preview only")
                    self.color_picker.update_property([Gtk.AccessibleProperty.LABEL], ["Choose custom keyboard color"])
                    self.color_picker.connect("notify::rgba", self.select_custom_color)
                    self.preview_controls.append(self.color_picker)
                    custom.append(self.color_picker)
                    content.append(custom)
                    self.preview_color(entry.get_text())

                    def apply_color():
                        import re
                        color = entry.get_text().strip().removeprefix("#")
                        if not re.fullmatch("[0-9a-fA-F]{6}", color):
                            self.status.set_text("Enter a six-digit RGB color, for example #007FC8.")
                            return
                        self.acer_apply("acer-rgb", [int(color[i:i + 2], 16) for i in (0, 2, 4)])
                    self.button(color_row, "Apply color", apply_color)

            control = self.acer_control("keyboard_sleep")
            if control:
                timer = self.section(page, "Keyboard sleep timer")
                content = self.card(timer, "Turn off lighting when idle", "Use zero to keep the backlight on, or set a timeout from 5 to 7199 seconds.")
                seconds = self.spin(content, "Timeout (seconds)", max(0, control["values"][0]) if control["values"][0] >= 0 else 30, 7199)
                self.button(content, "Apply keyboard sleep", lambda: self.acer_apply("acer-sleep", seconds.get_value_as_int()))

        def acer_charging_controls(self, page):
            if not self.acer_control("charge_limits"):
                return
            charge = self.state["acer"]["charging"]
            if not charge.get("available"):
                return
            content = self.card(page, "Acer FlexiCharger limits", "Choose firmware-advertised thresholds. Applying verifies the returned charge configuration.")
            starts, stops = charge["allowed_starts"], charge["allowed_stops"]
            start = Gtk.DropDown.new_from_strings([f"Start {v}%" for v in starts])
            stop = Gtk.DropDown.new_from_strings([f"Stop {v}%" for v in stops])
            start.set_selected(starts.index(charge["start"]) if charge["start"] in starts else 0)
            stop.set_selected(stops.index(charge["stop"]) if charge["stop"] in stops else 0)
            thresholds = box(12, True)
            start.set_hexpand(True)
            stop.set_hexpand(True)
            thresholds.append(start)
            thresholds.append(stop)
            content.append(thresholds)
            self.controls.extend((start, stop))
            actions = box(10, True)
            content.append(actions)
            self.button(actions, "Apply charging limits", lambda: self.acer_apply("acer-charge", [1, starts[start.get_selected()], stops[stop.get_selected()]]))
            self.button(actions, "Recommended 70–80%", lambda: self.acer_apply("acer-charge", [1, 70, 80]))
            self.button(content, "Disable Acer limits (95–100%)", lambda: self.acer_apply("acer-charge", [0, 95, 100]))

        def acer_configuration_controls(self, page):
            control = self.acer_control("keyboard_flags")
            if control:
                content = self.card(page, "Firmware keyboard options", "Changing one option preserves the other firmware flags.")
                for index, title in enumerate(("Fn lock", "Windows/Super key enabled", "Swap Fn and Windows/Super")):
                    toggle = Gtk.CheckButton(label=title)
                    toggle.set_active(control["values"][index] == (2 if index == 1 else 1))
                    content.append(toggle)
                    self.controls.append(toggle)
                    self.button(content, "Apply " + title, lambda index=index, toggle=toggle: self.acer_apply("acer-flags", [index, int(toggle.get_active())]))
            control = self.acer_control("camera")
            if control:
                content = self.card(page, "Firmware webcam switch")
                toggle = Gtk.CheckButton(label="Webcam enabled")
                toggle.set_active(control["values"][0] == 1)
                content.append(toggle)
                self.controls.append(toggle)
                self.button(content, "Apply webcam state", lambda: self.acer_apply("acer-camera", int(toggle.get_active())))

        def build_pages(self):
            active = self.stack.get_visible_child_name()
            for child in self.pages:
                self.stack.remove(child)
            self.pages, self.controls, self.preview_controls = [], [], []
            state = self.state
            system_page = self.page("system", "System", "Your laptop's health, performance and everyday controls.")
            overview = Gtk.Grid(column_spacing=16, row_spacing=16, column_homogeneous=True)
            system_page.append(overview)
            self.cpu_value, self.system_metrics = self.metric(overview, 0, 0, "PROCESSOR")
            self.memory_value, self.memory_detail = self.metric(overview, 1, 0, "MEMORY & STORAGE")
            self.gpu_value, self.gpu_metrics = self.metric(overview, 0, 1, "GRAPHICS")
            self.battery_value, self.battery_metrics = self.metric(overview, 1, 1, "BATTERY")
            thermal = self.card(system_page, "Thermals & cooling")
            readings = box(20, True)
            self.temperature_metrics = label("", "metric-detail")
            self.temperature_metrics.set_hexpand(True)
            self.fan_metrics = label("", "metric-detail")
            self.fan_metrics.set_hexpand(True)
            readings.append(self.temperature_metrics)
            readings.append(self.fan_metrics)
            thermal.append(readings)
            page = self.section(system_page, "Performance profiles", expanded=True)
            self.acer_power_controls(page)
            self.power_current = label("")
            content = self.card(page, "Linux power profile", "These service profiles do not establish equivalence to the four Windows firmware modes.")
            content.append(self.power_current)
            power = state["power"]
            if power["available"]:
                choices = power["choices"]
                selection = Gtk.DropDown.new_from_strings(choices)
                if power["active"] in choices:
                    selection.set_selected(choices.index(power["active"]))
                content.append(selection)
                self.controls.append(selection)

                def apply_profile():
                    profile = choices[selection.get_selected()]
                    self.apply(lambda: self.services.power.apply(profile))
                self.button(content, "Apply profile", apply_profile)
            else:
                content.append(label(power["error"]))

            page = self.section(system_page, "Fan controls & custom curves")
            self.acer_cooling_controls(page)
            acer = state.get("acer", {})
            self.card(page, "Acer firmware bridge", f"Acer bridge ABI {acer.get('abi_version', 1)} is connected." if acer.get("available") else
                      acer.get("reason", "See driver/README.md for the AL15G-52 read-only firmware probe."))
            self.vendor_current = label("")
            self.card(page, "Reported Acer controls").append(self.vendor_current)

            page = self.section(system_page, "Device & audio settings")
            self.acer_configuration_controls(page)
            touchpad = state.get("touchpad", {})
            if touchpad.get("available"):
                content = self.card(page, "Touchpad · GNOME session")
                touchpad_choices = ["enabled", "disabled", "disabled-on-external-mouse"]
                touchpad_selection = Gtk.DropDown.new_from_strings(touchpad_choices)
                touchpad_selection.set_selected(touchpad_choices.index(touchpad["mode"]))
                content.append(touchpad_selection)
                self.controls.append(touchpad_selection)
                self.button(content, "Apply touchpad mode", lambda: self.apply(lambda: self.services.apply_touchpad(touchpad_choices[touchpad_selection.get_selected()])))
            for device in state["displays"]:
                self.brightness_card(page, device, "display")
            if not state["displays"]:
                self.card(page, "Display brightness unavailable", "No Linux backlight device was detected.")
            content = self.card(page, "Audio · PipeWire / WirePlumber")
            self.audio_current = label("")
            content.append(self.audio_current)
            audio = state["audio"]
            if audio["available"]:
                volume = self.spin(content, "Playback volume (%)", min(audio["volume"], 100), 100)

                def apply_volume():
                    value = volume.get_value_as_int()
                    self.apply(lambda: self.services.apply_audio("volume", value))
                self.button(content, "Apply volume", apply_volume)
                self.button(content, "Mute speakers", lambda: self.apply(lambda: self.services.apply_audio("mute", True)))
                self.button(content, "Unmute speakers", lambda: self.apply(lambda: self.services.apply_audio("mute", False)))
            if state["microphone"]["available"]:
                self.button(content, "Mute microphone", lambda: self.apply(lambda: self.services.apply_audio("microphone_mute", True)))
                self.button(content, "Unmute microphone", lambda: self.apply(lambda: self.services.apply_audio("microphone_mute", False)))
            self.card(page, "Vendor device preferences", state["pending"]["fn_lock_camera_touchpad"])

            page = self.section(system_page, "Device details & diagnostics")
            content = self.card(page, "Diagnostics")
            self.button(content, "Export diagnostic JSON…", self.export)
            details = Gtk.Expander(label="Show hardware and service details")
            self.diagnostic_text = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
            details.set_child(self.diagnostic_text)
            content.append(details)

            page = self.page("keyboard", "Keyboard Backlight", "Find your color. Adjust the brightness. Make the keyboard feel like yours.")
            preview = self.card(page, "Lighting studio", "Preview your color and brightness. Select Apply when it feels right.")
            self.keyboard_panel = preview
            self.keyboard_preview = keyboard_preview()
            rgb = self.acer_control("keyboard_rgb")
            brightness = self.acer_control("keyboard_brightness")
            self.keyboard_preview.color = rgb["values"][:3] if rgb else [0, 0, 0]
            levels = (0, 47, 95, 143, 191)
            self.keyboard_preview.level = min(range(5), key=lambda i: abs(levels[i] - brightness["values"][0])) if brightness else 0
            self.keyboard_preview.refresh()
            preview.append(self.keyboard_preview)
            self.acer_keyboard_controls(page)
            if not state["keyboards"] and not self.acer_control("keyboard_brightness"):
                self.card(page, "Keyboard lighting unavailable", "No :kbd_backlight LED device was detected. "
                          "A compatible keyboard driver is required; Windows RGB support alone does not establish Linux support.")
            generic_keyboard = self.section(page, "Additional keyboard lighting") if state["keyboards"] else page
            for device in state["keyboards"]:
                content = self.brightness_card(generic_keyboard, device, "keyboard")
                if device["rgb"]:
                    entry = Gtk.Entry(placeholder_text="#RRGGBB")
                    entry.set_text("#FFFFFF")
                    content.append(entry)
                    content.append(label("Color is a draft. The backend follows the driver's RGB channel order."))
                    self.controls.append(entry)

                    def apply_rgb(device=device, entry=entry):
                        import re
                        color = entry.get_text().strip().removeprefix("#")
                        if not re.fullmatch("[0-9a-fA-F]{6}", color):
                            self.status.set_text("Enter a six-digit RGB color, for example #42A5FF.")
                            return
                        value = [int(color[i:i + 2], 16) for i in (0, 2, 4)]
                        self.apply(lambda: self.services.apply_hardware("rgb", device["id"], value))
                    self.button(content, "Apply RGB color", apply_rgb)
                else:
                    content.append(label("This LED device does not expose a writable three-channel RGB interface."))

            page = self.page("charging", "FlexiCharger", "Set a charging window that suits the way you use your laptop.")
            charge_hero = self.card(page, "Battery overview", "Live charge level and the limits currently reported by your device.")
            self.battery_preview = battery_preview()
            charge_hero.append(self.battery_preview)
            self.charge_current = label("", "metric-detail")
            charge_hero.append(self.charge_current)
            acer_charge = state.get("acer", {}).get("charging", {})
            if acer_charge.get("available"):
                self.acer_charge_current = label("")
                charge_hero.append(self.acer_charge_current)
            else:
                self.acer_charge_current = None
            self.acer_charging_controls(page)
            if not state["batteries"]:
                self.card(page, "No battery detected")
            generic_charging = self.section(page, "Additional battery controls") if state["batteries"] else page
            for device in state["batteries"]:
                content = self.card(generic_charging, device["id"], "Apply verifies the returned thresholds. "
                                    "Drivers can reject ranges or allow only particular values.")
                fields = {}
                if device["start_writable"] and device["start"] is not None:
                    fields["start"] = self.spin(content, "Start charging below (%)", device["start"], 100)
                if device["stop_writable"] and device["stop"] is not None:
                    fields["stop"] = self.spin(content, "Stop charging above (%)", device["stop"], 100)
                if fields:
                    def apply_charge(device=device, fields=fields):
                        values = {key: spin.get_value_as_int() for key, spin in fields.items()}
                        self.apply(lambda: self.services.apply_hardware("charge", device["id"], values))
                    self.button(content, "Apply charging limits", apply_charge)
                else:
                    content.append(label("No writable charge threshold interface is available from this battery driver."))

            if active:
                self.stack.set_visible_child_name(active)
            self.sync_navigation()

        def preview_color(self, text):
            import colorsys
            import re
            color = text.strip().removeprefix("#")
            if re.fullmatch("[0-9a-fA-F]{6}", color):
                self.keyboard_preview.color = [int(color[i:i + 2], 16) for i in (0, 2, 4)]
                self.keyboard_preview.refresh()
                if hasattr(self, "hue_slider"):
                    canonical = "#" + color.upper()
                    self.syncing_color = True
                    try:
                        hue, saturation, _ = colorsys.rgb_to_hsv(*(v / 255 for v in self.keyboard_preview.color))
                        if saturation:
                            self.hue_slider.set_value(hue * 360)
                        rgba = Gdk.RGBA()
                        rgba.parse(canonical)
                        self.color_picker.set_rgba(rgba)
                        for value, button in self.palette_buttons.items():
                            if value == canonical:
                                button.add_css_class("selected")
                            else:
                                button.remove_css_class("selected")
                        name = next((name for name, value in COLOR_PRESETS if value == canonical), "Custom")
                        self.selected_color_label.set_text(name + " · " + canonical)
                    finally:
                        self.syncing_color = False

        def select_hue(self, slider):
            import colorsys
            if not self.syncing_color:
                rgb = colorsys.hsv_to_rgb(slider.get_value() / 360, 1, 1)
                self.keyboard_color_entry.set_text("#" + "".join(f"{round(channel * 255):02X}" for channel in rgb))

        def select_custom_color(self, picker, *_):
            if not self.syncing_color:
                rgba = picker.get_rgba()
                self.keyboard_color_entry.set_text("#" + "".join(f"{round(channel * 255):02X}" for channel in (rgba.red, rgba.green, rgba.blue)))

        def preview_brightness(self, value):
            self.keyboard_preview.level = value
            self.keyboard_preview.refresh()

        def update_metrics(self):
            state, m = self.state, self.state["metrics"]
            self.cpu_value.set_text(fmt(m["cpu_percent"], "%") if m["cpu_percent"] is not None else "—")
            self.memory_value.set_text(fmt(m["memory_used_gib"], " GiB", 1))
            self.system_metrics.set_text((m.get("cpu_name") or "Processor") + "\n" + fmt(m["reported_clock_mhz"], " MHz"))
            self.memory_detail.set_text("of " + fmt(m["memory_total_gib"], " GiB", 1) + " memory\n" + fmt(m["disk_free_gib"], " GiB", 1) + " storage free")
            self.device_name.set_text(state.get("inventory", {}).get("dmi", {}).get("product_name") or "Linux device")
            self.connection.set_text("Acer bridge connected" if state.get("acer", {}).get("available") else "Standard Linux interfaces")
            capacities = [battery["capacity"] for battery in state["batteries"] if battery.get("capacity") is not None]
            capacity = capacities[0] if capacities else None
            self.battery_value.set_text(fmt(capacity, "%") if capacity is not None else "—")
            self.battery_preview.capacity = capacity
            self.battery_preview.refresh()
            gpu = state["gpu"]
            temperatures = [device["temperature"] for device in gpu["devices"] if device.get("temperature") is not None]
            self.gpu_value.set_text(fmt(temperatures[0], " °C") if temperatures else "—")
            self.gpu_metrics.set_text("\n".join(f"{g['name']} · {fmt(g['load'], '%')} · "
                                                f"{fmt(g['temperature'], ' °C')} · {fmt(g['clock_mhz'], ' MHz')}"
                                                for g in gpu["devices"]) or gpu.get("error", "Unavailable"))
            self.temperature_metrics.set_text("\n".join(f"{s['chip']} / {s['label']}   {fmt(s['value'], ' °C', 1)}"
                                                        for s in state["sensors"]["temperatures"]) or "No temperature sensors exposed.")
            self.fan_metrics.set_text("\n".join(f"{s['chip']} / {s['label']}   {fmt(s['value'], ' RPM')}"
                                                for s in state["sensors"]["fans"]) or "No fan tachometers exposed.")
            controls = state.get("acer", {}).get("controls", {})
            self.vendor_current.set_text("\n".join(f"{name.replace('_', ' ')}: " +
                                                  (" ".join(map(str, value["values"])) if value.get("available") else "Unavailable")
                                                  for name, value in controls.items()) or "ABI 2 controls are not connected.")
            battery = "\n".join(f"{b['id']}   {fmt(b['capacity'], '%')} · {b['status'] or 'Unknown status'}"
                                 for b in state["batteries"]) or "No battery detected."
            self.battery_metrics.set_text(battery)
            self.charge_current.set_text("\n".join(f"{b['id']} reported thresholds: start {fmt(b['start'], '%')} / stop {fmt(b['stop'], '%')}"
                                                   for b in state["batteries"]))
            if self.acer_charge_current is not None:
                charge = state.get("acer", {}).get("charging", {})
                self.acer_charge_current.set_text(
                    f"{'Enabled' if charge['enabled'] else 'Disabled'} · {charge['start']}–{charge['stop']}% · "
                    + ("controls available" if charge.get("writable") else "read-only bridge") if charge.get("available") else "Firmware charging state unavailable.")
            power = state["power"]
            self.power_current.set_text(f"Current: {power['active'] or 'Unavailable'}" +
                                        (f" · Performance degraded: {power['degraded']}" if power.get("degraded") else ""))
            audio = state["audio"]
            mic = state["microphone"]
            self.audio_current.set_text((f"Speakers: {audio['volume']}% · {'Muted' if audio['muted'] else 'Unmuted'}"
                                         if audio["available"] else "Speakers: " + audio["error"]) + "\n" +
                                        (f"Microphone: {'Muted' if mic['muted'] else 'Unmuted'}"
                                         if mic["available"] else "Microphone: " + mic["error"]))
            self.diagnostic_text.get_buffer().set_text(json.dumps(state, indent=2))

        def export(self):
            # FileChooserNative supports GTK 4 versions before FileDialog.
            chooser = Gtk.FileChooserNative(title="Save Linux diagnostics", transient_for=self.window,
                                            action=Gtk.FileChooserAction.SAVE,
                                            accept_label="Save", cancel_label="Cancel")
            chooser.set_current_name("control-center-fedora-diagnostics.json")

            def response(dialog, response_id):
                if response_id == Gtk.ResponseType.ACCEPT:
                    selected = dialog.get_file()
                    path = selected.get_path() if selected else None
                    try:
                        if path is None:
                            raise ValueError("Choose a local file for the diagnostic export.")
                        report = dict(self.state, exported_utc=datetime.now(timezone.utc).isoformat(),
                                      applied_actions=self.action_history)
                        Path(path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                        self.status.set_text(f"Diagnostics saved to {path}")
                    except (OSError, ValueError) as exc:
                        self.status.set_text(str(exc))
                dialog.destroy()
            chooser.connect("response", response)
            chooser.show()

    return ControlCenter().run([sys.argv[0]])


if __name__ == "__main__":
    raise SystemExit(main())
