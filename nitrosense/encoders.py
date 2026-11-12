"""Bit-exact WMI input encoders, reverse engineered from Acer NitroSense 3.01.3056.

Every function here mirrors one method of NitroSense.exe (namespace NitroSense,
class CommonFunction / Popup_Lighting / LightingDynamicUI / Nitro_MainWindow_Octavia)
and returns the integer that the Windows app hands to its service, which passes
it unchanged to the named WMI method of class AcerGamingFunction or APGeAction.

The functions are pure so they can be unit tested without hardware.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ---------------------------------------------------------------- fans ----

FAN_CPU = "cpu"
FAN_GPU = "gpu"

# Fan_Mode_Type enum: Auto=0, Max=1, Custom=2
FAN_MODE_AUTO = "auto"
FAN_MODE_MAX = "max"
FAN_MODE_CUSTOM = "custom"

# Per-fan behaviour codes inside SetGamingFanBehavior (2 bits per fan).
_BEHAVIOR_AUTO = 1
_BEHAVIOR_MAX = 2
_BEHAVIOR_CUSTOM = 3

# Fan bitmap / speed ids: CPU fan = bit 0 (id 1), GPU fan = bit 3 (id 4).
_FAN_BITMAP_ALL = 0x9
_FAN_SPEED_ID = {FAN_CPU: 1, FAN_GPU: 4}
_FAN_BEHAVIOR_SHIFT = {FAN_CPU: 16, FAN_GPU: 22}


def fan_mode_all(mode: str) -> int:
    """CommonFunction.set_all_fan_mode -> SetGamingFanBehavior.

    Auto: 0x410009, Max: 0x820009, Custom: 0xC30009.
    """
    code = {FAN_MODE_AUTO: _BEHAVIOR_AUTO, FAN_MODE_MAX: _BEHAVIOR_MAX,
            FAN_MODE_CUSTOM: _BEHAVIOR_CUSTOM}[mode]
    return _FAN_BITMAP_ALL | (code << 16) | (code << 22)


def fan_custom_behavior(cpu_auto: bool, gpu_auto: bool) -> int:
    """CommonFunction.set_all_custom_fan_state, first call -> SetGamingFanBehavior."""
    cpu = _BEHAVIOR_AUTO if cpu_auto else _BEHAVIOR_CUSTOM
    gpu = _BEHAVIOR_AUTO if gpu_auto else _BEHAVIOR_CUSTOM
    return _FAN_BITMAP_ALL | (cpu << 16) | (gpu << 22)


def fan_speed(fan: str, percent: int) -> int:
    """CommonFunction.set_single_custom_fan_speed -> SetGamingFanSpeed.

    percent is the slider value (0..10) * 10, i.e. 0..100 in steps of 10.
    """
    percent = _clamp(int(percent), 0, 100)
    return _FAN_SPEED_ID[fan] | (percent << 8)


def sysinfo_query(index: int) -> int:
    """CommonFunction.get_wmi_system_health_info -> GetGamingSysInfo input."""
    return 1 | ((index & 0xFF) << 8)


def sysinfo_value(output: int) -> int | None:
    """Decode GetGamingSysInfo output: status in byte 0, value in bytes 1..2."""
    if output & 0xFF:
        return None
    return (output >> 8) & 0xFFFF


# System_Health_Information_Index enum
SENSOR_CPU_TEMP = 1
SENSOR_CPU_FAN = 2
SENSOR_SYSTEM_TEMP = 3
SENSOR_GPU_FAN = 6
SENSOR_GPU_TEMP = 10

# ------------------------------------------------------- APGeAction -------

def coolboost_set(on: bool) -> int:
    """CommonFunction.set_coolboost_state -> APGeAction.SetFunction."""
    return 7 | ((1 if on else 0) << 16)


COOLBOOST_GET = 0x207  # CommonFunction.get_coolboost_state -> APGeAction.GetFunction


def coolboost_decode(output: int) -> bool | None:
    if output & 0xFF:
        return None
    return ((output >> 8) & 0xFF) == 1


def backlight_get(hotkey_number: int) -> int:
    """CommonFunction.get_backlight_off / get_backlight_brightness_percentage."""
    return 1 | ((hotkey_number & 0xFF) << 8) | 0x80000


def backlight_decode(output: int) -> tuple[int, bool] | None:
    """-> (brightness percentage, backlight-timeout enabled)."""
    if output & 0xFF:
        return None
    return (output >> 32) & 0xFF, ((output >> 40) & 0xFF) == 30


def backlight_timeout_set(hotkey_number: int, brightness_percent: int, enabled: bool) -> int:
    """Nitro_MainWindow_Octavia.Backlightoff_Checkbox_(Un)Checked -> APGeAction.SetFunction.

    Enabled turns the keyboard backlight off after 30 seconds of inactivity.
    """
    value = 2 | ((hotkey_number & 0xFF) << 8) | 0x80000
    value |= (brightness_percent & 0xFF) << 32
    if enabled:
        value |= 30 << 40
    return value


# --------------------------------------------------- gaming profile -------

def win_key_set(enabled: bool) -> int:
    """CommonFunction.set_win_menu_key_status -> SetGamingProfile."""
    return 2 | ((1 if enabled else 0) << 24)


def lcd_overdrive_set(on: bool) -> int:
    """CommonFunction.set_lcd_over_drive -> SetGamingProfile."""
    return 0x10 | ((1 << 48) if on else 0)


LCD_OVERDRIVE_GET = 0  # CommonFunction.get_lcd_over_drive -> GetGamingProfile(0)


def lcd_overdrive_decode(output: int) -> bool | None:
    if output & 0xFF:
        return None
    return ((output >> 48) & 0xFF) == 1


# ---------------------------------------------------- misc settings -------

GPU_MODE_SUPPORT_GET = 9   # CommonFunction.Get_GPUMode_Support -> GetGamingMiscSetting(9)
GPU_MODE_GET = 2           # CommonFunction.Get_System_GPUMode -> GetGamingMiscSetting(2)


def gpu_mode_supported(output: int) -> bool:
    return ((output >> 8) & 0xFF) == 3


def gpu_mode_decode(output: int) -> int:
    """1 = discrete only, 2 = hybrid (others: unknown -> 0)."""
    v = (output >> 8) & 0xFF
    return v if v in (1, 2, 3) else 0


def gpu_mode_set(discrete_only: bool) -> int:
    """CommonFunction.Set_System_GPUMode -> SetGamingMiscSetting (takes effect after reboot)."""
    return 2 | ((1 if discrete_only else 2) << 8)


# --------------------------------------------------------- keyboard -------

KB_ZONES = 4
ZONE_BITS = (1, 2, 4, 8)

# LightingDynamicUI radio Tag -> firmware effect id
EFFECT_BREATHING = "breathing"   # Tag 0
EFFECT_WAVE = "wave"             # Tag 1
EFFECT_ZOOM = "zoom"             # Tag 2
EFFECT_SHIFTING = "shifting"     # Tag 3
EFFECT_NEON = "neon"             # Tag 4
EFFECTS = (EFFECT_BREATHING, EFFECT_WAVE, EFFECT_ZOOM, EFFECT_SHIFTING, EFFECT_NEON)
_EFFECT_MODE = {EFFECT_BREATHING: 1, EFFECT_NEON: 2, EFFECT_WAVE: 3,
                EFFECT_SHIFTING: 4, EFFECT_ZOOM: 5}
EFFECT_HAS_COLOR = {EFFECT_BREATHING: True, EFFECT_NEON: False, EFFECT_WAVE: True,
                    EFFECT_SHIFTING: True, EFFECT_ZOOM: True}
EFFECT_HAS_DIRECTION = {EFFECT_BREATHING: False, EFFECT_NEON: False, EFFECT_WAVE: True,
                        EFFECT_SHIFTING: True, EFFECT_ZOOM: False}

DIRECTION_RIGHT = 1  # Direction4way1, "Direction Right"
DIRECTION_LEFT = 2   # Direction4way2, "Direction Left"


@dataclass(frozen=True)
class ColorAdjust:
    """HW_Support.ini [ZoneColorAdjust]; AN515-44 ships 1.0/1.0/1.0."""
    r: float = 1.0
    g: float = 1.0
    b: float = 1.0

    def apply(self, rgb: tuple[int, int, int]) -> tuple[int, int, int]:
        r, g, b = rgb
        return (_clamp(math.floor(r * self.r), 0, 255),
                _clamp(math.floor(g * self.g), 0, 255),
                _clamp(math.floor(b * self.b), 0, 255))


def brightness_raw(level: int) -> int:
    """Brightness slider 1..5 -> firmware 0,25,50,75,100 ((level-1)*25)."""
    return (_clamp(int(level), 1, 5) - 1) * 25


def kb_static_backlight(level: int) -> int:
    """Popup_Lighting.Change_Keyboard_Brightness -> SetGamingKBBacklight (static mode 0)."""
    return brightness_raw(level) << 16


def kb_dynamic_backlight(effect: str, speed: int, level: int, direction: int,
                         rgb: tuple[int, int, int], adjust: ColorAdjust = ColorAdjust()) -> int:
    """LightingDynamicUI.Set_Dynamic_Keyboard -> SetGamingKBBacklight."""
    mode = _EFFECT_MODE[effect]
    speed = _clamp(int(speed), 1, 9)
    value = mode | (speed << 8) | (brightness_raw(level) << 16)
    if effect == EFFECT_WAVE:
        value |= 0x08 << 24
    if EFFECT_HAS_DIRECTION[effect]:
        value |= (DIRECTION_LEFT if direction == DIRECTION_LEFT else DIRECTION_RIGHT) << 32
    if EFFECT_HAS_COLOR[effect]:
        r, g, b = adjust.apply(rgb)
        value |= (r << 40) | (g << 48) | (b << 56)
    return value


def kb_zone_color(zone: int, rgb: tuple[int, int, int], adjust: ColorAdjust = ColorAdjust()) -> int:
    """Popup_Lighting.Change_Zone_Color -> SetGamingRgbKb. zone is 1..4."""
    if not 1 <= zone <= KB_ZONES:
        raise ValueError("zone must be 1..4")
    r, g, b = adjust.apply(rgb)
    return ZONE_BITS[zone - 1] | (r << 8) | (g << 16) | (b << 24)


def kb_zone_enable(enabled: tuple[bool, bool, bool, bool]) -> int:
    """Popup_Lighting.Change_Zone_Status -> SetGamingLEDBehavior."""
    value = 8
    for i, on in enumerate(enabled):
        if on:
            value |= 1 << (40 + i)
    return value


def int_to_bytes(value: int, size: int) -> bytes:
    return int(value).to_bytes(size, "little", signed=False)


def bytes_to_int(data: bytes) -> int:
    return int.from_bytes(bytes(data[:8]), "little", signed=False)


def parse_hex_color(text: str) -> tuple[int, int, int]:
    t = text.strip().lstrip("#")
    if len(t) == 8:  # AARRGGBB
        t = t[2:]
    if len(t) != 6:
        raise ValueError(f"bad color {text!r}")
    return int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16)


def _clamp(v: int, lo: int, hi: int) -> int:
    return lo if v < lo else hi if v > hi else v


# ---------------------------------------------------------------- battery charge limit
BATTERY_HEALTH_GET = 0x0101  # battery 1, query 1
BATTERY_HEALTH_MODE = 1      # function bit: charge limit
BATTERY_CALIBRATION_MODE = 2  # function bit: calibration (charge, discharge, recharge)


def battery_function_set(function: int, on: bool) -> int:
    """SetBatteryHealth input: battery 1, function mask, status 0/1."""
    return 1 | (function << 8) | (int(on) << 16)


def battery_health_set(on: bool) -> int:
    return battery_function_set(BATTERY_HEALTH_MODE, on)


def battery_calibration_set(on: bool) -> int:
    return battery_function_set(BATTERY_CALIBRATION_MODE, on)


def battery_health_decode(output: int) -> bool | None:
    """GetBatteryHealth output: byte 0 lists supported functions, byte 3 is the health mode state.
    -> None when the firmware does not support the charge limit."""
    if not output & BATTERY_HEALTH_MODE:
        return None
    return ((output >> 24) & 0xFF) > 0


def battery_calibration_decode(output: int) -> bool | None:
    """GetBatteryHealth output: byte 4 is the calibration state. None = not supported."""
    if not output & BATTERY_CALIBRATION_MODE:
        return None
    return ((output >> 32) & 0xFF) > 0
