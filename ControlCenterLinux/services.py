"""Desktop session controls. These always run as the logged-in user."""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from core import ControlError, LinuxHardware, integer


def run(args: list[str], timeout: int = 5) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                                check=False, env=os.environ | {"LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ControlError(str(exc)) from exc
    if result.returncode:
        raise ControlError(result.stderr.strip() or result.stdout.strip() or
                           f"{Path(args[0]).name} exited with {result.returncode}.")
    return result.stdout.strip()


class PowerProfiles:
    """The PPD D-Bus API is also implemented by Fedora's tuned-ppd."""
    ENDPOINTS = (
        ("org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles"),
        ("net.hadess.PowerProfiles", "/net/hadess/PowerProfiles"),
    )

    def __init__(self):
        self.endpoint = None

    @staticmethod
    def connection():
        # Keep core diagnostics usable with just the Python standard library.
        try:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio, GLib
        except (ImportError, ValueError) as exc:
            raise ControlError("Power profiles require python3-gobject and a desktop power service.") from exc
        return Gio, GLib, Gio.bus_get_sync(Gio.BusType.SYSTEM, None)

    def read(self) -> dict:
        try:
            Gio, GLib, bus = self.connection()
            errors = []
            for name, path in self.ENDPOINTS:
                try:
                    result = bus.call_sync(name, path, "org.freedesktop.DBus.Properties", "GetAll",
                                           GLib.Variant("(s)", (name,)), GLib.VariantType.new("(a{sv})"),
                                           Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
                    choices = [p["Profile"] for p in result.get("Profiles", []) if "Profile" in p]
                    if not choices:
                        raise ControlError("The service did not advertise any profiles.")
                    self.endpoint = name, path
                    return dict(available=True, choices=choices, active=result.get("ActiveProfile"),
                                degraded=result.get("PerformanceDegraded", ""), service=name)
                except Exception as exc:
                    errors.append(str(exc))
            raise ControlError("No PPD-compatible power service responded: " + "; ".join(errors))
        except Exception as exc:
            self.endpoint = None
            return dict(available=False, choices=[], active=None, error=str(exc))

    def apply(self, profile: str) -> dict:
        current = self.read()
        if not current["available"] or profile not in current["choices"] or self.endpoint is None:
            raise ControlError("Select a profile currently advertised by the power service.")
        Gio, GLib, bus = self.connection()
        name, path = self.endpoint
        try:
            bus.call_sync(name, path, "org.freedesktop.DBus.Properties", "Set",
                          GLib.Variant("(ssv)", (name, "ActiveProfile", GLib.Variant("s", profile))),
                          None, Gio.DBusCallFlags.NONE, 5000, None)
        except Exception as exc:
            raise ControlError(str(exc)) from exc
        actual = self.read()
        if actual["active"] != profile:
            raise ControlError(f"Power service returned {actual['active']!r}, requested {profile!r}.")
        return actual


class DesktopServices:
    def __init__(self, hardware: LinuxHardware | None = None, runner=run):
        self.hardware = hardware or LinuxHardware()
        self.run = runner
        self.power = PowerProfiles()

    def audio(self, source: bool = False) -> dict:
        target = "@DEFAULT_AUDIO_SOURCE@" if source else "@DEFAULT_AUDIO_SINK@"
        try:
            output = self.run(["wpctl", "get-volume", target])
            match = re.search(r"Volume:\s*([0-9.]+)", output)
            if match is None:
                raise ControlError("WirePlumber returned an unrecognized volume response.")
            return dict(available=True, volume=round(float(match[1]) * 100), muted="[MUTED]" in output)
        except (ControlError, ValueError) as exc:
            return dict(available=False, error=str(exc))

    def apply_audio(self, action: str, value) -> dict:
        source = action == "microphone_mute"
        target = "@DEFAULT_AUDIO_SOURCE@" if source else "@DEFAULT_AUDIO_SINK@"
        if action == "volume":
            self.run(["wpctl", "set-volume", "--limit", "1.0", target, f"{integer(value, 0, 100)}%"])
        elif action in ("mute", "microphone_mute") and type(value) is bool:
            self.run(["wpctl", "set-mute", target, "1" if value else "0"])
        else:
            raise ControlError("Invalid audio action or value.")
        actual = self.audio(source)
        if not actual["available"]:
            raise ControlError("Command completed but audio readback failed: " + actual["error"])
        key = "volume" if action == "volume" else "muted"
        if actual[key] != value:
            raise ControlError(f"Audio readback returned {key}={actual[key]!r}, requested {value!r}.")
        return actual

    def gpu(self) -> dict:
        try:
            output = self.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,temperature.gpu,"
                               "memory.used,memory.total,clocks.current.graphics", "--format=csv,noheader,nounits"])
            result = []
            for fields in csv.reader(output.splitlines()):
                if len(fields) != 6:
                    raise ControlError("Unexpected NVIDIA telemetry response.")
                item = {"name": fields[0].strip()}
                for key, raw in zip(("load", "temperature", "memory_used_mib", "memory_total_mib", "clock_mhz"), fields[1:]):
                    try:
                        item[key] = float(raw)
                    except ValueError:
                        item[key] = None
                result.append(item)
            return dict(available=bool(result), devices=result)
        except ControlError as exc:
            return dict(available=False, devices=[], error=str(exc))

    def snapshot(self) -> dict:
        state = self.hardware.snapshot()
        state.update(power=self.power.read(), audio=self.audio(), microphone=self.audio(True), gpu=self.gpu(),
                     touchpad=self.touchpad())
        return state

    def touchpad(self) -> dict:
        if "GNOME" not in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
            return dict(available=False, error="GNOME touchpad integration is available in a GNOME desktop session.")
        try:
            value = self.run(["gsettings", "get", "org.gnome.desktop.peripherals.touchpad", "send-events"]).strip("'")
            if value not in ("enabled", "disabled", "disabled-on-external-mouse"):
                raise ControlError("Unrecognized GNOME touchpad state.")
            return dict(available=True, mode=value, enabled=value == "enabled")
        except ControlError as exc:
            return dict(available=False, error=str(exc))

    def apply_touchpad(self, mode: str) -> dict:
        if mode not in ("enabled", "disabled", "disabled-on-external-mouse"):
            raise ControlError("Invalid touchpad mode.")
        current = self.touchpad()
        if not current["available"]:
            raise ControlError(current["error"])
        self.run(["gsettings", "set", "org.gnome.desktop.peripherals.touchpad", "send-events", mode])
        actual = self.touchpad()
        if actual.get("mode") != mode:
            raise ControlError("GNOME did not confirm the requested touchpad mode.")
        return actual

    def apply_hardware(self, action: str, device: str, value) -> dict:
        try:
            result = self.hardware.apply(action, device, value)
        except PermissionError:
            # Only elevate a fixed, root-owned installed helper. Never execute
            # an arbitrary user-writable Python module with pkexec.
            helper = Path("/opt/control-center-clone/core.py")
            if not helper.is_file() or not shutil.which("pkexec"):
                raise ControlError("This control requires administrator authorization. "
                                   "Install the app with install-fedora.sh to enable its hardware helper.")
            for node in (Path("/opt"), helper.parent, helper):
                info = node.stat()
                if node.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
                    raise ControlError("The installed hardware helper must be root-owned and not writable by other users.")
            result = json.loads(self.run(["/usr/bin/pkexec", str(helper),
                                          "--hardware-write", action, "--device", device,
                                          "--value", json.dumps(value)], timeout=120))
        if "actual" in result:
            requested = result.get("requested")
            expected = " ".join(map(str, requested)) if isinstance(requested, list) else requested
            if result["actual"] != expected:
                raise ControlError(f"Driver readback was {result['actual']!r}; requested {expected!r}. "
                                   "Refresh to review the current hardware state.")
        return result
