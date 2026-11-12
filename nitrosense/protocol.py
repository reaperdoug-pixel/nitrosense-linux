"""Daemon <-> GUI protocol: one JSON object per line over a Unix socket."""

SOCKET_DIR = "/run/nitrosense"
SOCKET_PATH = SOCKET_DIR + "/nitrosense.sock"
ALLOWED_USERS_FILE = "/etc/nitrosense/allowed-users"
STATE_DIR = "/var/lib/nitrosense"
STATE_FILE = STATE_DIR + "/state.json"
HISTORY_DIR = STATE_DIR + "/history"
MAX_REQUEST = 64 * 1024

DEFAULT_ZONE_COLOR = "#FF0000"  # HW_Support.ini [ZoneDefaultColor] for AN515-44


def _default_curve() -> list:
    from .fancurve import DEFAULT_POINTS
    return [list(p) for p in DEFAULT_POINTS]


def default_state(zone_colors: list[str] | None = None) -> dict:
    colors = list(zone_colors or [DEFAULT_ZONE_COLOR] * 4)
    return {
        "fan": {"mode": "auto", "cpu_auto": False, "gpu_auto": False,
                "cpu_percent": 50, "gpu_percent": 50},
        "fan_curve": {"points": _default_curve()},
        "coolboost": None,
        "keyboard": {
            "mode": "static",
            "brightness": 5,
            "zones_on": [True, True, True, True],
            "zone_colors": colors,
            "effect": "wave",
            "speed": 3,  # NitroSense uses 5; users found that fast on the AN515-44
            "direction": 1,
            "effect_color": colors[0],
        },
        "keyboard_applied": False,
        "lcd_overdrive": None,
        "win_key": None,
        "backlight_timeout": None,
        "battery_limit": None,
        "power": {"ac": "balance", "battery": "balance"},
        "power_applied": False,
    }
