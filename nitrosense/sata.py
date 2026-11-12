"""SATA / SAS / USB disks (HDD and SSD): health through smartmontools' JSON output.

smartctl needs root and is a separate package (smartmontools), so the service runs it. A sleeping
hard disk is never woken up: smartctl is started with `-n standby`, and when the disk is asleep
the last known data is kept and marked as such.

list_devices() and parse() are pure and unit-tested with real smartctl output; read() only adds
the subprocess call.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

SYS_BLOCK = "/sys/block"
DEVICE = re.compile(r"^sd[a-z]{1,2}$")
TIMEOUT = 25

# SSD life attributes, whose normalised value is the REMAINING life in percent
WEAR_ATTRIBUTES = {"Wear_Leveling_Count", "SSD_Life_Left", "Media_Wearout_Indicator",
                   "Percent_Lifetime_Remain", "Percent_Lifetime_Remaining", "Remaining_Lifetime_Perc"}


def _read(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def list_devices(root: str = SYS_BLOCK) -> list[dict]:
    """Internal SATA/SAS/USB block devices (sda, sdb, ...), without removable media."""
    out = []
    try:
        names = sorted(n for n in os.listdir(root) if DEVICE.match(n))
    except OSError:
        return out
    for name in names:
        base = os.path.join(root, name)
        if _read(os.path.join(base, "removable")) == "1":
            continue
        try:
            size = int(_read(os.path.join(base, "size")) or 0) * 512
        except ValueError:
            size = 0
        if size <= 0:  # an empty card reader slot
            continue
        vendor = (_read(os.path.join(base, "device", "vendor")) or "").strip()
        model = (_read(os.path.join(base, "device", "model")) or "").strip()
        out.append({
            "name": name,
            "model": " ".join(p for p in (vendor if vendor.upper() != "ATA" else "", model) if p) or name,
            "firmware": _read(os.path.join(base, "device", "rev")) or "",
            "size": size,
            "rotational": _read(os.path.join(base, "queue", "rotational")) == "1",
            "transport": "usb" if "/usb" in os.path.realpath(base) else "sata",
        })
    return out


def drivetemp(name: str, hwmon_root: str = "/sys/class/hwmon") -> float | None:
    """Temperature from the kernel's drivetemp hwmon driver (no root, if the module is loaded)."""
    try:
        entries = os.listdir(hwmon_root)
    except OSError:
        return None
    for e in entries:
        hw = os.path.join(hwmon_root, e)
        if _read(os.path.join(hw, "name")) != "drivetemp":
            continue
        if os.path.exists(os.path.join(os.path.realpath(os.path.join(hw, "device")), "block", name)):
            try:
                return int(_read(os.path.join(hw, "temp1_input")) or "") / 1000
            except ValueError:
                return None
    return None


# ------------------------------------------------------------------ parsing
def _attr(table: list[dict], *keys) -> dict | None:
    for a in table:
        if a.get("id") in keys or a.get("name") in keys:
            return a
    return None


def _raw(table: list[dict], *keys) -> int | None:
    a = _attr(table, *keys)
    if not a:
        return None
    try:
        return int(a["raw"]["value"])
    except (KeyError, TypeError, ValueError):
        return None


def parse(data: dict) -> dict:
    """Normalise `smartctl -j -a` output of an ATA drive."""
    table = (data.get("ata_smart_attributes") or {}).get("table") or []
    wear = next((a for a in table if a.get("name") in WEAR_ATTRIBUTES), None)
    temp = (data.get("temperature") or {}).get("current")
    if temp is None:
        raw = _raw(table, 194, 190)
        temp = raw & 0xFF if raw is not None else None
    tests = ((data.get("ata_smart_self_test_log") or {}).get("standard") or {}).get("table") or []
    last_test = tests[0] if tests else None
    rpm = data.get("rotation_rate")
    out = {
        "ata": True,
        "passed": (data.get("smart_status") or {}).get("passed"),
        "temperature_c": temp,
        "power_on_hours": (data.get("power_on_time") or {}).get("hours"),
        "power_cycles": data.get("power_cycle_count"),
        "rotation_rpm": rpm if isinstance(rpm, int) and rpm > 0 else None,
        "reallocated": _raw(table, 5),
        "pending": _raw(table, 197),
        "uncorrectable": _raw(table, 198),
        "reported_uncorrect": _raw(table, 187),
        "crc_errors": _raw(table, 199),
        "spin_retry": _raw(table, 10),
        "percentage_used": max(0, min(100, 100 - wear["value"])) if wear and isinstance(wear.get("value"), int) else None,
        "failing": [a.get("name", str(a.get("id"))) for a in table
                    if a.get("when_failed") == "FAILING_NOW"],
        "failed_before": [a.get("name", str(a.get("id"))) for a in table
                          if a.get("when_failed") == "In_the_past"],
        "last_self_test": ({"passed": (last_test.get("status") or {}).get("passed"),
                            "type": (last_test.get("type") or {}).get("string", ""),
                            "lifetime_hours": last_test.get("lifetime_hours")} if last_test else None),
        "error_log_count": ((data.get("ata_smart_error_log") or {}).get("summary") or {}).get("count"),
        "standby": False,
    }
    return out


def _run(cmd: list[str], run=subprocess.run) -> tuple[dict | None, str]:
    proc = run(cmd, capture_output=True, text=True, timeout=TIMEOUT, check=False)
    text = (proc.stdout or "") + (proc.stderr or "")
    try:
        return json.loads(proc.stdout), text
    except ValueError:
        return None, text


def read(dev: dict, run=subprocess.run, smartctl: str | None = None) -> dict:
    """SMART data of one device: parsed dict, {"standby": True}, or {"error": ...}."""
    tool = smartctl or shutil.which("smartctl")
    if not tool:
        return {"error": "smartmontools is not installed", "missing_tool": True}
    path = "/dev/" + dev["name"]
    base = [tool, "-j", "-a", "-n", "standby"]
    try:
        data, text = _run(base + [path], run)
        if data is not None and dev.get("transport") == "usb" and not data.get("ata_smart_attributes"):
            retry, text2 = _run(base + ["-d", "sat", path], run)  # many USB bridges need SAT passthrough
            if retry is not None and retry.get("ata_smart_attributes"):
                data, text = retry, text2
    except (OSError, subprocess.SubprocessError) as e:
        return {"error": str(e)}
    if "STANDBY" in text.upper() and (data is None or not data.get("ata_smart_attributes")):
        return {"ata": True, "standby": True}
    if data is None:
        return {"error": text.strip().splitlines()[0] if text.strip() else "no answer from smartctl"}
    if not data.get("ata_smart_attributes"):
        messages = (data.get("smartctl") or {}).get("messages") or []
        why = messages[0].get("string") if messages and isinstance(messages[0], dict) else ""
        return {"error": why or "this drive does not report ATA SMART data"}
    return parse(data)


def read_all(root: str = SYS_BLOCK, **kw) -> dict[str, dict]:
    """{"sda": parsed...} for every internal SATA/SAS/USB disk."""
    return {d["name"]: read(d, **kw) for d in list_devices(root)}
