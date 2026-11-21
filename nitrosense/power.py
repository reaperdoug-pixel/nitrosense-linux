"""Power plans (Power Saver / Balance / High-Performance) for AC and battery.

Windows NitroSense switches Windows power schemes (PowerSetActiveScheme).
Linux has no power schemes, so each plan maps to CPU frequency policy plus
power-profiles-daemon (keeps the GNOME quick-settings in sync):

  Power Saver      : schedutil, CPU boost off,  PPD power-saver
  Balance          : schedutil, CPU boost on,   PPD balanced
  High-Performance : performance, CPU boost on, PPD performance (or balanced)
"""

from __future__ import annotations

import glob
import logging
import os
import shutil
import subprocess

log = logging.getLogger("nitrosense.power")

PLAN_SAVER = "powersaver"
PLAN_BALANCE = "balance"
PLAN_PERFORMANCE = "performance"
PLANS = (PLAN_SAVER, PLAN_BALANCE, PLAN_PERFORMANCE)

_PLAN_SETTINGS = {
    PLAN_SAVER: ("schedutil", False, "power-saver"),
    PLAN_BALANCE: ("schedutil", True, "balanced"),
    PLAN_PERFORMANCE: ("performance", True, "performance"),
}


def ac_online() -> bool:
    for supply in glob.glob("/sys/class/power_supply/*"):
        try:
            with open(os.path.join(supply, "type")) as f:
                if f.read().strip() != "Mains":
                    continue
            with open(os.path.join(supply, "online")) as f:
                return f.read().strip() == "1"
        except OSError:
            continue
    return True  # no battery info -> treat as plugged in


def _write(path: str, value: str) -> bool:
    try:
        with open(path, "w") as f:
            f.write(value)
        return True
    except OSError as e:
        log.debug("write %s=%s failed: %s", path, value, e)
        return False


def _available_governors() -> set[str]:
    try:
        with open("/sys/devices/system/cpu/cpufreq/policy0/scaling_available_governors") as f:
            return set(f.read().split())
    except OSError:
        return set()


def _ppd_profiles() -> set[str]:
    exe = shutil.which("powerprofilesctl")
    if not exe:
        return set()
    try:
        out = subprocess.run([exe, "list"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    profiles = set()
    for line in out.splitlines():
        line = line.strip().lstrip("*").strip()
        if line.endswith(":"):
            profiles.add(line[:-1])
    return profiles


def _scaling_driver() -> str:
    try:
        with open("/sys/devices/system/cpu/cpufreq/policy0/scaling_driver") as f:
            return f.read().strip()
    except OSError:
        return ""


# Drivers with an energy/performance preference that power-profiles-daemon sets itself.
# Their "performance" governor locks that preference (writes fail with EBUSY), which makes
# ppd abort the whole profile switch, firmware platform_profile included.
_EPP_DRIVERS = ("intel_pstate", "amd-pstate-epp")


def apply_plan(plan: str) -> None:
    governor, boost, ppd = _PLAN_SETTINGS[plan]
    govs = _available_governors()
    profiles = _ppd_profiles()
    if profiles and _scaling_driver() in _EPP_DRIVERS:
        governor = "powersave"  # ppd drives the plan through EPP and platform_profile
    if governor not in govs and "schedutil" in govs:
        governor = "schedutil"
    for pol in glob.glob("/sys/devices/system/cpu/cpufreq/policy*"):
        if governor in govs:
            _write(os.path.join(pol, "scaling_governor"), governor)
        if os.path.exists(os.path.join(pol, "boost")):
            _write(os.path.join(pol, "boost"), "1" if boost else "0")
    if os.path.exists("/sys/devices/system/cpu/cpufreq/boost"):
        _write("/sys/devices/system/cpu/cpufreq/boost", "1" if boost else "0")

    if profiles:
        if ppd not in profiles:
            ppd = "balanced"
        try:
            subprocess.run(["powerprofilesctl", "set", ppd], timeout=5, check=False,
                           capture_output=True)
        except (OSError, subprocess.SubprocessError) as e:
            log.debug("powerprofilesctl failed: %s", e)
    log.info("power plan %s applied (governor=%s boost=%s ppd=%s)", plan, governor, boost, ppd)


def restore_defaults() -> None:
    apply_plan(PLAN_BALANCE)
