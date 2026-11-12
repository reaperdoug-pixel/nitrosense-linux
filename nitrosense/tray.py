"""System tray icon for the alert watcher (XApp status icon: Cinnamon, MATE, XFCE, KDE...).

The icon changes with the most serious alert (normal / attention / critical), the tooltip and the
menu show live numbers, a click opens the dashboard, and the menu switches the fan mode and the
80 % charge limit. GTK 3 and XApp live in the watcher process only (the dashboard is GTK 4), and
everything is optional: without XApp or a display, create() returns None and the watcher keeps
sending notifications.
"""

from __future__ import annotations

import json
import os

from . import battery as battery_mod
from .disks import CRIT, WARN

ICONS = {0: "nitrosense-tray", WARN: "nitrosense-tray-warning", CRIT: "nitrosense-tray-critical"}
FAN_MODES = (("auto", "Automático"), ("max", "Máx"), ("curve", "Curva"))
PREFS = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                     "nitrosense", "gui.json")


def unit_preference(path: str = PREFS) -> str:
    try:
        with open(path) as f:
            return "F" if json.load(f).get("unit") == "F" else "C"
    except (OSError, ValueError):
        return "C"


def _temp(c, unit: str) -> str:
    if c is None:
        return "--"
    return f"{round(c * 9 / 5 + 32)} °F" if unit == "F" else f"{round(c)} °C"


def summary(status: dict | None, bats: list, unit: str = "C") -> dict:
    """Plain-language lines for the tooltip and the menu. status None = service unreachable."""
    if not status:
        return {"cpu": "Serviço do NitroSense indisponível", "gpu": "", "ssd": "", "battery": ""}
    s = status.get("sensors", {})
    cpu = f"CPU {_temp(s.get('cpu_temp'), unit)}"
    if s.get("cpu_fan"):
        cpu += f" · {s['cpu_fan']} RPM"
    if s.get("cpu_power") is not None:
        cpu += f" · {s['cpu_power']:.0f} W"
    gpu_temp = s.get("gpu_temp")
    gpu = "GPU suspensa" if not gpu_temp else f"GPU {_temp(gpu_temp, unit)}"
    if gpu_temp and s.get("gpu_fan"):
        gpu += f" · {s['gpu_fan']} RPM"
    ssd = ""
    from . import disks
    temp = disks.hottest_temp()
    if temp is not None:
        ssd = f"SSD {_temp(temp, unit)}"
    bat = ""
    if bats:
        b = bats[0]
        bat = "Bateria " + ("--" if b["capacity"] is None else f"{b['capacity']:.0f}%")
        bat += f" ({battery_mod.STATUS_PT.get(b['status'], b['status']).lower()})"
        if b["health"] is not None:
            bat += f" · saúde {b['health']:.0f}%"
    return {"cpu": cpu, "gpu": gpu, "ssd": ssd, "battery": bat}


def tooltip(lines: dict, alerts: list) -> str:
    parts = ["NitroSense"] + [v for v in (lines["cpu"], lines["gpu"], lines["ssd"], lines["battery"]) if v]
    if alerts:
        parts.append("⚠ " + alerts[0][2])
    return "\n".join(parts)


def icon_for(alerts: list, reachable: bool = True) -> str:
    level = max((a[0] for a in alerts), default=0)
    if not reachable:
        level = max(level, WARN)
    return ICONS[CRIT if level >= CRIT else WARN if level >= WARN else 0]


class Tray:
    """The XApp icon and its menu. `actions` is a dict of callables: open, set_fan, set_limit, quit."""

    def __init__(self, actions: dict) -> None:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("XApp", "1.0")
        from gi.repository import Gtk, XApp
        self.Gtk, self.actions = Gtk, actions
        self._updating = False
        self.icon = XApp.StatusIcon()
        self.icon.set_name("nitrosense")
        self.icon.set_icon_name(self._icon(ICONS[0]))
        self.icon.set_tooltip_text("NitroSense")
        self.icon.connect("activate", lambda *_: actions["open"]())

        menu = Gtk.Menu()
        self.menu = menu
        item = Gtk.MenuItem(label="Abrir NitroSense")
        item.connect("activate", lambda *_: actions["open"]())
        menu.append(item)
        menu.append(Gtk.SeparatorMenuItem())
        self.info = {}
        for key in ("cpu", "gpu", "ssd", "battery"):
            self.info[key] = Gtk.MenuItem(label="--")
            self.info[key].set_sensitive(False)
            menu.append(self.info[key])
        self.alert_item = Gtk.MenuItem(label="")
        self.alert_item.set_sensitive(False)
        menu.append(self.alert_item)
        menu.append(Gtk.SeparatorMenuItem())

        fan = Gtk.MenuItem(label="Ventoinha")
        sub = Gtk.Menu()
        self.fan_items, group = {}, None
        for mode, label in FAN_MODES:
            radio = Gtk.RadioMenuItem.new_with_label_from_widget(group, label)
            group = group or radio
            radio.connect("toggled", self._fan_toggled, mode)
            sub.append(radio)
            self.fan_items[mode] = radio
        fan.set_submenu(sub)
        menu.append(fan)
        self.limit_item = Gtk.CheckMenuItem(label="Limitar a carga a 80%")
        self.limit_item.connect("toggled", self._limit_toggled)
        menu.append(self.limit_item)
        menu.append(Gtk.SeparatorMenuItem())
        quit_item = Gtk.MenuItem(label="Sair (para os alertas também)")
        quit_item.connect("activate", lambda *_: actions["quit"]())
        menu.append(quit_item)
        menu.show_all()
        self.limit_item.set_visible(False)
        self.icon.set_secondary_menu(menu)
        self.icon.set_visible(True)

    # ----------------------------------------------------------- callbacks
    def _icon(self, name: str) -> str:
        """The themed icon when installed; otherwise the file in the source tree (running from git)."""
        if self.Gtk.IconTheme.get_default().has_icon(name):
            return name
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
                            "data", "icons", name + ".svg")
        return path if os.path.exists(path) else name

    def _fan_toggled(self, radio, mode: str) -> None:
        if radio.get_active() and not self._updating:
            self.actions["set_fan"](mode)

    def _limit_toggled(self, item) -> None:
        if not self._updating:
            self.actions["set_limit"](item.get_active())

    # -------------------------------------------------------------- update
    def update(self, status: dict | None, alerts: list, bats: list, unit: str = "C") -> None:
        lines = summary(status, bats, unit)
        self.icon.set_icon_name(self._icon(icon_for(alerts, bool(status))))
        self.icon.set_tooltip_text(tooltip(lines, alerts))
        self._updating = True
        try:
            for key, item in self.info.items():
                item.set_label(lines[key] or "--")
                item.set_visible(bool(lines[key]))
            self.alert_item.set_label("⚠ " + alerts[0][2] if alerts else "")
            self.alert_item.set_visible(bool(alerts))
            if status:
                state = status.get("state", {})
                mode = state.get("fan", {}).get("mode")
                if mode in self.fan_items:
                    self.fan_items[mode].set_active(True)
                hw = status.get("hw", {})
                cal = (hw.get("battery_calibration") or {}).get("active")
                self.limit_item.set_visible(bool(hw.get("battery_limit_supported")))
                self.limit_item.set_sensitive(not cal)
                self.limit_item.set_active(bool(hw.get("battery_limit")))
        finally:
            self._updating = False

    def destroy(self) -> None:
        self.icon.set_visible(False)


def create(actions: dict):
    """The tray, or None when XApp / GTK 3 / a display is not available."""
    try:
        return Tray(actions)
    except Exception as e:  # ImportError, ValueError (missing typelib), no display, ...
        print(f"tray icon unavailable: {e}", flush=True)
        return None
