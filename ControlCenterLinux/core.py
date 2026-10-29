#!/usr/bin/python3 -I
"""Linux hardware discovery and narrowly scoped sysfs writes. No GTK dependency.

This module can also run in isolation as the authenticated hardware helper.
It deliberately has no raw EC, ACPI method execution or Windows DLL interface.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import stat
import sys
from pathlib import Path
from typing import Any

VERSION = "0.5.1"

ACER_ACTIONS = {
    "acer-fan": ("fan_mode", 1), "acer-offset": ("fan_offset", 1),
    "acer-curve": ("fan_curve", 8), "acer-rgb": ("keyboard_rgb", 3),
    "acer-brightness": ("keyboard_brightness", 1), "acer-charge": ("charge_limits", 3),
    "acer-flags": ("keyboard_flags", 2), "acer-sleep": ("keyboard_sleep", 1),
    "acer-camera": ("camera", 1), "acer-power": ("power_mode", 1),
}


class ControlError(Exception):
    pass


def read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def number(path: Path) -> int | None:
    try:
        return int(read(path) or "")
    except ValueError:
        return None


def integer(value: Any, minimum: int, maximum: int) -> int:
    # bool is an int subclass; do not silently treat it as a percentage.
    if type(value) is not int or not minimum <= value <= maximum:
        raise ControlError(f"Expected an integer between {minimum} and {maximum}.")
    return value


class LinuxHardware:
    def __init__(self, sys_root: Path = Path("/sys"), proc_root: Path = Path("/proc")):
        # Alternate roots are dependency injection for tests, never CLI options.
        self.sys = sys_root
        self.proc = proc_root
        self.previous_cpu: tuple[int, int] | None = None

    def entries(self, group: str) -> list[Path]:
        return sorted((self.sys / "class" / group).glob("*"))

    @staticmethod
    def driver_writable(path: Path) -> bool:
        try:
            return bool(path.stat().st_mode & stat.S_IWUSR)
        except OSError:
            return False

    def display_devices(self) -> list[dict]:
        return [dict(id=p.name, value=number(p / "brightness"),
                     actual=number(p / "actual_brightness"), maximum=number(p / "max_brightness"),
                     writable=self.driver_writable(p / "brightness"))
                for p in self.entries("backlight")]

    def keyboard_devices(self) -> list[dict]:
        devices = []
        for p in self.entries("leds"):
            if not p.name.endswith(":kbd_backlight"):
                continue
            colors = (read(p / "multi_index") or "").split()
            devices.append(dict(id=p.name, value=number(p / "brightness"),
                                maximum=number(p / "max_brightness"), colors=colors,
                                intensity=read(p / "multi_intensity"),
                                writable=self.driver_writable(p / "brightness"),
                                rgb=set(colors) == {"red", "green", "blue"} and len(colors) == 3
                                and self.driver_writable(p / "multi_intensity")))
        return devices

    def batteries(self) -> list[dict]:
        result = []
        for p in self.entries("power_supply"):
            if read(p / "type") != "Battery":
                continue
            result.append(dict(id=p.name, capacity=number(p / "capacity"), status=read(p / "status"),
                               present=number(p / "present"),
                               start=number(p / "charge_control_start_threshold"),
                               stop=number(p / "charge_control_end_threshold"),
                               start_writable=self.driver_writable(p / "charge_control_start_threshold"),
                               stop_writable=self.driver_writable(p / "charge_control_end_threshold")))
        return result

    def sensors(self) -> dict:
        temperatures, fans, pwm = [], [], []
        for p in self.entries("hwmon"):
            chip = read(p / "name") or p.name
            for kind, target, divisor in (("temp", temperatures, 1000), ("fan", fans, 1)):
                for node in sorted(p.glob(f"{kind}[0-9]*_input")):
                    if not re.fullmatch(rf"{kind}\d+_input", node.name):
                        continue
                    prefix = node.name.removesuffix("_input")
                    raw = number(node)
                    faulty = number(p / f"{prefix}_fault") == 1
                    target.append(dict(id=f"{p.name}/{prefix}", chip=chip,
                                       label=read(p / f"{prefix}_label") or prefix,
                                       value=raw / divisor if raw is not None and not faulty else None,
                                       fault=faulty))
            for node in sorted(p.glob("pwm[0-9]*_enable")):
                if re.fullmatch(r"pwm\d+_enable", node.name):
                    pwm.append(dict(id=f"{p.name}/{node.name}", chip=chip, mode=number(node)))
        return dict(temperatures=temperatures, fans=fans, pwm_interfaces=pwm,
                    fan_control=False,
                    fan_control_reason="No AL15G-52 Linux fan adapter has been validated. "
                    "PWM nodes are inventoried only; mode meanings can differ between drivers.")

    def metrics(self) -> dict:
        cpu = None
        rows = (read(self.proc / "stat") or "").splitlines()
        if rows and rows[0].startswith("cpu "):
            try:
                values = [int(x) for x in rows[0].split()[1:9]]
                total, idle = sum(values), values[3] + values[4]
                if self.previous_cpu:
                    delta = total - self.previous_cpu[0]
                    if delta > 0:
                        cpu = max(0, min(100, 100 * (1 - (idle - self.previous_cpu[1]) / delta)))
                self.previous_cpu = total, idle
            except (ValueError, IndexError):
                self.previous_cpu = None
        memory = {}
        for line in (read(self.proc / "meminfo") or "").splitlines():
            parts = line.replace(":", "").split()
            if len(parts) >= 2 and parts[1].isdigit():
                memory[parts[0]] = int(parts[1])
        total = memory.get("MemTotal")
        available = memory.get("MemAvailable")
        cpu_info = (read(self.proc / "cpuinfo") or "").splitlines()
        name = next((x.split(":", 1)[1].strip() for x in cpu_info if x.startswith("model name")), None)
        clocks = []
        for line in cpu_info:
            if line.startswith("cpu MHz"):
                try:
                    clocks.append(float(line.split(":", 1)[1]))
                except ValueError:
                    pass
        disk = shutil.disk_usage("/")
        return dict(cpu_percent=cpu, cpu_name=name,
                    reported_clock_mhz=sum(clocks) / len(clocks) if clocks else None,
                    memory_total_gib=total / 1048576 if total else None,
                    memory_used_gib=(total - available) / 1048576 if total and available is not None else None,
                    disk_total_gib=disk.total / 1073741824, disk_free_gib=disk.free / 1073741824)

    def inventory(self) -> dict:
        dmi = self.sys / "class/dmi/id"
        modules = (read(self.proc / "modules") or "").splitlines()
        # Excludes serials, UUIDs, host/user names and network identifiers.
        return dict(dmi={key: read(dmi / key) for key in
                         ("sys_vendor", "product_name", "product_version", "board_name", "bios_version")},
                    modules=[x.split()[0] for x in modules if x.split()],
                    wmi=[dict(guid=p.name, modalias=read(p / "modalias"),
                              driver=(p / "driver").resolve().name if (p / "driver").exists() else None)
                         for p in sorted((self.sys / "bus/wmi/devices").glob("*"))],
                    clevo_acpi=[dict(id=p.name, hid=read(p / "hid"), status=read(p / "status"),
                                     driver=(p / "physical_node/driver").resolve().name
                                     if (p / "physical_node/driver").exists() else None)
                                for p in sorted((self.sys / "bus/acpi/devices").glob("CLV*"))],
                    platform_profile=read(self.sys / "firmware/acpi/platform_profile"),
                    platform_profile_choices=read(self.sys / "firmware/acpi/platform_profile_choices"))

    def snapshot(self) -> dict:
        try:
            release = platform.freedesktop_os_release()
            distribution = {key: release.get(key) for key in ("NAME", "VERSION_ID", "PRETTY_NAME")}
        except OSError:
            distribution = {}
        inventory = self.inventory()
        # Imported here so the isolated, standard-library-only write helper
        # remains independent of adjacent Python modules.
        try:
            from acer import AcerBridge
            acer = AcerBridge(self.sys).snapshot(inventory["dmi"])
        except ImportError:
            acer = dict(available=False, reason="Acer bridge decoder is not installed.")
        sensors = self.sensors()
        if acer["available"]:
            sensors["temperatures"].extend(acer["temperatures"])
            sensors["fans"].extend(acer["fans"])
            sensors["fan_control"] = acer.get("controls", {}).get("fan_mode", {}).get("writable", False)
            sensors["fan_control_reason"] = ("Acer firmware controls are available through bridge ABI 2."
                                             if sensors["fan_control"] else
                                             "Load the ABI 2 driver to enable Acer controls; the connected bridge provides telemetry only.")
        return dict(version=VERSION, system=platform.system(), kernel=platform.release(),
                    distribution=distribution, wsl="microsoft" in platform.release().lower(),
                    inventory=inventory, metrics=self.metrics(), sensors=sensors, acer=acer,
                    displays=self.display_devices(), keyboards=self.keyboard_devices(), batteries=self.batteries(),
                    pending={
                        "vendor_performance": "Four firmware profiles are implemented through ABI 2. "
                        "Linux desktop power policy is separate; Windows FnKey GPU/ASPM orchestration is not reproduced.",
                        "fan_curves_and_offset": "Implemented through the Acer ABI 2 bridge; physical Fedora validation pending.",
                        "fn_lock_camera_touchpad": "Fn-key and camera controls use the Acer ABI 2 bridge; touchpad uses the GNOME session.",
                        "overclocking": "Not advertised by the verified Windows capabilities on this laptop."})

    def target(self, group: str, device: str, attribute: str) -> Path:
        # Device names come from discovery but all helper inputs are revalidated.
        if not isinstance(device, str) or not re.fullmatch(r"[A-Za-z0-9_:.-]+", device) or device in (".", ".."):
            raise ControlError("Invalid device identifier.")
        path = self.sys / "class" / group / device / attribute
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ControlError(f"Driver does not expose {group}/{device}/{attribute}.") from exc
        if not resolved.is_relative_to((self.sys / "devices").resolve()):
            raise ControlError("Refusing a target outside the kernel device tree.")
        if not self.driver_writable(resolved):
            raise ControlError(f"Driver exposes {attribute} as read-only.")
        return resolved

    def write(self, path: Path, value: int | str) -> None:
        path.write_text(str(value) + "\n", encoding="ascii")

    def apply(self, action: str, device: str, value: Any) -> dict:
        if action in ACER_ACTIONS:
            return self.apply_acer(action, device, value)
        if action in ("display", "keyboard"):
            group = "backlight" if action == "display" else "leds"
            if action == "keyboard" and not device.endswith(":kbd_backlight"):
                raise ControlError("Only keyboard backlight LEDs may be changed.")
            path = self.target(group, device, "brightness")
            maximum = number(path.parent / "max_brightness")
            if maximum is None or maximum <= 0:
                raise ControlError("Driver did not return a valid brightness range.")
            level = integer(value, 0, maximum)
            self.write(path, level)
            return dict(requested=level, actual=number(path), maximum=maximum)
        if action == "rgb":
            if not device.endswith(":kbd_backlight"):
                raise ControlError("Only keyboard backlight LEDs may be changed.")
            path = self.target("leds", device, "multi_intensity")
            colors = (read(path.parent / "multi_index") or "").split()
            maximum = number(path.parent / "max_brightness")
            if len(colors) != 3 or set(colors) != {"red", "green", "blue"} or not maximum or maximum < 0:
                raise ControlError("Driver does not expose a supported three-channel RGB keyboard.")
            if not isinstance(value, list) or len(value) != 3:
                raise ControlError("Expected [red, green, blue] with values from 0 to 255.")
            rgb = dict(zip(("red", "green", "blue"), (integer(x, 0, 255) for x in value)))
            levels = [round(rgb[color] * maximum / 255) for color in colors]
            self.write(path, " ".join(map(str, levels)))
            return dict(requested=levels, actual=read(path), order=colors)
        if action == "charge":
            if not isinstance(value, dict) or not value or set(value) - {"start", "stop"}:
                raise ControlError("Expected charge thresholds with start and/or stop.")
            # Validate the entire request and all targets before any mutation.
            nodes = {k: self.target("power_supply", device, f"charge_control_{k}_threshold")
                     for k in value.keys() & {"start"}}
            if "stop" in value:
                nodes["stop"] = self.target("power_supply", device, "charge_control_end_threshold")
            if read((self.sys / "class/power_supply" / device) / "type") != "Battery":
                raise ControlError("The selected power supply is not a battery.")
            base = self.sys / "class/power_supply" / device
            current = dict(start=number(base / "charge_control_start_threshold"),
                           stop=number(base / "charge_control_end_threshold"))
            desired = current | {k: integer(v, 0, 100) for k, v in value.items()}
            if desired["start"] is not None and desired["stop"] is not None and desired["start"] >= desired["stop"]:
                raise ControlError("The start threshold must be below the stop threshold.")
            # When moving an entire range upwards, raise stop before start.
            order = ["start", "stop"]
            if "start" in value and current["stop"] is not None and desired["start"] >= current["stop"]:
                order.reverse()
            applied = []
            try:
                for key in order:
                    if key not in value:
                        continue
                    self.write(nodes[key], desired[key])
                    applied.append(key)
                    actual = number(nodes[key])
                    if actual != desired[key]:
                        raise ControlError(f"Driver returned {key}={actual}, requested {desired[key]}; "
                                           "hardware may only accept specific thresholds.")
            except OSError as exc:
                # A failed second write must never be reported as atomic success.
                if applied:
                    raise ControlError(f"Charge update partially applied ({', '.join(applied)}). "
                                       f"Refresh and review current thresholds. {exc}") from exc
                raise
            return dict(start=number(base / "charge_control_start_threshold"),
                        stop=number(base / "charge_control_end_threshold"))
        raise ControlError("Unsupported hardware action.")

    def apply_acer(self, action: str, device: str, value: Any) -> dict:
        # This path also runs under python -I in the privileged helper. Keep it
        # standard-library-only; the kernel independently validates every field.
        expected = {"sys_vendor": "Acer", "product_name": "Aspire Lite AL15G-52", "bios_version": "1.07.01RAC2"}
        if any(read(self.sys / "class/dmi/id" / key) != val for key, val in expected.items()):
            raise ControlError("Acer controls require AL15G-52 BIOS 1.07.01RAC2.")
        if device != "CLV0001:00":
            raise ControlError("Invalid Acer bridge device.")
        attribute, count = ACER_ACTIONS[action]
        base = self.sys / "bus/platform/devices" / device / "control_center"
        path = (base / attribute).resolve(strict=True)
        if not path.is_relative_to((self.sys / "devices").resolve()) or not self.driver_writable(path):
            raise ControlError("Acer control is not a writable kernel device attribute.")
        if read(base / "abi_version") != "2":
            raise ControlError("Load the new ABI 2 Acer module before changing settings.")
        values = value if isinstance(value, list) else [value]
        if len(values) != count:
            raise ControlError(f"Expected {count} integer value(s) for {action}.")
        values = [integer(v, 0, 7199) for v in values]
        # Reject invalid choices before authorization or any sysfs mutation.
        if action == "acer-fan" and values[0] not in (0, 1):
            raise ControlError("Use Automatic (0) or Maximum (1); custom mode requires a complete curve.")
        if action == "acer-offset" and values[0] > 100:
            raise ControlError("Fan offset must be 0–100%.")
        if action == "acer-brightness" and values[0] > 4:
            raise ControlError("Keyboard brightness must be 0–4.")
        if action == "acer-rgb" and any(v > 255 for v in values):
            raise ControlError("RGB channels must be 0–255.")
        if action == "acer-power" and values[0] > 3:
            raise ControlError("Select a firmware profile from 0–3.")
        if action == "acer-camera" and values[0] > 1:
            raise ControlError("Camera state must be 0 or 1.")
        if action == "acer-flags" and (values[0] > 2 or values[1] > 1):
            raise ControlError("Choose a keyboard flag from 0–2 and state 0 or 1.")
        if action == "acer-sleep" and 0 < values[0] < 5:
            raise ControlError("Use zero to disable sleep, or 5–7199 seconds.")
        if action == "acer-charge":
            enabled, start, stop = values
            if enabled > 1 or not 0 < start < stop <= 100 or (not enabled and (start, stop) != (95, 100)):
                raise ControlError("Use enabled/start/stop thresholds, or [0,95,100] to disable limits.")
        if action == "acer-curve":
            for offset in (0, 4):
                t1, d1, t2, d2 = values[offset:offset + 4]
                if not 20 <= t1 < t2 < 100 or not 0 < d1 < d2 < 100:
                    raise ControlError("Curve temperatures and duties must strictly increase below 100.")
        try:
            self.write(path, " ".join(map(str, values)))
        except OSError as exc:
            if isinstance(exc, PermissionError):
                raise
            raise ControlError(f"Firmware request failed; it may have partially applied. "
                               f"Refresh current state before retrying. {exc}") from exc
        reported = read(path)
        if reported is None:
            raise ControlError("Command completed but reading current firmware state failed; refresh before retrying.")
        acknowledgement_only = action in ("acer-rgb", "acer-brightness", "acer-sleep")
        return dict(action=action, requested=values, reported=reported,
                    confirmation="Command acknowledged; physical lighting/timer behavior needs checking."
                    if acknowledgement_only else "Kernel verified firmware readback.",
                    hardware_validation="Pending on native Fedora for the new setters.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Linux diagnostics or explicit sysfs control")
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--hardware-write", choices=("display", "keyboard", "rgb", "charge", *ACER_ACTIONS))
    parser.add_argument("--device")
    parser.add_argument("--value", help="JSON value; writes require this explicit option")
    args = parser.parse_args(argv)
    if platform.system() != "Linux":
        parser.error("This backend runs on Linux. Use the Windows clone on Windows.")
    if args.diagnose == bool(args.hardware_write):
        parser.error("Choose exactly one of --diagnose and --hardware-write.")
    if args.output and not args.diagnose:
        parser.error("--output is only valid with --diagnose.")
    if args.output and os.geteuid() == 0:
        parser.error("Save diagnostics as your normal user; the elevated helper does not accept output paths.")
    hardware = LinuxHardware()
    try:
        if args.diagnose:
            result = hardware.snapshot()
        else:
            if not args.device or args.value is None:
                parser.error("Hardware writes require --device and --value.")
            result = hardware.apply(args.hardware_write, args.device, json.loads(args.value))
        output = json.dumps(result, indent=2)
        if args.output:
            args.output.write_text(output + "\n", encoding="utf-8")
        else:
            print(output)
        return 0
    except (OSError, ValueError, ControlError) as exc:
        print(json.dumps(dict(error=str(exc))), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
