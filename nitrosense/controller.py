"""High level hardware actions, same call sequences as NitroSense for Windows."""

from __future__ import annotations

import logging
import os
import time

from . import encoders as enc
from .wmi import AcerWmi, WmiError

log = logging.getLogger("nitrosense.controller")

DMI_TYPE_AA = "/sys/firmware/dmi/entries/170-0/raw"


def read_hotkey_number() -> int:
    """commun_fn_key_number from SMBIOS type 0xAA (offset 14), as acer-wmi uses it."""
    try:
        with open(DMI_TYPE_AA, "rb") as f:
            raw = f.read()
        if len(raw) > 14 and raw[0] == 0xAA:
            return raw[14]
    except OSError:
        pass
    return 0


class Controller:
    def __init__(self, wmi: AcerWmi | None = None, adjust: enc.ColorAdjust = enc.ColorAdjust()):
        self.wmi = wmi or AcerWmi()
        self.adjust = adjust
        self.hotkey_number = read_hotkey_number()

    # ------------------------------------------------------------ fans
    def set_fan_mode(self, mode: str, cpu_auto: bool = True, gpu_auto: bool = True,
                     cpu_percent: int = 50, gpu_percent: int = 50) -> None:
        if mode == enc.FAN_MODE_CUSTOM:
            # Nitro_FanControlPage.FanModeCustom_Click -> set_all_custom_fan_state
            self._ok("SetGamingFanBehavior", enc.fan_custom_behavior(cpu_auto, gpu_auto))
            self._ok("SetGamingFanSpeed", enc.fan_speed(enc.FAN_CPU, cpu_percent))
            self._ok("SetGamingFanSpeed", enc.fan_speed(enc.FAN_GPU, gpu_percent))
        else:
            self._ok("SetGamingFanBehavior", enc.fan_mode_all(mode))

    def set_fan_speed(self, fan: str, percent: int) -> None:
        self._ok("SetGamingFanSpeed", enc.fan_speed(fan, percent))

    def read_sensor(self, index: int) -> int | None:
        try:
            return enc.sysinfo_value(self.wmi.call("GetGamingSysInfo", enc.sysinfo_query(index)))
        except WmiError as e:
            log.debug("sensor %d: %s", index, e)
            return None

    # -------------------------------------------------------- coolboost
    def set_coolboost(self, on: bool) -> None:
        self._ok("SetFunction", enc.coolboost_set(on))

    def get_coolboost(self) -> bool | None:
        try:
            return enc.coolboost_decode(self.wmi.call("GetFunction", enc.COOLBOOST_GET))
        except WmiError:
            return None

    # --------------------------------------------------- misc settings
    def set_win_key(self, enabled: bool) -> None:
        self._ok("SetGamingProfile", enc.win_key_set(enabled))

    def set_lcd_overdrive(self, on: bool) -> None:
        self._ok("SetGamingProfile", enc.lcd_overdrive_set(on))

    def get_lcd_overdrive(self) -> bool | None:
        try:
            return enc.lcd_overdrive_decode(self.wmi.call("GetGamingProfile", enc.LCD_OVERDRIVE_GET))
        except WmiError:
            return None

    def get_battery_limit(self) -> bool | None:
        """True/False = charge limit on/off; None = not supported (or the firmware did not answer)."""
        try:
            return enc.battery_health_decode(self.wmi.call("GetBatteryHealth", enc.BATTERY_HEALTH_GET))
        except WmiError:
            return None

    def set_battery_limit(self, on: bool) -> None:
        # the set call has no meaningful status byte, so confirm by reading the state back
        self.wmi.call("SetBatteryHealth", enc.battery_health_set(on))
        if self.get_battery_limit() != on:
            raise WmiError("the firmware did not accept the battery charge limit")

    def get_backlight(self) -> tuple[int, bool] | None:
        try:
            return enc.backlight_decode(
                self.wmi.call("GetFunction", enc.backlight_get(self.hotkey_number)))
        except WmiError:
            return None

    def set_backlight_timeout(self, enabled: bool) -> None:
        state = self.get_backlight()
        brightness = state[0] if state else 100
        self._ok("SetFunction", enc.backlight_timeout_set(self.hotkey_number, brightness, enabled))

    def gpu_mode_supported(self) -> bool:
        try:
            return enc.gpu_mode_supported(
                self.wmi.call("GetGamingMiscSetting", enc.GPU_MODE_SUPPORT_GET))
        except WmiError:
            return False

    def get_gpu_mode(self) -> int:
        try:
            return enc.gpu_mode_decode(self.wmi.call("GetGamingMiscSetting", enc.GPU_MODE_GET))
        except WmiError:
            return 0

    def set_gpu_mode(self, discrete_only: bool) -> None:
        self._ok("SetGamingMiscSetting", enc.gpu_mode_set(discrete_only))

    # ---------------------------------------------------------- keyboard
    def apply_keyboard(self, kb: dict) -> None:
        if kb.get("mode") == "dynamic":
            self._ok("SetGamingKBBacklight", enc.kb_dynamic_backlight(
                kb["effect"], kb["speed"], kb["brightness"], kb["direction"],
                enc.parse_hex_color(kb["effect_color"]), self.adjust))
            return
        # Static: brightness, then the four zone colours (Popup_Lighting). A switched-off
        # zone is written as black: NitroSense's SetGamingLEDBehavior zone mask is
        # rejected by the AN515-44 BIOS (status 2), while SetGamingRgbKb is verified.
        self._ok("SetGamingKBBacklight", enc.kb_static_backlight(kb["brightness"]))
        for zone in range(1, enc.KB_ZONES + 1):
            color = kb["zone_colors"][zone - 1] if kb["zones_on"][zone - 1] else "#000000"
            self._ok("SetGamingRgbKb", enc.kb_zone_color(
                zone, enc.parse_hex_color(color), self.adjust))

    # ----------------------------------------------------------- helpers
    def _ok(self, method: str, value: int) -> int:
        out = self.wmi.call(method, value)
        if out & 0xFF:
            raise WmiError(f"{method}({value:#x}) returned status {out & 0xFF:#x}")
        return out


def wait_for_acpi_call(timeout: float = 20.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if os.path.exists("/proc/acpi/call"):
            return True
        time.sleep(0.5)
    return os.path.exists("/proc/acpi/call")
