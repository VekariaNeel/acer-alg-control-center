"""Decode Acer telemetry and discover the typed controls in bridge ABI 2."""
from pathlib import Path

EXPECTED_DMI = {
    "sys_vendor": "Acer",
    "product_name": "Aspire Lite AL15G-52",
    "bios_version": "1.07.01RAC2",
}

CONTROL_FIELDS = {"fan_mode": 1, "fan_offset": 1, "fan_curve": 16,
                  "keyboard_rgb": 9, "keyboard_brightness": 1,
                  "charge_limits": 3, "keyboard_flags": 3,
                  "keyboard_sleep": 1, "camera": 1, "power_mode": 1}


def decode_buffer(text: str) -> bytes:
    # The module exports exactly 256 bytes as hex, never a variable-size struct.
    data = bytes.fromhex(text.strip())
    if len(data) != 256:
        raise ValueError(f"Expected a 256-byte Acer response, received {len(data)} bytes.")
    return data


def rpm(data: bytes, offset: int) -> int | None:
    period = int.from_bytes(data[offset:offset + 2], "big")
    if period == 0xffff:
        return None
    if period == 0:
        return 0
    result = round(2156250 / period)
    return result if result <= 20000 else None


def decode(specs: bytes, telemetry: bytes, charging: bytes | None = None) -> dict:
    if len(specs) != 256 or len(telemetry) != 256:
        raise ValueError("Incomplete Acer firmware response.")
    fans, keyboard = specs[12], specs[15]
    if fans != 2 or keyboard != 6:
        raise ValueError(f"Unexpected firmware identity: fans={fans}, keyboard type={keyboard}; expected 2/6.")
    if not any(telemetry):
        raise ValueError("Firmware returned empty telemetry; the EC may be unavailable under Linux.")
    temperatures = []
    fan_values = []
    for name, temperature_offset, rpm_offset in (("CPU", 18, 2), ("GPU", 21, 4)):
        value = telemetry[temperature_offset]
        temperatures.append(dict(id=f"acer/{name.lower()}_temp", chip="acer_al15g52", label=name,
                                 value=value if 0 < value <= 125 else None, fault=False))
        fan_values.append(dict(id=f"acer/{name.lower()}_fan", chip="acer_al15g52", label=name,
                               value=rpm(telemetry, rpm_offset), fault=False))
    charge = dict(available=False, reason="No charging response was returned by the bridge.")
    if charging is not None:
        if len(charging) != 256:
            raise ValueError("Incomplete Acer charging response.")
        starts = sorted({v for v in charging[16:32] if 0 < v < 100})
        stops = sorted({v for v in charging[32:48] if 0 < v <= 100})
        if charging[0] not in (0, 1) or not 0 <= charging[1] < charging[2] <= 100 or not starts or not stops:
            charge = dict(available=False, reason="Firmware returned invalid charge state or threshold choices.")
        else:
            charge = dict(available=True, enabled=charging[0] == 1, start=charging[1], stop=charging[2],
                          allowed_starts=starts, allowed_stops=stops, writable=False)
    return dict(available=True, read_only=True, fan_count=fans, keyboard_type=keyboard,
                firmware_fan_mode=specs[14],
                keyboard_raw=dict(rgb_left=list(specs[2:5]), brightness=specs[11]),
                temperatures=temperatures, fans=fan_values, charging=charge)


class AcerBridge:
    def __init__(self, sys_root: Path = Path("/sys")):
        self.sys = sys_root

    def snapshot(self, dmi: dict) -> dict:
        if any(dmi.get(key) != value for key, value in EXPECTED_DMI.items()):
            return dict(available=False, reason="The read-only Acer bridge targets AL15G-52 BIOS 1.07.01RAC2 only.")
        paths = sorted((self.sys / "bus/platform/devices").glob("CLV0001:*/control_center"))
        if len(paths) != 1:
            return dict(available=False, reason="The Acer ACPI bridge is not loaded. See driver/README.md.")
        base = paths[0]
        if not base.resolve().is_relative_to((self.sys / "devices").resolve()):
            return dict(available=False, reason="Acer bridge path is outside the kernel device tree.")
        raw = {}
        try:
            abi = (base / "abi_version").read_text().strip()
            if abi not in ("1", "2"):
                raise ValueError("Unsupported Acer bridge ABI version.")
            for key in ("specs", "telemetry"):
                raw[key] = decode_buffer((base / key).read_text())
            # A failure in the optional charging getter must not erase fan data.
            charge_error = None
            try:
                raw["charging"] = decode_buffer((base / "charging").read_text())
            except (OSError, ValueError) as exc:
                charge_error = str(exc)
            result = decode(raw["specs"], raw["telemetry"], raw.get("charging"))
            if charge_error:
                result["charging"] = dict(available=False, reason=charge_error)
            result.update(path=str(base), raw={key: value.hex() for key, value in raw.items()})
            result["abi_version"] = int(abi)
            result["controls"] = {}
            if abi == "2":
                for name, count in CONTROL_FIELDS.items():
                    try:
                        path = base / name
                        values = [int(v) for v in path.read_text().split()]
                        if len(values) != count:
                            raise ValueError("Unexpected number of driver values.")
                        if any(v < 0 for v in values) and not (name == "keyboard_sleep" and values == [-1]):
                            raise ValueError("Driver returned an unavailable value.")
                        if ((name == "fan_mode" and values[0] not in (0, 1, 6)) or
                            (name in ("fan_offset", "keyboard_rgb", "keyboard_brightness") and any(v > 255 for v in values)) or
                            (name == "charge_limits" and (values[0] not in (0, 1) or not 0 < values[1] < values[2] <= 100)) or
                            (name == "keyboard_flags" and any(v not in (1, 2) for v in values)) or
                            (name == "camera" and values[0] not in (0, 1)) or
                            (name == "power_mode" and values[0] not in range(4)) or
                            (name == "keyboard_sleep" and values[0] not in (-1, 0) and not 5 <= values[0] <= 7199) or
                            (name == "fan_curve" and any(v > 100 for v in values))):
                            raise ValueError("Driver returned an invalid control state.")
                        result["controls"][name] = dict(available=True, values=values,
                                                        writable=bool(path.stat().st_mode & 0o222))
                    except (OSError, ValueError) as exc:
                        result["controls"][name] = dict(available=False, writable=False, reason=str(exc))
                result["read_only"] = not any(c.get("writable") for c in result["controls"].values())
                result["charging"]["writable"] = result["controls"]["charge_limits"].get("writable", False)
            return result
        except (OSError, ValueError) as exc:
            return dict(available=False, reason=str(exc), raw={key: value.hex() for key, value in raw.items()})
