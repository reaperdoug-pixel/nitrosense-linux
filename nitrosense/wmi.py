"""Invoke Acer WMI methods from Linux userspace (root only) through acpi_call.

Windows NitroSense: GUI -> named pipe -> NitroSense service -> WMI class
AcerGamingFunction / APGeAction -> ACPI method WMxx of the PNP0C14 device.
Here: daemon -> /proc/acpi/call -> the same ACPI method with the same input.

Only the methods listed in METHODS can be called, with fixed input sizes.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
import threading

log = logging.getLogger("nitrosense.wmi")

ACPI_CALL = "/proc/acpi/call"
OVERRIDE_FILE = "/etc/nitrosense/wmi.json"

GAMING_GUID = "7A4DDFE7-5B5D-40B4-8595-4408E0CC7F56"  # class AcerGamingFunction
APGE_GUID = "61EF69EA-865C-4BC3-A502-A0DEBA0CB531"    # class APGeAction
BATTERY_GUID = "79772EC5-04B1-4BFD-843C-61E7F77B6CC9"  # battery health control (acer-wmi-battery)

# name -> (guid, WmiMethodId, input size in bytes)
# Verified against the AN515-44 BIOS V1.04 (SSDT5 \_SB.PCI0.WMID.WMBH):
#   5  GetGamingSysInfo  -> EC GGSI(buf[0]=1, buf[1]=sensor): 1 CTMP, 2 C1FR, 6 G1FR, 10 SKTC
#   6  SetGamingRgbKb    -> EC KBBA=buf[0] (zone 1/2/4/8), KBnR/G/B=buf[1..3]   (4-byte BHSK)
#   16 SetGamingFanSpeed -> EC CPUF/GPUF = buf[1] (0..100) for buf[0] = 1 / 4    (8-byte BHGK)
#   20 SetGamingKBBacklight -> EC KBLE,KBLS,KBBP,KBCS,KBED,KBCR/G/B = buf[0..7]  (16-byte BHLK)
#   1/3/14/22/23/24 are forwarded to SMM (WSMI); 14/22/23 match mainline acer-wmi,
#   1 returns the setter status buffer and 3/23 the getter buffer, as their names imply;
#   1 is confirmed on hardware (Windows-key lock), 3 reports Overdrive byte 6 = 0xFF (unsupported).
#   24 (assumed SetGamingLEDBehavior, zone on/off) answered status 2 on hardware -> not used.
# APGeAction (\_SB.PCI0.WMID.WMAA) only implements 1 (SetFunction) and 2 (GetFunction).
METHODS: dict[str, tuple[str, int, int]] = {
    "SetGamingProfile": (GAMING_GUID, 1, 8),
    "GetGamingProfile": (GAMING_GUID, 3, 4),
    "GetGamingSysInfo": (GAMING_GUID, 5, 4),
    "SetGamingRgbKb": (GAMING_GUID, 6, 4),
    "GetGamingRgbKb": (GAMING_GUID, 7, 4),          # -> [status, R, G, B] of zone buf[0]
    "SetGamingFanBehavior": (GAMING_GUID, 14, 8),
    "SetGamingFanSpeed": (GAMING_GUID, 16, 8),
    "SetGamingKBBacklight": (GAMING_GUID, 20, 16),
    "GetGamingKBBacklight": (GAMING_GUID, 21, 4),    # -> [status, mode, speed, bright, cs, dir, R, G, B]
    "SetGamingMiscSetting": (GAMING_GUID, 22, 8),
    "GetGamingMiscSetting": (GAMING_GUID, 23, 4),
    # Battery health mode = charge limit at ~80 %. Layout from the acer-wmi-battery driver; the
    # get call is confirmed on a Nitro ANV15-51 (answers 03 00 00 00 ...: health + calibration).
    "GetBatteryHealth": (BATTERY_GUID, 20, 4),   # in: battery 1, query 1; out[0] functions, out[3] health
    "SetBatteryHealth": (BATTERY_GUID, 21, 8),   # in: battery 1, function mask, status
    "SetFunction": (APGE_GUID, 1, 8),
    "GetFunction": (APGE_GUID, 2, 4),
}


class WmiError(RuntimeError):
    pass


def _load_overrides() -> None:
    """Allow /etc/nitrosense/wmi.json to correct method ids/sizes for other BIOSes."""
    try:
        with open(OVERRIDE_FILE) as f:
            data = json.load(f)
    except FileNotFoundError:
        return
    except (OSError, ValueError) as e:
        log.warning("ignoring %s: %s", OVERRIDE_FILE, e)
        return
    for name, spec in data.get("methods", {}).items():
        if name in METHODS and isinstance(spec, dict):
            guid, mid, size = METHODS[name]
            METHODS[name] = (guid, int(spec.get("id", mid)), int(spec.get("size", size)))


def acpi_method_path(guid: str) -> str:
    """Resolve e.g. \\_SB_.PCI0.WMID.WMBH for a WMI GUID from sysfs."""
    dev = f"/sys/bus/wmi/devices/{guid}"
    if not os.path.isdir(dev):
        # Kernels with legacy names expose GUID-<n>
        matches = glob.glob(f"/sys/bus/wmi/devices/{guid}*")
        if not matches:
            raise WmiError(f"WMI GUID {guid} not present on this machine")
        dev = matches[0]
    with open(os.path.join(dev, "object_id")) as f:
        obj = f.read().strip()
    if not re.fullmatch(r"[A-Z0-9]{2}", obj):
        raise WmiError(f"unexpected object id {obj!r} for {guid}")
    node = os.path.realpath(dev)
    while node != "/":
        fw = os.path.join(node, "firmware_node", "path")
        if os.path.exists(fw):
            with open(fw) as f:
                acpi = f.read().strip()
            if not re.fullmatch(r"[\\A-Z0-9_.]+", acpi):
                raise WmiError(f"unexpected ACPI path {acpi!r}")
            return f"{acpi}.WM{obj}"
        node = os.path.dirname(node)
    raise WmiError(f"cannot find ACPI device for {guid}")


def parse_acpi_call_result(text: str) -> bytes | int:
    text = text.strip().rstrip("\x00").strip()
    if not text or text == "not called":
        raise WmiError("acpi_call returned no result")
    if text.startswith("Error"):
        raise WmiError(text)
    if text.startswith("{"):
        inner = text.strip("{}").strip()
        if not inner:
            return b""
        return bytes(int(x, 16) for x in inner.split(","))
    if text.startswith("0x"):
        return int(text, 16)
    raise WmiError(f"unexpected acpi_call result {text!r}")


class AcerWmi:
    """Serialised, whitelisted access to the Acer WMI methods."""

    def __init__(self) -> None:
        _load_overrides()
        self._lock = threading.Lock()
        self._paths: dict[str, str] = {}

    def available(self) -> tuple[bool, str]:
        if not os.path.exists(ACPI_CALL):
            return False, "acpi_call kernel module is not loaded"
        try:
            self._path(GAMING_GUID)
        except WmiError as e:
            return False, str(e)
        return True, ""

    def _path(self, guid: str) -> str:
        if guid not in self._paths:
            self._paths[guid] = acpi_method_path(guid)
        return self._paths[guid]

    def call(self, name: str, value: int) -> int:
        """Call a whitelisted method; returns the first 8 output bytes as an integer (LE)."""
        result = self.call_bytes(name, value)
        out = int.from_bytes(result[:8], "little")
        log.debug("%s(%#x) -> %#x", name, value, out)
        return out

    def call_bytes(self, name: str, value: int) -> bytes:
        """Call a whitelisted method; returns the complete output buffer."""
        guid, mid, size = METHODS[name]
        if value < 0 or value >= 1 << (8 * size):
            raise WmiError(f"{name}: input {value:#x} does not fit {size} bytes")
        payload = value.to_bytes(size, "little")
        cmd = f"{self._path(guid)} 0x0 {mid:#x} b{payload.hex()}"
        with self._lock:
            try:
                with open(ACPI_CALL, "w") as f:
                    f.write(cmd)
                with open(ACPI_CALL) as f:
                    raw = f.read()
            except OSError as e:
                raise WmiError(f"{name}: acpi_call failed: {e}") from e
        result = parse_acpi_call_result(raw)
        if isinstance(result, int):
            return result.to_bytes(8, "little")
        return result
