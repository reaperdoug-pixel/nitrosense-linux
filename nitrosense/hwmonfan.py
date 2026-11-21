"""Fan control through the in-kernel acer_wmi driver (hwmon pwm), no acpi_call needed.

acer_wmi (Linux 6.19+) exposes pwm1 (CPU fan) and pwm2 (GPU fan) on Predator Sense v4
machines whose DMI quirk sets .pwm, or when loaded with force_caps including ACER_CAP_PWM.
It is a signed in-tree module, so it keeps working under kernel lockdown=integrity, where
the unsigned acpi_call module is refused.

  pwmN_enable: 0 = full speed (firmware "turbo"), 1 = manual, 2 = automatic
  pwmN:        duty 0..255, applied in manual mode (the firmware works in percent)

Same interface as the fan part of Controller, so the daemon can use either one.
"""

from __future__ import annotations

import glob
import os

from . import encoders as enc
from .wmi import WmiError

HWMON_NAME = "acer"
_CHANNEL = {"cpu": 1, "gpu": 2}
ENABLE_MAX, ENABLE_MANUAL, ENABLE_AUTO = 0, 1, 2


def find_pwm_hwmon(root: str = "/sys/class/hwmon") -> str | None:
    for hw in sorted(glob.glob(os.path.join(root, "hwmon*"))):
        try:
            with open(os.path.join(hw, "name")) as f:
                if f.read().strip() != HWMON_NAME:
                    continue
        except OSError:
            continue
        if all(os.path.exists(os.path.join(hw, f"pwm{c}_enable")) for c in _CHANNEL.values()):
            return hw
    return None


def percent_to_duty(percent: int) -> int:
    return round(max(0, min(100, percent)) * 255 / 100)


class HwmonFans:
    def __init__(self, path: str) -> None:
        self.path = path

    def _write(self, name: str, value: int) -> None:
        for attempt in (0, 1):
            try:
                with open(os.path.join(self.path, name), "w") as f:
                    f.write(f"{value}\n")
                return
            except OSError as e:
                # reloading acer_wmi renumbers its hwmon directory: look it up once more
                fresh = find_pwm_hwmon() if attempt == 0 else None
                if fresh and fresh != self.path:
                    self.path = fresh
                    continue
                raise WmiError(f"acer_wmi {name}={value}: {e}") from e

    def _enable(self, fan: str, mode: int) -> None:
        self._write(f"pwm{_CHANNEL[fan]}_enable", mode)

    def set_fan_speed(self, fan: str, percent: int) -> None:
        self._enable(fan, ENABLE_MANUAL)
        self._write(f"pwm{_CHANNEL[fan]}", percent_to_duty(percent))

    def set_fan_mode(self, mode: str, cpu_auto: bool = True, gpu_auto: bool = True,
                     cpu_percent: int = 50, gpu_percent: int = 50) -> None:
        if mode == enc.FAN_MODE_CUSTOM:
            for fan, auto, pct in (("cpu", cpu_auto, cpu_percent), ("gpu", gpu_auto, gpu_percent)):
                if auto:
                    self._enable(fan, ENABLE_AUTO)
                else:
                    self.set_fan_speed(fan, pct)
        else:
            target = ENABLE_MAX if mode == enc.FAN_MODE_MAX else ENABLE_AUTO
            for fan in _CHANNEL:
                self._enable(fan, target)
