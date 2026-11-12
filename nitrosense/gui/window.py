"""NitroSense main window: purple dashboard with Home / Scenario / Monitoring tabs."""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from collections import deque

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from .. import APP_ID, alerts, battery, disks, fancurve, history, procs, set_process_name, watcher  # noqa: E402
from .. import model as model_cfg  # noqa: E402
from ..client import Client, DaemonError  # noqa: E402
from ..protocol import default_state  # noqa: E402
from ..sysmon import CpuLoad, GpuMonitor, gpu_throttle  # noqa: E402
from .widgets import (ACCENT, ACCENT_LIGHT, CSS, FanCurveEditor, Gauge, History,  # noqa: E402
                      TimeChart)

PREFS = os.path.join(GLib.get_user_config_dir(), "nitrosense", "gui.json")

PLAN_NAMES = {"powersaver": "Silencioso", "balance": "Equilibrado", "performance": "Desempenho"}
FAN_NAMES = {"auto": "Automático", "max": "Máx", "custom": "Personalizado", "curve": "Curva"}
GPU_SUSPENDED = "GPU dedicada suspensa (economizando energia)"


class Worker:
    """Runs daemon requests off the UI thread; callbacks come back on the UI thread."""

    def __init__(self) -> None:
        self.q: queue.Queue = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, fn, done=None, fail=None) -> None:
        self.q.put((fn, done, fail))

    def _run(self) -> None:
        while True:
            fn, done, fail = self.q.get()
            try:
                res = fn()
            except Exception as e:  # reported on the UI thread
                if fail:
                    GLib.idle_add(fail, e)
                continue
            if done:
                GLib.idle_add(done, res)


def _lbl(text: str, *classes: str, xalign: float = 0.0) -> Gtk.Label:
    lbl = Gtk.Label(label=text)
    for c in classes:
        lbl.add_css_class(c)
    lbl.set_xalign(xalign)
    return lbl


def _box(orientation=Gtk.Orientation.VERTICAL, spacing: int = 8, *classes: str) -> Gtk.Box:
    b = Gtk.Box(orientation=orientation, spacing=spacing)
    for c in classes:
        b.add_css_class(c)
    return b


def _card(spacing: int = 10) -> Gtk.Box:
    return _box(Gtk.Orientation.VERTICAL, spacing, "ns-card")


def _switch() -> Gtk.Switch:
    sw = Gtk.Switch()
    sw.set_valign(Gtk.Align.CENTER)
    return sw


def _conv(c, unit: str) -> str:
    if c is None:
        return "--"
    return str(round(c * 9 / 5 + 32)) if unit == "F" else str(round(c))


def _ram_used_gb() -> float | None:
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key, _, rest = line.partition(":")
                info[key] = int(rest.split()[0])
        return (info["MemTotal"] - info["MemAvailable"]) / 1048576
    except (OSError, KeyError, ValueError, IndexError):
        return None


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application) -> None:
        super().__init__(application=app, title="NitroSense")
        self.add_css_class("nitrosense")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(1180, 700)
        self.set_icon_name(APP_ID)

        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.model = model_cfg.load()
        self.client = Client()
        self.worker = Worker()
        self.cpu_load = CpuLoad()
        self.gpu = GpuMonitor()
        self.prefs = self._load_prefs()
        self.state = default_state(self.model.zone_default_colors)
        self.hw: dict = {}
        self.ac_online = True
        self.plan_source = "ac"
        self._poll_busy = False
        self._status_is_error = False
        self._updating = False
        self._layout_flags = None
        self._fan_timer = {"cpu": 0, "gpu": 0}
        self._current: dict = {}
        self.smart: dict = {}
        self._poll_n = 0
        self._disk_basic: list[dict] = []
        self._disk_assess: list[tuple[dict, dict]] = []
        self._notified: dict[str, int] = {}
        self._hist_range = self.prefs.get("hist_range", "24h")
        if self._hist_range not in history.RANGES:
            self._hist_range = "24h"
        self._hist_busy = False
        self._hist_loaded = 0.0
        self._hist_data = None
        self._bats: list[dict] = []
        self._bat_assess: list[tuple[dict, dict]] = []
        self._throttle: dict = {}
        self._gpu_perf: dict = {}
        self._gpu_slow: dict = {}  # the service's view of GPU slowdown (also runs with no window)
        self.sampler = procs.ProcessSampler()
        self._procs_busy = False
        self._procs_at = 0.0
        self._procs_n = 0
        self._holders: list | None = None
        self._pw: deque = deque(maxlen=60)  # last minute of battery power, to steady the ETA
        self._pw_status = ""
        self.disk_ui: dict[str, dict] = {}
        self.rpm: dict = {}
        self.sticky_settings = None

        root = _box(Gtk.Orientation.VERTICAL, 0)
        self.set_child(root)
        root.append(self._build_header())
        self.alert_bar = _lbl("", "ns-alert")
        self.alert_bar.set_wrap(True)
        self.alert_bar.set_visible(False)
        root.append(self.alert_bar)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_vexpand(True)
        self.stack.set_margin_start(20)
        self.stack.set_margin_end(20)
        self.stack.add_named(self._build_home(), "home")
        self.stack.add_named(self._build_scenario(), "scenario")
        self.stack.add_named(self._build_disks(), "disks")
        self.stack.add_named(self._build_battery(), "battery")
        self.stack.add_named(self._build_monitor(), "monitor")
        self.stack.add_named(self._build_procs(), "procs")
        self.stack.add_named(self._build_history(), "history")
        root.append(self.stack)
        self.status_label = _lbl("", "ns-status", xalign=0.5)
        self.status_label.set_margin_top(6)
        self.status_label.set_margin_bottom(10)
        self.status_label.set_size_request(-1, 20)
        root.append(self.status_label)

        self._build_settings()
        page = self.prefs.get("page")
        if page in self.nav_buttons:
            self._goto(page)
        self._update_fan_ui()
        self._show_plan_tab("ac")
        self._poll()
        GLib.timeout_add(1000, self._poll)

    # ================================================================ header
    def _build_header(self) -> Gtk.Widget:
        handle = Gtk.WindowHandle()
        bar = Gtk.CenterBox()
        bar.set_margin_start(20)
        bar.set_margin_end(14)
        bar.set_margin_top(14)
        bar.set_margin_bottom(12)
        handle.set_child(bar)
        bar.set_start_widget(_lbl("NITROSENSE", "ns-title"))

        nav = _box(Gtk.Orientation.HORIZONTAL, 4, "ns-nav")
        first = None
        self.nav_buttons = {}
        for key, text in (("home", "Início"), ("scenario", "Cenário"), ("disks", "Discos"),
                          ("battery", "Bateria"), ("monitor", "Monitoramento"),
                          ("procs", "Processos"), ("history", "Histórico")):
            b = Gtk.ToggleButton(label=text)
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.connect("toggled", self._nav_toggled, key)
            nav.append(b)
            self.nav_buttons[key] = b
        first.set_active(True)
        bar.set_center_widget(nav)

        win = _box(Gtk.Orientation.HORIZONTAL, 2, "ns-win")
        self.settings_button = Gtk.MenuButton(icon_name="emblem-system-symbolic")
        self.settings_button.set_tooltip_text("Configurações")
        win.append(self.settings_button)
        mini = Gtk.Button.new_from_icon_name("window-minimize-symbolic")
        mini.set_tooltip_text("Minimizar")
        mini.connect("clicked", lambda *_: self.minimize())
        win.append(mini)
        close = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close.set_tooltip_text("Fechar")
        close.connect("clicked", lambda *_: self.close())
        win.append(close)
        bar.set_end_widget(win)
        return handle

    def _nav_toggled(self, button: Gtk.ToggleButton, key: str) -> None:
        if button.get_active() and hasattr(self, "stack"):
            self.stack.set_visible_child_name(key)
            if key in ("history", "battery"):
                self._load_history(force=True)
            if key == "procs":
                self._load_procs(force=True)
            if self.prefs.get("page") != key:
                self.prefs["page"] = key
                self._save_prefs()

    def _goto(self, key: str) -> None:
        self.nav_buttons[key].set_active(True)

    # ================================================================== home
    def _build_home(self) -> Gtk.Widget:
        page = _box(Gtk.Orientation.HORIZONTAL, 14)
        page.set_homogeneous(False)

        gpu = _card(8)
        gpu.set_size_request(290, -1)
        gpu.append(_lbl("GPU", "ns-h"))
        self.g_gpu_load = Gauge(200)
        self.g_gpu_load.set_vexpand(True)
        self.g_gpu_load.set_valign(Gtk.Align.CENTER)
        gpu.append(self.g_gpu_load)
        row = _box(Gtk.Orientation.HORIZONTAL, 0)
        row.set_homogeneous(True)
        for attr, title in (("home_gpu_load", "Uso da GPU"), ("home_cpu_load", "Uso da CPU")):
            col = _box(Gtk.Orientation.VERTICAL, 2)
            lab = _lbl("--%", "ns-mid", xalign=0.5)
            setattr(self, attr, lab)
            col.append(lab)
            col.append(_lbl(title, "ns-dim", xalign=0.5))
            row.append(col)
        gpu.append(row)
        page.append(gpu)

        mid = _card(14)
        mid.set_hexpand(True)
        mid.append(_lbl("Temperatura e ventoinhas", "ns-h"))
        gauges = _box(Gtk.Orientation.HORIZONTAL, 0)
        gauges.set_homogeneous(True)
        gauges.set_vexpand(True)
        self.g_temp = {}
        self.rpm_labels = {}
        self.pw_labels = {}
        self.fan_cols = {}
        for name, title, enabled in (("cpu", "CPU", self.model.fan_cpu),
                                     ("gpu", "GPU", self.model.fan_gpu)):
            col = _box(Gtk.Orientation.VERTICAL, 8)
            col.set_valign(Gtk.Align.CENTER)
            g = Gauge(170, ACCENT if name == "cpu" else ACCENT_LIGHT)
            self.g_temp[name] = g
            col.append(g)
            col.append(_lbl(f"Temperatura da {title}", "ns-dim", xalign=0.5))
            rpm = _lbl("-- RPM", "ns-mid", xalign=0.5)
            self.rpm_labels[name] = rpm
            col.append(rpm)
            col.append(_lbl(f"Ventoinha da {title}", "ns-dim", xalign=0.5))
            watts = _lbl("-- W", "ns-mid", xalign=0.5)
            watts.set_margin_top(6)
            self.pw_labels[name] = watts
            col.append(watts)
            col.append(_lbl(f"Consumo da {title}", "ns-dim", xalign=0.5))
            col.set_visible(enabled)
            self.fan_cols[name] = col
            gauges.append(col)
        mid.append(gauges)
        perf = _box(Gtk.Orientation.VERTICAL, 4)
        perf.set_margin_bottom(6)
        self.perf_chip = _lbl("--", "ns-chip")
        self.perf_chip.set_halign(Gtk.Align.CENTER)
        perf.append(self.perf_chip)
        self.perf_detail = _lbl("", "ns-dim", xalign=0.5)
        self.perf_detail.set_wrap(True)
        perf.append(self.perf_detail)
        mid.append(perf)
        page.append(mid)

        side = _card(6)
        side.set_size_request(330, -1)
        side.append(_lbl("Perfil de cenário", "ns-h"))
        rows = _box(Gtk.Orientation.VERTICAL, 0)
        self.prof_vals = {}
        for key, title in (("mode", "Modo"), ("fan", "Ventoinha"), ("coolboost", "CoolBoost")):
            r = _box(Gtk.Orientation.HORIZONTAL, 6, "ns-row")
            lab = _lbl(title)
            lab.set_hexpand(True)
            r.append(lab)
            val = _lbl("--", "ns-accent")
            self.prof_vals[key] = val
            r.append(val)
            rows.append(r)
        side.append(rows)
        more = Gtk.Button(label="Detalhes ›")
        more.add_css_class("ns-link")
        more.set_halign(Gtk.Align.START)
        more.connect("clicked", lambda *_: self._goto("scenario"))
        side.append(more)

        mon = _lbl("Monitoramento", "ns-h")
        mon.set_margin_top(10)
        side.append(mon)
        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        grid.set_column_homogeneous(True)
        self.tiles = {}
        for i, (key, title) in enumerate((("cpu_temp", "CPU"), ("gpu_temp", "GPU"),
                                          ("cpu_load", "Carga da CPU"), ("ram", "RAM"),
                                          ("disk_temp", "SSD"), ("disk_health", "Saúde do SSD"),
                                          ("battery", "Bateria"), ("bat_health", "Saúde da bateria"))):
            tile = _box(Gtk.Orientation.VERTICAL, 2, "ns-tile")
            tile.append(_lbl(title, "ns-dim"))
            val = _lbl("--", "ns-mid")
            self.tiles[key] = val
            tile.append(val)
            grid.attach(tile, i % 2, i // 2, 1, 1)
        side.append(grid)
        more2 = Gtk.Button(label="Histórico ›")
        more2.add_css_class("ns-link")
        more2.set_halign(Gtk.Align.START)
        more2.connect("clicked", lambda *_: self._goto("history"))
        side.append(more2)
        page.append(side)
        return page

    # ============================================================== scenario
    def _build_scenario(self) -> Gtk.Widget:
        page = _box(Gtk.Orientation.VERTICAL, 14)

        power = _card(12)
        head = _box(Gtk.Orientation.HORIZONTAL, 8)
        title = _lbl("Modo de energia", "ns-h")
        title.set_hexpand(True)
        head.append(title)
        self.seg_buttons = {}
        first = None
        for key, text in (("ac", "Na tomada"), ("battery", "Na bateria")):
            b = Gtk.ToggleButton(label=text)
            b.add_css_class("ns-seg")
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.connect("toggled", self._seg_toggled, key)
            head.append(b)
            self.seg_buttons[key] = b
        power.append(head)
        modes = _box(Gtk.Orientation.HORIZONTAL, 12)
        modes.set_homogeneous(True)
        self.plan_buttons = {}
        first = None
        for plan, sub in (("powersaver", "Economiza energia e reduz o ruído"),
                          ("balance", "Uso diário"),
                          ("performance", "Máxima potência")):
            b = Gtk.ToggleButton()
            b.add_css_class("ns-mode")
            inner = _box(Gtk.Orientation.VERTICAL, 4)
            inner.append(_lbl(PLAN_NAMES[plan], "ns-mid", xalign=0.5))
            inner.append(_lbl(sub, "ns-dim", xalign=0.5))
            b.set_child(inner)
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.connect("toggled", self._plan_toggled, plan)
            modes.append(b)
            self.plan_buttons[plan] = b
        power.append(modes)
        page.append(power)

        fan = _card(12)
        head = _box(Gtk.Orientation.HORIZONTAL, 8)
        title = _lbl("Controle de ventoinha", "ns-h")
        title.set_hexpand(True)
        head.append(title)
        fan.append(head)
        fmodes = _box(Gtk.Orientation.HORIZONTAL, 12)
        fmodes.set_homogeneous(True)
        self.fan_buttons = {}
        first = None
        for mode, sub in (("auto", "O notebook controla"), ("max", "Rotação máxima"),
                          ("custom", "Você define a velocidade"),
                          ("curve", "Velocidade pela temperatura")):
            b = Gtk.ToggleButton()
            b.add_css_class("ns-mode")
            inner = _box(Gtk.Orientation.VERTICAL, 4)
            inner.append(_lbl(FAN_NAMES[mode], "ns-mid", xalign=0.5))
            inner.append(_lbl(sub, "ns-dim", xalign=0.5))
            b.set_child(inner)
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.connect("toggled", self._fan_toggled, mode)
            fmodes.append(b)
            self.fan_buttons[mode] = b
        fan.append(fmodes)

        cb = _box(Gtk.Orientation.HORIZONTAL, 10, "ns-row")
        txt = _box(Gtk.Orientation.VERTICAL, 2)
        txt.set_hexpand(True)
        txt.append(_lbl("CoolBoost™"))
        txt.append(_lbl("Aumenta a rotação máxima das ventoinhas. Funciona só no modo Automático.",
                        "ns-dim"))
        cb.append(txt)
        self.coolboost = _switch()
        self.coolboost.connect("notify::active", self._switch_changed, self._coolboost_toggled)
        cb.append(self.coolboost)
        self.coolboost_row = cb
        fan.append(cb)

        self.custom_box = _box(Gtk.Orientation.HORIZONTAL, 30)
        self.custom_box.set_homogeneous(True)
        self.sliders, self.autos, self.slider_vals, self.slider_cols = {}, {}, {}, {}
        for name, title, enabled in (("cpu", "CPU", self.model.fan_cpu),
                                     ("gpu", "GPU", self.model.fan_gpu)):
            col = _box(Gtk.Orientation.VERTICAL, 6)
            top = _box(Gtk.Orientation.HORIZONTAL, 8)
            lab = _lbl(f"Ventoinha da {title}")
            lab.set_hexpand(True)
            top.append(lab)
            val = _lbl("0%", "ns-accent")
            self.slider_vals[name] = val
            top.append(val)
            col.append(top)
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 10, 1)
            scale.set_draw_value(False)
            scale.set_hexpand(True)
            scale.connect("change-value", self._scale_changed, name)
            self.sliders[name] = scale
            col.append(scale)
            bot = _box(Gtk.Orientation.HORIZONTAL, 8)
            alab = _lbl("Automático", "ns-dim")
            alab.set_hexpand(True)
            bot.append(alab)
            sw = _switch()
            sw.connect("notify::active", self._switch_changed,
                       lambda _w, on, n=name: self._fan_auto(n, on))
            self.autos[name] = sw
            bot.append(sw)
            col.append(bot)
            col.set_visible(enabled)
            self.slider_cols[name] = col
            self.custom_box.append(col)
        fan.append(self.custom_box)

        self.curve_box = _box(Gtk.Orientation.VERTICAL, 8)
        head = _box(Gtk.Orientation.HORIZONTAL, 8)
        hint = _lbl("Arraste os pontos para definir a velocidade em cada temperatura. Com uma curva "
                    "só, as duas ventoinhas seguem a temperatura mais alta.", "ns-dim")
        hint.set_hexpand(True)
        hint.set_wrap(True)
        head.append(hint)
        for key, text in (("quiet", "Silencioso"), ("balanced", "Equilibrado"),
                          ("performance", "Desempenho")):
            b = Gtk.Button(label=text)
            b.add_css_class("ns-seg")
            b.connect("clicked", self._curve_preset, key)
            head.append(b)
        self.curve_box.append(head)

        split = _box(Gtk.Orientation.HORIZONTAL, 10, "ns-row")
        txt = _box(Gtk.Orientation.VERTICAL, 2)
        txt.set_hexpand(True)
        txt.append(_lbl("Curvas separadas para cada ventoinha"))
        txt.append(_lbl("A ventoinha da CPU segue a temperatura da CPU e a da GPU segue a da GPU "
                        "(com a GPU suspensa, a da CPU). Em 88 °C na CPU ou 82 °C na GPU as duas "
                        "vão a 100%.", "ns-dim"))
        split.append(txt)
        self.curve_split = _switch()
        self.curve_split.connect("notify::active", self._switch_changed, self._curve_split_toggled)
        split.append(self.curve_split)
        self.curve_box.append(split)

        self.curve_pick = _box(Gtk.Orientation.HORIZONTAL, 6)
        self.curve_target = "cpu"
        self.curve_pick_buttons = {}
        first = None
        for key, text in (("cpu", "Ventoinha da CPU"), ("gpu", "Ventoinha da GPU")):
            b = Gtk.ToggleButton(label=text)
            b.add_css_class("ns-seg")
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.connect("toggled", self._curve_target_toggled, key)
            self.curve_pick.append(b)
            self.curve_pick_buttons[key] = b
        first.set_active(True)
        self.curve_pick.set_visible(False)
        self.curve_box.append(self.curve_pick)
        self._curves = {"cpu": [list(p) for p in fancurve.DEFAULT_POINTS],
                        "gpu": [list(p) for p in fancurve.DEFAULT_POINTS]}
        self._curve_split = False
        self.curve_editor = FanCurveEditor(
            215, fancurve.MIN_PERCENT, fancurve.SAFETY_CPU,
            lambda v: _conv(v, self.prefs.get("unit", "C")), self._curve_changed)
        self.curve_box.append(self.curve_editor)
        self.curve_status = _lbl("", xalign=0.0)
        self.curve_box.append(self.curve_status)
        self.curve_box.set_visible(False)
        fan.append(self.curve_box)
        page.append(fan)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(page)
        return scroller

    # ================================================================ disks
    def _build_disks(self) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page = _box(Gtk.Orientation.VERTICAL, 14)
        scroller.set_child(page)
        self._disk_basic = disks.basic()
        if not self._disk_basic:
            card = _card()
            card.append(_lbl("Nenhum disco NVMe encontrado.", "ns-h"))
            page.append(card)
        for d in self._disk_basic:
            page.append(self._build_disk_card(d))
        return scroller

    def _build_disk_card(self, d: dict) -> Gtk.Widget:
        ui: dict = {}
        self.disk_ui[d["name"]] = ui
        card = _card(12)
        head = _box(Gtk.Orientation.HORIZONTAL, 10)
        titles = _box(Gtk.Orientation.VERTICAL, 2)
        titles.set_hexpand(True)
        titles.append(_lbl(d["model"], "ns-mid"))
        size = disks.human_bytes(d["size"]) if d["size"] else "?"
        titles.append(_lbl(f"{d['name']} · {size} · firmware {d['firmware']}", "ns-dim"))
        head.append(titles)
        ui["chip"] = _lbl("--", "ns-chip")
        ui["chip"].set_valign(Gtk.Align.CENTER)
        head.append(ui["chip"])
        card.append(head)

        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        grid.set_column_homogeneous(True)
        ui["tiles"] = {}
        for i, (key, title) in enumerate((
                ("temp", "Temperatura"), ("used", "Desgaste"), ("spare", "Reserva de células"),
                ("hours", "Tempo ligado"), ("written", "Dados gravados"), ("read", "Dados lidos"),
                ("cycles", "Ciclos de energia"), ("unsafe", "Desligamentos inesperados"),
                ("errors", "Erros de integridade"))):
            tile = _box(Gtk.Orientation.VERTICAL, 2, "ns-tile")
            tile.append(_lbl(title, "ns-dim"))
            val = _lbl("--", "ns-mid")
            ui["tiles"][key] = val
            tile.append(val)
            grid.attach(tile, i % 3, i // 3, 1, 1)
        card.append(grid)

        card.append(_lbl("Temperatura do disco, últimos 12 minutos", "ns-dim"))
        ui["hist"] = History(90)
        card.append(ui["hist"])

        ui["mounts"] = {}
        if d["mounts"]:
            card.append(_lbl("Espaço em uso", "ns-dim"))
        for m in d["mounts"]:
            row = _box(Gtk.Orientation.HORIZONTAL, 12)
            name = _lbl(m["mount"])
            name.set_size_request(130, -1)
            row.append(name)
            bar = Gtk.ProgressBar()
            bar.set_hexpand(True)
            bar.set_valign(Gtk.Align.CENTER)
            row.append(bar)
            txt = _lbl("--", "ns-dim", xalign=1.0)
            txt.set_size_request(190, -1)
            row.append(txt)
            card.append(row)
            ui["mounts"][m["mount"]] = (bar, txt)

        ui["advice"] = _lbl("", xalign=0.0)
        ui["advice"].set_wrap(True)
        card.append(ui["advice"])
        return card

    def _set_chip(self, chip: Gtk.Label, level: int, text: str) -> None:
        for c in ("ns-chip-ok", "ns-chip-warn", "ns-chip-crit"):
            chip.remove_css_class(c)
        chip.add_css_class(("ns-chip-ok", "ns-chip-warn", "ns-chip-crit")[level])
        chip.set_label(text)

    def _update_disks(self) -> None:
        unit = self.prefs.get("unit", "C")
        self._disk_assess = []
        for d in self._disk_basic:
            raw = self.smart.get(d["name"])
            smart = raw if raw and "error" not in raw else None
            a = disks.assess(d, smart)
            self._disk_assess.append((d, a))
            ui = self.disk_ui.get(d["name"])
            if not ui:
                continue
            ui["hist"].push(d["temp"], None)
            self._set_chip(ui["chip"], a["level"], a["label"])
            t = ui["tiles"]
            t["temp"].set_label(f"{_conv(d['temp'], unit)}°{unit}")
            if smart:
                t["used"].set_label(f"{smart['percentage_used']}%")
                t["spare"].set_label(f"{smart['available_spare']}%")
                t["hours"].set_label(f"{smart['power_on_hours']:,} h".replace(",", "."))
                t["written"].set_label(disks.human_bytes(smart["bytes_written"]))
                t["read"].set_label(disks.human_bytes(smart["bytes_read"]))
                t["cycles"].set_label(f"{smart['power_cycles']:,}".replace(",", "."))
                t["unsafe"].set_label(f"{smart['unsafe_shutdowns']:,}".replace(",", "."))
                t["errors"].set_label(str(smart["media_errors"]))
            for m in d["mounts"]:
                bar, txt = ui["mounts"].get(m["mount"], (None, None))
                if bar is None:
                    continue
                pct = m["used"] / m["total"]
                bar.set_fraction(pct)
                bar.remove_css_class("ns-bar-warn")
                bar.remove_css_class("ns-bar-crit")
                if pct >= 0.95:
                    bar.add_css_class("ns-bar-crit")
                elif pct >= 0.90:
                    bar.add_css_class("ns-bar-warn")
                txt.set_label(f"{disks.human_bytes(m['used'])} de {disks.human_bytes(m['total'])}"
                              f" ({pct * 100:.0f}%)")
            lines = [f"• {text}" for _lv, text in a["reasons"]]
            lines.append(a["advice"])
            if a["life"]:
                lines.append(a["life"])
            if not smart:
                lines.append("Dados SMART indisponíveis: o serviço do NitroSense não respondeu "
                             "ao pedido de discos (ele precisa estar atualizado e rodando).")
            ui["advice"].set_label("\n".join(lines))

    def _update_alerts(self, cpu_temp, gpu_temp) -> None:
        found = alerts.evaluate(cpu_temp, gpu_temp, self.rpm.get("cpu"), self.rpm.get("gpu"),
                                self._disk_assess, self._bat_assess, self._throttle,
                                bool(self._gpu_perf.get("thermal"))
                                or self._gpu_slow.get("thermal_for_s", 0) >= alerts.THERMAL_ALERT_S)
        keys = {a[1] for a in found}
        for key in [k for k in self._notified if k not in keys]:
            del self._notified[key]
        for level, key, text in found:
            if self._notified.get(key, -1) < level:
                self._notified[key] = level
                self._notify(level, key, text)
        bar = self.alert_bar
        bar.remove_css_class("ns-alert-warn")
        bar.remove_css_class("ns-alert-crit")
        if not found:
            bar.set_visible(False)
            return
        top = found[0]
        extra = f"  (+{len(found) - 1} alerta(s))" if len(found) > 1 else ""
        bar.set_label(("Atenção: " if top[0] == disks.WARN else "Crítico: ") + top[2] + extra)
        bar.add_css_class("ns-alert-crit" if top[0] == disks.CRIT else "ns-alert-warn")
        bar.set_visible(True)

    def _notify(self, level: int, key: str, text: str) -> None:
        app = self.get_application()
        if app is None or watcher.running():  # the background watcher already notifies
            return
        n = Gio.Notification.new("NitroSense: " + ("alerta crítico" if level == disks.CRIT
                                                    else "atenção"))
        n.set_body(text)
        n.set_priority(Gio.NotificationPriority.URGENT if level == disks.CRIT
                       else Gio.NotificationPriority.NORMAL)
        app.send_notification("alert-" + key, n)

    # ============================================================== monitor
    def _build_monitor(self) -> Gtk.Widget:
        page = _box(Gtk.Orientation.VERTICAL, 14)
        self.hist = {}
        self.hist_range = {}
        self.hist_now = {}
        for name, title in (("cpu", "CPU"), ("gpu", "GPU")):
            card = _card(10)
            head = _box(Gtk.Orientation.HORIZONTAL, 14)
            t = _lbl(title, "ns-mid")
            head.append(t)
            rng = _lbl("Mín -- · Máx --", "ns-dim")
            rng.set_valign(Gtk.Align.END)
            rng.set_hexpand(True)
            self.hist_range[name] = rng
            head.append(rng)
            now = _lbl("--°  --%", "ns-mid")
            self.hist_now[name] = now
            head.append(now)
            card.append(head)
            h = History(150)
            h.set_vexpand(True)
            self.hist[name] = h
            card.append(h)
            card.append(_lbl("Temperatura (linha roxa) e carga (área lilás), últimos 12 minutos",
                             "ns-dim"))
            page.append(card)
        return page

    # =============================================================== processes
    PROC_ROWS = 10

    def _build_procs(self) -> Gtk.Widget:
        page = _box(Gtk.Orientation.VERTICAL, 14)
        cols = _box(Gtk.Orientation.HORIZONTAL, 14)
        cols.set_homogeneous(True)
        self.proc_ui = {}
        for key, title in (("cpu", "CPU"), ("mem", "Memória"), ("gpu", "GPU")):
            card = _card(8)
            head = _box(Gtk.Orientation.HORIZONTAL, 8)
            head.append(_lbl(title, "ns-mid"))
            total = _lbl("--", "ns-dim")
            total.set_hexpand(True)
            total.set_xalign(1.0)
            total.set_valign(Gtk.Align.END)
            head.append(total)
            card.append(head)
            rows = []
            for _ in range(self.PROC_ROWS):
                row = _box(Gtk.Orientation.VERTICAL, 3)
                top = _box(Gtk.Orientation.HORIZONTAL, 8)
                name = _lbl("")
                name.set_hexpand(True)
                name.set_ellipsize(3)  # end
                name.set_max_width_chars(20)
                top.append(name)
                val = _lbl("", "ns-dim", xalign=1.0)
                top.append(val)
                row.append(top)
                bar = Gtk.ProgressBar()
                row.append(bar)
                row.set_visible(False)
                card.append(row)
                rows.append((row, name, bar, val))
            empty = _lbl("", "ns-dim")
            empty.set_wrap(True)
            card.append(empty)
            self.proc_ui[key] = {"total": total, "rows": rows, "empty": empty}
            cols.append(card)
        page.append(cols)
        holders = _card(6)
        holders.append(_lbl("O que mantém a GPU dedicada acordada", "ns-mid"))
        self.holders_label = _lbl("--", xalign=0.0)
        self.holders_label.set_wrap(True)
        holders.append(self.holders_label)
        page.append(holders)
        return page

    def _load_procs(self, force: bool = False) -> None:
        if self._procs_busy or (not force and time.monotonic() - self._procs_at < 1.8):
            return
        self._procs_busy = True
        self._procs_n += 1
        awake = self.gpu.awake()
        want_holders = awake and (force or self._procs_n % 3 == 0)

        def fetch():
            data = self.sampler.sample()
            gpu = procs.gpu_processes() if awake else []  # never run nvidia-smi on a sleeping GPU
            holders = None
            if want_holders:
                try:
                    holders = self.client.request("gpu_holders").get("holders")
                except DaemonError:  # an older service: fall back to our own programs only
                    holders = [dict(h, own=True) for h in procs.nvidia_holders()]
            return data, awake, gpu, holders

        def done(res):
            self._procs_busy = False
            self._procs_at = time.monotonic()
            self._apply_procs(*res)

        def fail(_e):
            self._procs_busy = False

        self.worker.submit(fetch, done, fail)

    def _apply_procs(self, data: dict, awake: bool, gpu: list, holders) -> None:
        ui = self.proc_ui

        def fill(key, items, empty_text):
            rows = ui[key]["rows"]
            for i, (row, name, bar, val) in enumerate(rows):
                row.set_visible(i < len(items))
                if i < len(items):
                    label, text, frac, tip = items[i]
                    name.set_label(label)
                    name.set_tooltip_text(tip)
                    val.set_label(text)
                    bar.set_fraction(max(0.0, min(1.0, frac)))
            ui[key]["empty"].set_label("" if items else empty_text)

        cpu = data["cpu"]
        top = max([v for _n, v, _c in cpu] + [10.0])
        fill("cpu", [(n, f"{v:.1f}%".replace(".", ","), v / top, f"{c} processo(s)")
                     for n, v, c in cpu],
             "Medindo..." if not data["ready"] else "Nada pesando agora.")
        ui["cpu"]["total"].set_label("% do processador inteiro")
        total_kb = used_kb = None
        try:
            info = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, _, v = line.partition(":")
                    info[k] = int(v.split()[0])
            total_kb, used_kb = info["MemTotal"], info["MemTotal"] - info["MemAvailable"]
        except (OSError, KeyError, ValueError):
            pass
        total = (total_kb or 0) * 1024
        fill("mem", [(n, disks.human_bytes(v), v / total if total else 0, f"{c} processo(s)")
                     for n, v, c in data["mem"]], "Sem dados.")
        ui["mem"]["total"].set_label("--" if not total else
                                     f"{disks.human_bytes(used_kb * 1024)} de {disks.human_bytes(total)} em uso")
        if awake:
            ui["gpu"]["total"].set_label("acordada")
            fill("gpu", [(g["name"], f"{g['mem_mb']} MB · {g['sm']}%", g["sm"] / 100,
                          "gráfico" if g["type"] == "G" else "computação") for g in gpu],
                 "Nenhum programa usando a GPU agora.")
        else:
            ui["gpu"]["total"].set_label("suspensa")
            fill("gpu", [], "A GPU dedicada está suspensa (economizando energia): ninguém a está usando.")
        if not awake:
            self.holders_label.set_label("Nada: a GPU dedicada está suspensa.")
        elif holders is not None:
            self._holders = holders
        if awake and self._holders is not None:
            lines = []
            for h in self._holders:
                devs = ", ".join(d.replace("/dev/", "") for d in h["devices"])
                lines.append(f"• {h['name']} (pid {h['pid']}): {devs}")
            text = "\n".join(lines) or ("Nenhum programa visível a segura agora (ela deve suspender "
                                        "em instantes).")
            if self._holders and all(h.get("own") for h in self._holders):
                text += "\n(Só seus programas aparecem: atualize o serviço para ver todos.)"
            self.holders_label.set_label(text)
        elif awake:
            self.holders_label.set_label("Consultando...")

    # ============================================================ performance
    def _update_perf(self) -> None:
        """Home: is the CPU or GPU being held back right now (heat / power) and at what clock."""
        th, gp = self._throttle, self._gpu_perf
        if not th and not gp:
            self._set_chip(self.perf_chip, 0, "Sem dados de desempenho")
            return
        problems = []
        if th.get("thermal"):
            problems.append("CPU limitada por calor")
        if gp.get("thermal"):
            problems.append("GPU limitada por calor")
        level = disks.WARN if problems else disks.OK
        if not problems and th.get("power_limited"):
            problems.append("CPU no limite de potência")
        if not problems and gp.get("power"):
            problems.append("GPU no limite de potência")
        self._set_chip(self.perf_chip, level, " · ".join(problems) or "Desempenho normal")
        parts = []
        if th.get("mhz"):
            parts.append(f"CPU {th['mhz'] / 1000:.1f} de {th['mhz_max'] / 1000:.1f} GHz".replace(".", ","))
        if gp.get("clock"):
            parts.append(f"GPU {gp['clock']} de {gp['clock_max']} MHz")
        if th.get("limit_c"):
            parts.append(f"proteção térmica da CPU a partir de ~{_conv(th['limit_c'], self.prefs.get('unit', 'C'))}°")
        self.perf_detail.set_label(" · ".join(parts))
        self.perf_chip.set_tooltip_text("\n".join(th.get("reasons", [])) or None)

    # ============================================================== battery
    RANGE_NAMES = {"1h": "última hora", "6h": "últimas 6 horas", "24h": "últimas 24 horas",
                   "7d": "últimos 7 dias", "30d": "últimos 30 dias"}

    def _build_battery(self) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page = _box(Gtk.Orientation.VERTICAL, 14)
        scroller.set_child(page)
        ui = self.bat_ui = {}

        card = _card(12)
        head = _box(Gtk.Orientation.HORIZONTAL, 10)
        titles = _box(Gtk.Orientation.VERTICAL, 2)
        titles.set_hexpand(True)
        ui["title"] = _lbl("Bateria", "ns-mid")
        titles.append(ui["title"])
        ui["subtitle"] = _lbl("", "ns-dim")
        titles.append(ui["subtitle"])
        head.append(titles)
        ui["chip"] = _lbl("--", "ns-chip")
        ui["chip"].set_valign(Gtk.Align.CENTER)
        head.append(ui["chip"])
        card.append(head)

        body = _box(Gtk.Orientation.HORIZONTAL, 18)
        ui["gauge"] = Gauge(170, ACCENT)
        ui["gauge"].set_valign(Gtk.Align.CENTER)
        body.append(ui["gauge"])
        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        grid.set_column_homogeneous(True)
        grid.set_hexpand(True)
        ui["tiles"], ui["tile_titles"] = {}, {}
        for i, (key, title) in enumerate((
                ("status", "Estado"), ("charge", "Carga atual"), ("capacity", "Capacidade atual"),
                ("cycles", "Ciclos de carga"), ("power", "Consumo"), ("eta", "Autonomia restante"),
                ("voltage", "Tensão"), ("temp", "Temperatura"), ("maker", "Fabricante"))):
            tile = _box(Gtk.Orientation.VERTICAL, 2, "ns-tile")
            ui["tile_titles"][key] = _lbl(title, "ns-dim")
            tile.append(ui["tile_titles"][key])
            val = _lbl("--", "ns-mid")
            ui["tiles"][key] = val
            tile.append(val)
            grid.attach(tile, i % 3, i // 3, 1, 1)
        body.append(grid)
        card.append(body)
        ui["advice"] = _lbl("", xalign=0.0)
        ui["advice"].set_wrap(True)
        card.append(ui["advice"])
        page.append(card)

        limit = _card(6)
        row = _box(Gtk.Orientation.HORIZONTAL, 12)
        txt = _box(Gtk.Orientation.VERTICAL, 3)
        txt.set_hexpand(True)
        txt.append(_lbl("Limitar a carga a 80%", "ns-mid"))
        desc = _lbl("Para de carregar em cerca de 80% quando o notebook fica na tomada, o que "
                    "reduz o desgaste da bateria. A carga completa volta ao desligar o limite.",
                    "ns-dim")
        desc.set_wrap(True)
        txt.append(desc)
        row.append(txt)
        self.battery_limit_toggle = _switch()
        self.battery_limit_toggle.connect("notify::active", self._switch_changed,
                                          self._battery_limit_toggled)
        row.append(self.battery_limit_toggle)
        limit.append(row)
        limit.set_visible(False)  # shown only when the firmware supports it
        ui["limit_card"] = limit
        page.append(limit)

        calib = _card(8)
        row = _box(Gtk.Orientation.HORIZONTAL, 12)
        txt = _box(Gtk.Orientation.VERTICAL, 3)
        txt.set_hexpand(True)
        txt.append(_lbl("Calibração da bateria", "ns-mid"))
        desc = _lbl("A bateria carrega até 100%, descarrega e recarrega uma vez para o notebook "
                    "reaprender a capacidade real. Pode levar várias horas. Útil quando a saúde "
                    "parece baixa demais para os ciclos ou a carga salta de repente.", "ns-dim")
        desc.set_wrap(True)
        txt.append(desc)
        row.append(txt)
        ui["cal_button"] = Gtk.Button(label="Iniciar calibração")
        ui["cal_button"].add_css_class("ns-seg")
        ui["cal_button"].set_valign(Gtk.Align.CENTER)
        ui["cal_button"].connect("clicked", self._calibration_clicked)
        row.append(ui["cal_button"])
        calib.append(row)
        ui["cal_status"] = _lbl("", xalign=0.0)
        ui["cal_status"].set_wrap(True)
        calib.append(ui["cal_status"])
        calib.set_visible(False)
        ui["cal_card"] = calib
        page.append(calib)
        self._cal: dict = {}

        self.bat_charts = {}
        for key, title, kw in (("bat", "Carga da bateria", {"suffix": "%", "mode": "percent"}),
                               ("pw", "Consumo da bateria (watts)", {"suffix": " W", "mode": "zero"})):
            c = _card(8)
            row = _box(Gtk.Orientation.HORIZONTAL, 12)
            row.append(_lbl(title, "ns-mid"))
            summ = _lbl("", "ns-dim")
            summ.set_hexpand(True)
            summ.set_xalign(1.0)
            summ.set_valign(Gtk.Align.END)
            row.append(summ)
            c.append(row)
            chart = TimeChart(120, lambda v: f"{v:.0f}", **kw)
            c.append(chart)
            self.bat_charts[key] = (chart, summ)
            page.append(c)
        ui["trend"] = _lbl("", "ns-dim")
        ui["trend"].set_wrap(True)
        page.append(ui["trend"])
        return scroller

    def _update_battery(self) -> None:
        self._bat_assess = [(b, battery.assess(b)) for b in self._bats]
        ui = self.bat_ui
        if not self._bats:
            ui["title"].set_label("Nenhuma bateria encontrada")
            return
        b, a = self._bats[0], self._bat_assess[0][1]
        unit = self.prefs.get("unit", "C")
        if b["status"] != self._pw_status:  # a new state (plugged in, unplugged): restart the average
            self._pw.clear()
            self._pw_status = b["status"]
        if b["power"] is not None and b["status"] in ("Discharging", "Charging"):
            self._pw.append(b["power"])
        avg = sum(self._pw) / len(self._pw) if self._pw else None
        discharging, charging = b["status"] == "Discharging", b["status"] == "Charging"
        ui["title"].set_label("Bateria " + (f"{b['manufacturer']} {b['model']}".strip() or b["name"]))
        ui["subtitle"].set_label(f"{b['technology'] or 'bateria'} · {b['name']}")
        self._set_chip(ui["chip"], a["level"], a["label"])
        h = b["health"]
        ui["gauge"].set_value(None if h is None else h / 100, "--" if h is None else f"{h:.0f}%",
                              "saúde")
        t, tt = ui["tiles"], ui["tile_titles"]
        t["status"].set_label(battery.STATUS_PT.get(b["status"], b["status"]))
        t["charge"].set_label("--" if b["capacity"] is None else f"{b['capacity']:.0f}%")
        t["capacity"].set_label("--" if b["energy_full"] is None else
                                f"{b['energy_full']:.1f} de {b['energy_design']:.1f} Wh".replace(".", ","))
        t["cycles"].set_label("--" if b["cycles"] is None else str(b["cycles"]))
        tt["power"].set_label("Carregando a" if charging else "Consumo")
        t["power"].set_label("--" if avg is None else f"{avg:.1f} W".replace(".", ","))
        tt["eta"].set_label("Tempo até carregar" if charging else "Autonomia restante")
        t["eta"].set_label(battery.human_duration(battery.time_left(b, avg))
                           if discharging or charging else "--")
        t["voltage"].set_label("--" if b["voltage"] is None else f"{b['voltage']:.1f} V".replace(".", ","))
        t["temp"].set_label("não informada" if b["temp"] is None else f"{_conv(b['temp'], unit)}°{unit}")
        t["maker"].set_label(b["manufacturer"] or "--")
        lines = [f"• {text}" for _lv, text in a["reasons"]]
        lines.append(a["advice"])
        if a["note"]:
            lines.append(a["note"])
        ui["advice"].set_label("\n".join(lines))

    def _apply_battery_history(self) -> None:
        data = self._hist_data
        if not data:
            return
        now = time.time()
        since = now - data["span"]
        name = self.RANGE_NAMES.get(data["range"], "")
        for key, (chart, summ) in self.bat_charts.items():
            chart.set_data(data["series"], key, since, now, data["step"])
            s = data["summary"].get(key)
            if not s:
                summ.set_label(name + (": sem uso da bateria no período" if key == "pw" else ""))
            elif key == "pw":
                summ.set_label(f"{name} · Média {s['avg']:.1f} W · Pico {s['max']:.0f} W".replace(".", ","))
            else:
                summ.set_label(f"{name} · Mín {s['min']:.0f}% · Máx {s['max']:.0f}%")
        lines = []
        for bname, tr in data.get("battery", {}).items():
            lines.append(f"{bname}: saúde {'+' if tr['health'] > 0 else ''}{tr['health']:.1f} ponto(s) "
                         f"percentuais e {tr['cycles']} ciclo(s) em {tr['days']:.1f} dia(s).")
        self.bat_ui["trend"].set_label("\n".join(lines) or "A tendência de saúde aparece depois "
                                       "de algumas horas (o serviço anota a saúde da bateria a cada 6 horas).")

    # ============================================================= history
    def _build_history(self) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page = _box(Gtk.Orientation.VERTICAL, 14)
        scroller.set_child(page)
        head = _box(Gtk.Orientation.HORIZONTAL, 8)
        title = _lbl("Histórico", "ns-mid")
        title.set_hexpand(True)
        head.append(title)
        first = None
        self.hist_buttons = {}
        for key, text in (("1h", "1 hora"), ("6h", "6 horas"), ("24h", "24 horas"),
                          ("7d", "7 dias"), ("30d", "30 dias")):
            b = Gtk.ToggleButton(label=text)
            b.add_css_class("ns-seg")
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.set_active(key == self._hist_range)
            b.connect("toggled", self._hist_range_toggled, key)
            head.append(b)
            self.hist_buttons[key] = b
        page.append(head)
        self.hist_note = _lbl("", "ns-dim")
        self.hist_note.set_wrap(True)
        page.append(self.hist_note)

        self.hchart = {}
        self.hsummary = {}
        for key, name, load in (("cpu", "CPU", True), ("gpu", "GPU", False),
                                ("ssd", "SSD", False)):
            card = _card(8)
            row = _box(Gtk.Orientation.HORIZONTAL, 12)
            t = _lbl(name, "ns-mid")
            row.append(t)
            summ = _lbl("--", "ns-dim")
            summ.set_hexpand(True)
            summ.set_xalign(1.0)
            summ.set_valign(Gtk.Align.END)
            row.append(summ)
            card.append(row)
            chart = TimeChart(130, lambda v: _conv(v, self.prefs.get("unit", "C")))
            card.append(chart)
            self.hchart[key], self.hsummary[key] = (chart, load), summ
            page.append(card)
        self.pchart = {}
        for key, name in (("cpw", "Consumo da CPU"), ("gpw", "Consumo da GPU")):
            card = _card(8)
            row = _box(Gtk.Orientation.HORIZONTAL, 12)
            row.append(_lbl(name, "ns-mid"))
            summ = _lbl("--", "ns-dim")
            summ.set_hexpand(True)
            summ.set_xalign(1.0)
            summ.set_valign(Gtk.Align.END)
            row.append(summ)
            card.append(row)
            chart = TimeChart(110, lambda v: f"{v:.0f}", suffix=" W", mode="zero")
            card.append(chart)
            self.pchart[key] = (chart, summ)
            page.append(card)
        card = _card(8)
        row = _box(Gtk.Orientation.HORIZONTAL, 12)
        row.append(_lbl("Frequência da CPU e limitações", "ns-mid"))
        self.fq_summary = _lbl("--", "ns-dim")
        self.fq_summary.set_hexpand(True)
        self.fq_summary.set_xalign(1.0)
        self.fq_summary.set_valign(Gtk.Align.END)
        row.append(self.fq_summary)
        card.append(row)
        self.fq_chart = TimeChart(110, lambda v: f"{v:g}", suffix=" GHz", mode="nice0")
        card.append(self.fq_chart)
        card.append(_lbl("As faixas vermelhas marcam quando a CPU reduziu o desempenho por calor "
                         "(quanto mais forte, maior a parte do intervalo).", "ns-dim"))
        page.append(card)
        legend = _lbl("Linha roxa: média; linha fina clara: pico em cada intervalo; "
                      "área lilás (CPU): carga de processamento. O consumo da CPU é o do "
                      "processador inteiro (pacote); o da GPU só é medido enquanto ela está acordada.",
                      "ns-dim")
        legend.set_wrap(True)
        page.append(legend)

        ssd = _card(6)
        ssd.append(_lbl("Desgaste do SSD no período", "ns-mid"))
        self.hssd = _lbl("--", xalign=0.0)
        self.hssd.set_wrap(True)
        ssd.append(self.hssd)
        page.append(ssd)
        return scroller

    def _hist_range_toggled(self, button: Gtk.ToggleButton, key: str) -> None:
        if not button.get_active():
            return
        self._hist_range = key
        self.prefs["hist_range"] = key
        self._save_prefs()
        self._load_history(force=True)

    def _load_history(self, force: bool = False) -> None:
        if self._hist_busy or (not force and time.monotonic() - self._hist_loaded < 30):
            return
        self._hist_busy = True
        key = self._hist_range

        def fetch():
            return key, self.client.request("history", range=key).get("history")

        def done(res):
            self._hist_busy = False
            self._hist_loaded = time.monotonic()
            if res[0] == self._hist_range:
                self._apply_history(res[1])
            else:
                self._load_history(force=True)

        def fail(e):
            self._hist_busy = False
            self.hist_note.set_label("Histórico indisponível: " + str(e) + " (atualize o serviço "
                                     "com o install.sh ou reinicie o nitrosensed).")

        self.worker.submit(fetch, done, fail)

    def _apply_history(self, data) -> None:
        self._hist_data = data
        self._apply_battery_history()
        unit = self.prefs.get("unit", "C")
        if not data:
            self.hist_note.set_label("O serviço ainda não registrou dados.")
            return
        now = time.time()
        since = now - data["span"]
        cov = data["coverage_s"] / data["span"]
        self.hist_note.set_label(
            f"{data['samples']} amostras coletadas em segundo plano pelo serviço, mesmo com a "
            f"janela fechada ({cov * 100:.0f}% do período coberto"
            + ("; o histórico começa quando o serviço foi atualizado" if cov < 0.9 else "") + ").")
        for key, (chart, load) in self.hchart.items():
            chart.set_data(data["series"], key, since, now, data["step"], load)
            s = data["summary"].get(key)
            hot = data["hot_minutes"].get(key)
            if not s:
                self.hsummary[key].set_label("sem dados" + (" (GPU suspensa)" if key == "gpu" else ""))
                continue
            text = (f"Mín {_conv(s['min'], unit)}° · Média {_conv(s['avg'], unit)}° · "
                    f"Máx {_conv(s['max'], unit)}°")
            if hot:
                limit = history.HOT[key]
                text += f" · {self._minutes(hot)} acima de {_conv(limit, unit)}°"
            self.hsummary[key].set_label(text)
        for key, (chart, summ) in self.pchart.items():
            chart.set_data(data["series"], key, since, now, data["step"])
            s = data["summary"].get(key)
            if not s:
                summ.set_label("sem medição" + (" (GPU suspensa ou sem leitura)" if key == "gpw" else
                                                " (o serviço precisa estar atualizado e rodando como root)"))
                continue
            wh = s["avg"] * s["n"] * data["interval"] / 3600
            energy = f"{wh / 1000:.2f} kWh" if wh >= 1000 else f"{wh:.0f} Wh"
            summ.set_label(f"Média {s['avg']:.1f} W · Pico {s['max']:.0f} W · "
                           f"≈ {energy} no período".replace(".", ","))
        self._apply_frequency_history(data, since, now)
        lines = []
        for name, t in data.get("smart", {}).items():
            lines.append(f"{name}: {disks.human_bytes(t['written'])} gravados e "
                         f"{disks.human_bytes(t['read'])} lidos em {t['days']:.1f} dia(s); "
                         f"desgaste {'+' if t['wear'] > 0 else ''}{t['wear']} ponto(s) percentuais; "
                         f"desligamentos inesperados +{t['unsafe']}; erros de integridade "
                         f"+{t['media_errors']}.")
        self.hssd.set_label("\n".join(lines) or "Ainda sem registros suficientes (o serviço anota "
                            "os contadores do SSD a cada 6 horas; volte mais tarde).")

    def _apply_frequency_history(self, data, since: float, now: float) -> None:
        ghz = [dict(p, fq=p["fq"] / 1000) if "fq" in p else p for p in data["series"]]
        self.fq_chart.set_data(ghz, "fq", since, now, data["step"], flag="thr")
        s = data["summary"].get("fq")
        if not s:
            self.fq_summary.set_label("sem dados (o serviço precisa estar atualizado)")
            return

        def minutes(key: str) -> int:
            t = data["summary"].get(key)
            return round(t["avg"] * t["n"] * data["interval"] / 100 / 60) if t else 0
        heat, power = minutes("thr"), minutes("pl")
        text = f"Média {s['avg'] / 1000:.2f} GHz · " + (
            f"limitada por calor {self._minutes(heat)}" if heat else "sem limitação por calor")
        if power:
            text += f" · no limite de potência {self._minutes(power)}"
        self.fq_summary.set_label(text.replace(".", ","))

    @staticmethod
    def _minutes(m: int) -> str:
        return f"{m} min" if m < 120 else f"{m / 60:.1f} h".replace(".", ",")

    # ============================================================== settings
    def _build_settings(self) -> None:
        pop = Gtk.Popover()
        pop.set_has_arrow(False)
        box = _box(Gtk.Orientation.VERTICAL, 0)
        box.set_size_request(340, -1)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        pop.set_child(box)
        self.settings_rows: dict[str, Gtk.Widget] = {}

        def row(name: str, text: str, control: Gtk.Widget) -> None:
            r = _box(Gtk.Orientation.HORIZONTAL, 10, "ns-row")
            lab = _lbl(text)
            lab.set_hexpand(True)
            lab.set_wrap(True)
            r.append(lab)
            r.append(control)
            box.append(r)
            self.settings_rows[name] = r

        box.append(_lbl("Configurações", "ns-h"))
        self.sticky_toggle = _switch()
        self.sticky_toggle.connect("notify::active", self._switch_changed, self._sticky_toggled)
        row("sticky", "Teclas de aderência", self.sticky_toggle)
        self.winkey_toggle = _switch()
        self.winkey_toggle.connect("notify::active", self._switch_changed, self._winkey_toggled)
        row("winkey", "Bloquear tecla Windows e menu", self.winkey_toggle)

        units = _box(Gtk.Orientation.HORIZONTAL, 4)
        self.unit_c = Gtk.ToggleButton(label="°C")
        self.unit_f = Gtk.ToggleButton(label="°F")
        self.unit_f.set_group(self.unit_c)
        for b, u in ((self.unit_c, "C"), (self.unit_f, "F")):
            b.add_css_class("ns-seg")
            b.connect("toggled", self._unit_toggled, u)
            units.append(b)
        row("unit", "Unidade de temperatura", units)
        self.dgpu_toggle = _switch()
        self.dgpu_toggle.connect("notify::active", self._switch_changed, self._dgpu_toggled)
        row("dgpu", "Usar somente a GPU dedicada", self.dgpu_toggle)
        self.overdrive_toggle = _switch()
        self.overdrive_toggle.connect("notify::active", self._switch_changed,
                                      self._overdrive_toggled)
        row("overdrive", "Overdrive da tela (LCD)", self.overdrive_toggle)
        self.backlight_toggle = _switch()
        self.backlight_toggle.connect("notify::active", self._switch_changed,
                                      self._backlight_toggled)
        row("backlight", "Apagar luz do teclado após 30 s", self.backlight_toggle)

        src = Gio.SettingsSchemaSource.get_default()
        if src and src.lookup("org.gnome.desktop.a11y.keyboard", True):
            self.sticky_settings = Gio.Settings.new("org.gnome.desktop.a11y.keyboard")
            self._set_switch(self.sticky_toggle, self.sticky_settings.get_boolean("stickykeys-enable"))
            self.sticky_settings.connect(
                "changed::stickykeys-enable",
                lambda s, k: self._set_switch(self.sticky_toggle, s.get_boolean(k)))
        self._updating = True
        (self.unit_f if self.prefs.get("unit") == "F" else self.unit_c).set_active(True)
        self._updating = False
        self.settings_button.set_popover(pop)
        self._layout_settings()

    def _layout_settings(self) -> None:
        """Hide rows the hardware does not support."""
        m = self.model
        visible = {"dgpu": bool(self.hw.get("gpu_mode_supported")),
                   "sticky": self.sticky_settings is not None and "Sticky_Key" in m.keyboard,
                   "winkey": any(k.startswith("Windowskey") for k in m.keyboard),
                   "unit": "Temperature" in m.advanced,
                   "overdrive": "LCD" in m.advanced and bool(self.hw.get("lcd_overdrive_supported")),
                   "backlight": "Backlight" in m.keyboard
                   and bool(self.hw.get("backlight_timeout_supported"))}
        for name, r in self.settings_rows.items():
            r.set_visible(visible.get(name, True))

    def _layout_settings_if_changed(self) -> None:
        flags = tuple(bool(self.hw.get(k)) for k in ("gpu_mode_supported", "lcd_overdrive_supported",
                                                     "backlight_timeout_supported"))
        if flags != self._layout_flags:
            self._layout_flags = flags
            self._layout_settings()

    # ============================================================== helpers
    def _set_switch(self, sw: Gtk.Switch, value) -> None:
        self._updating = True
        try:
            sw.set_active(bool(value))
        finally:
            self._updating = False

    def _switch_changed(self, sw: Gtk.Switch, _pspec, callback) -> None:
        if not self._updating:
            callback(sw, sw.get_active())

    def _set_toggle(self, button: Gtk.ToggleButton, value: bool) -> None:
        self._updating = True
        try:
            button.set_active(value)
        finally:
            self._updating = False

    # ================================================================= fan
    def _fan_toggled(self, button: Gtk.ToggleButton, mode: str) -> None:
        if button.get_active() and not self._updating:
            self._fan_mode_clicked(mode)

    def _fan_mode_clicked(self, mode: str) -> None:
        if self.state["fan"]["mode"] == mode:
            return
        self.state["fan"]["mode"] = mode
        self._update_fan_ui()
        f = self.state["fan"]
        self._send("set_fan", mode=mode, cpu_auto=f["cpu_auto"], gpu_auto=f["gpu_auto"],
                   cpu_percent=f["cpu_percent"], gpu_percent=f["gpu_percent"])

    def _scale_changed(self, scale: Gtk.Scale, _scroll, value: float, fan: str) -> bool:
        step = max(0, min(10, round(value)))
        self.slider_vals[fan].set_label(f"{step * 10}%")
        if self._fan_timer[fan]:
            GLib.source_remove(self._fan_timer[fan])

        def send() -> bool:
            self._fan_timer[fan] = 0
            self._fan_speed(fan, step)
            return False

        self._fan_timer[fan] = GLib.timeout_add(300, send)
        return False

    def _fan_speed(self, fan: str, value: int) -> None:
        self.state["fan"][f"{fan}_percent"] = value * 10
        self._send("set_fan_speed", fan=fan, percent=value * 10)

    def _fan_auto(self, fan: str, on: bool) -> None:
        self.state["fan"][f"{fan}_auto"] = on
        self._update_fan_ui()
        f = self.state["fan"]
        self._send("set_fan", mode="custom", cpu_auto=f["cpu_auto"], gpu_auto=f["gpu_auto"],
                   cpu_percent=f["cpu_percent"], gpu_percent=f["gpu_percent"])

    def _send_curves(self) -> None:
        self.state["fan_curve"] = {"points": self._curves["cpu"], "gpu_points": self._curves["gpu"],
                                   "split": self._curve_split}
        self._send("set_fan_curve", points=self._curves["cpu"], gpu_points=self._curves["gpu"],
                   split=self._curve_split)

    def _curve_changed(self, points: list) -> None:
        self._curves[self.curve_target] = points
        self._send_curves()

    def _curve_preset(self, _button, key: str) -> None:
        points = [[t, p] for t, p in zip(fancurve.TEMPS, fancurve.PRESETS[key])]
        self.curve_editor.set_points(points)
        self._curve_changed(points)

    def _curve_split_toggled(self, _w, on: bool) -> None:
        self._curve_split = on
        if not on:
            self.curve_target = "cpu"
            self._set_toggle(self.curve_pick_buttons["cpu"], True)
        self.curve_pick.set_visible(on)
        self.curve_editor.set_points(self._curves[self.curve_target])
        self._send_curves()

    def _curve_target_toggled(self, button: Gtk.ToggleButton, which: str) -> None:
        if button.get_active() and not self._updating and hasattr(self, "curve_editor"):
            self.curve_target = which
            self.curve_editor.set_points(self._curves[which])

    def _sync_curves(self, cfg: dict) -> None:
        """Take the saved curves from the service (unless the user is dragging one)."""
        if self.curve_editor.dragging is not None:
            return
        self._curves = {"cpu": cfg["points"], "gpu": cfg.get("gpu_points") or cfg["points"]}
        self._curve_split = bool(cfg.get("split"))
        self._set_switch(self.curve_split, self._curve_split)
        self.curve_pick.set_visible(self._curve_split)
        if not self._curve_split and self.curve_target != "cpu":
            self.curve_target = "cpu"
            self._set_toggle(self.curve_pick_buttons["cpu"], True)
        self.curve_editor.set_points(self._curves[self.curve_target])

    def _update_curve_status(self, info: dict) -> None:
        unit = self.prefs.get("unit", "C")
        split = bool(info.get("split"))
        if split and self.curve_target == "gpu":
            self.curve_editor.set_live(info.get("gpu_temp"), info.get("gpu_percent"))
        else:
            self.curve_editor.set_live(info.get("temp"), info.get("percent"))
        if info.get("failsafe"):
            text = "Sem leitura de temperatura: as ventoinhas voltaram ao modo automático."
        elif info.get("safety"):
            text = (f"Proteção ativa: a temperatura está alta demais "
                    f"({_conv(info.get('temp'), unit)}°), as ventoinhas ficam em 100%.")
        elif info.get("temp") is None:
            text = "Aguardando a primeira leitura..."
        elif split:
            asleep = self._current.get("gpu_suspended") if self._current else False
            gpu_note = " (GPU suspensa: segue a CPU)" if asleep else ""
            text = (f"Agora: CPU {_conv(info['temp'], unit)}° → {info['percent']}% · "
                    f"GPU {_conv(info.get('gpu_temp'), unit)}°{gpu_note} → {info.get('gpu_percent')}%.")
        else:
            text = (f"Agora: {_conv(info['temp'], unit)}° → ventoinhas a {info['percent']}%.")
        self.curve_status.set_label(text)

    def _coolboost_toggled(self, _w, on: bool) -> None:
        self.state["coolboost"] = on
        self._send("set_coolboost", on=on)

    def _update_fan_ui(self) -> None:
        f = self.state["fan"]
        for mode, b in self.fan_buttons.items():
            self._set_toggle(b, mode == f["mode"])
        custom = f["mode"] == "custom"
        self.custom_box.set_visible(custom)
        self.curve_box.set_visible(f["mode"] == "curve")
        for fan in ("cpu", "gpu"):
            self._set_switch(self.autos[fan], f[f"{fan}_auto"])
            self.sliders[fan].set_sensitive(not f[f"{fan}_auto"])
            if not self._fan_timer[fan]:
                self._updating = True
                self.sliders[fan].set_value(f[f"{fan}_percent"] // 10)
                self._updating = False
                self.slider_vals[fan].set_label(f"{f[f'{fan}_percent'] // 10 * 10}%")
        self.coolboost.set_sensitive(f["mode"] == "auto")

    # ------------------------------------------------------- power plan
    def _seg_toggled(self, button: Gtk.ToggleButton, source: str) -> None:
        if button.get_active() and not self._updating:
            self._show_plan_tab(source)

    def _show_plan_tab(self, source: str) -> None:
        self.plan_source = source
        self._set_toggle(self.seg_buttons[source], True)
        current = self.state["power"][source]
        for plan, b in self.plan_buttons.items():
            self._set_toggle(b, plan == current)

    def _plan_toggled(self, button: Gtk.ToggleButton, plan: str) -> None:
        if button.get_active() and not self._updating:
            self._plan_clicked(plan)

    def _plan_clicked(self, plan: str) -> None:
        self.state["power"][self.plan_source] = plan
        self._show_plan_tab(self.plan_source)
        self._send("set_power_plan", source=self.plan_source, plan=plan)

    # --------------------------------------------------------- settings
    def _sticky_toggled(self, _w, on: bool) -> None:
        if self.sticky_settings is not None:
            self.sticky_settings.set_boolean("stickykeys-enable", on)

    def _winkey_toggled(self, _w, on: bool) -> None:
        self.state["win_key"] = on
        self._send("set_win_key", on=on)

    def _overdrive_toggled(self, _w, on: bool) -> None:
        self.state["lcd_overdrive"] = on
        self._send("set_lcd_overdrive", on=on)
        if on and not self.prefs.get("overdrive_reminded"):
            self.prefs["overdrive_reminded"] = True
            self._save_prefs()
            self._show_status("Para o melhor desempenho do Overdrive, mantenha a taxa de "
                              "atualização máxima da tela.", error=False)

    def _battery_limit_toggled(self, _w, on: bool) -> None:
        self.state["battery_limit"] = on
        msg = ("Limite de carga ligado: a bateria vai parar em cerca de 80%." if on else
               "Limite de carga desligado: a bateria volta a carregar até 100%.")
        self._send("set_battery_limit", after=lambda _r: self._show_status(msg, error=False), on=on)

    def _calibration_clicked(self, _button) -> None:
        if self._cal.get("active") or self._cal.get("external"):
            self._send("stop_battery_calibration")
            return
        dialog = Gtk.AlertDialog(
            message="Iniciar a calibração da bateria?",
            detail=("A bateria vai carregar até 100%, descarregar quase por completo e recarregar. "
                    "Pode levar várias horas.\n\n"
                    "Mantenha o carregador ligado, não suspenda o notebook e evite tarefas pesadas. "
                    "O sistema pode mostrar avisos de bateria fraca durante a descarga. "
                    "O limite de 80% fica desligado e volta sozinho no fim. "
                    "Se o carregador sair da tomada, a calibração é interrompida."),
            buttons=["Iniciar", "Cancelar"], cancel_button=1, default_button=1)

        def done(dlg, res):
            try:
                choice = dlg.choose_finish(res)
            except GLib.Error:
                choice = 1
            if choice == 0:
                self._send("start_battery_calibration")

        dialog.choose(self, None, done)

    def _update_calibration(self) -> None:
        cal = self._cal
        ui = self.bat_ui
        ui["cal_card"].set_visible(bool(cal.get("supported")))
        if not cal.get("supported"):
            return
        active, external = bool(cal.get("active")), bool(cal.get("external"))
        button = ui["cal_button"]
        button.set_label("Cancelar calibração" if active or external else "Iniciar calibração")
        button.set_sensitive(active or external or self.ac_online)
        lines = []
        if active:
            minutes = int(cal.get("elapsed_s", 0) // 60)
            lines.append(f"Em andamento: {cal['text']} · há {minutes // 60} h {minutes % 60:02d} min. "
                         "Mantenha o carregador ligado.")
        elif external:
            lines.append("Há uma calibração em andamento, iniciada fora do NitroSense.")
        elif not self.ac_online:
            lines.append("Ligue o carregador para poder calibrar.")
        last = cal.get("last")
        if last:
            when = time.strftime("%d/%m %H:%M", time.localtime(last["finished"]))
            result = {"done": "concluída", "cancelled": "cancelada", "aborted": "interrompida",
                      "timeout": "encerrada por tempo esgotado"}.get(last["result"], last["result"])
            lines.append(f"Última calibração: {result} em {when}.")
        ui["cal_status"].set_label("\n".join(lines))
        # the firmware turns the charge limit off while calibrating
        self.battery_limit_toggle.set_sensitive(not active)

    def _backlight_toggled(self, _w, on: bool) -> None:
        self.state["backlight_timeout"] = on
        self._send("set_backlight_timeout", on=on)

    def _dgpu_toggled(self, w, on: bool) -> None:
        dialog = Gtk.AlertDialog(
            message="Usar somente a GPU dedicada",
            detail="A mudança vale depois de reiniciar.",
            buttons=["Reiniciar depois", "Reiniciar agora", "Cancelar"],
            cancel_button=2, default_button=1)

        def done(dlg, res):
            try:
                choice = dlg.choose_finish(res)
            except GLib.Error:
                choice = 2
            if choice == 2:
                self._set_switch(w, not on)
                return
            reboot = choice == 1

            def after(_r):
                if reboot:
                    Gio.Subprocess.new(["systemctl", "reboot"], Gio.SubprocessFlags.NONE)
            self._send("set_gpu_mode", after=after, discrete_only=on)

        dialog.choose(self, None, done)

    def _unit_toggled(self, button: Gtk.ToggleButton, unit: str) -> None:
        if button.get_active() and not self._updating:
            self.prefs["unit"] = unit
            self._save_prefs()
            self._render()
            if self.stack.get_visible_child_name() == "history":
                self._load_history(force=True)

    # ======================================================== daemon I/O
    def _send(self, cmd: str, after=None, **kw) -> None:
        def ok(resp):
            if self._status_is_error:
                self._show_status("")
            if after:
                after(resp)
            return False

        def fail(e):
            self._show_status(str(e))
            self._poll(force=True)
            return False

        self.worker.submit(lambda: self.client.request(cmd, **kw), ok, fail)

    def _poll(self, force: bool = False) -> bool:
        if self._poll_busy and not force:
            return True
        self._poll_busy = True

        def fetch():
            gpu_idle, gpu_load, gpu_temp = self.gpu.sample()
            cpu = self.cpu_load.sample()
            self._poll_n += 1
            disk_basic = disks.basic()
            bats = battery.read()
            smart = None
            try:
                status = self.client.request("status")
                err = None
            except DaemonError as e:
                status, err = None, str(e)
            if status is not None and self._poll_n % 10 == 1:
                try:  # an older service without the "disks" command just leaves SMART empty
                    smart = self.client.request("disks").get("smart")
                except DaemonError:
                    smart = None
            return status, err, cpu, gpu_idle, gpu_load, gpu_temp, disk_basic, smart, bats

        self.worker.submit(fetch, self._apply_status, lambda e: setattr(self, "_poll_busy", False))
        return True

    def _apply_status(self, res) -> bool:
        self._poll_busy = False
        status, err, cpu_load, gpu_idle, gpu_load, nv_temp, disk_basic, smart, bats = res
        self._bats = bats
        if disk_basic:
            self._disk_basic = disk_basic
        if smart is not None:
            self.smart = smart
        sensors = {}
        if status is None:
            self._show_status(err or "Serviço do NitroSense indisponível")
        else:
            first = not getattr(self, "_got_status", False)
            self._got_status = True
            self.state = status["state"]
            if "fan_curve" in self.state:
                self._sync_curves(self.state["fan_curve"])
            self._update_curve_status(status.get("fan_curve") or {})
            self.hw = status.get("hw", {})
            self.ac_online = status.get("ac", True)
            sensors = status.get("sensors", {})
            if not status.get("ready"):
                self._show_status("Interface de hardware indisponível: " + (status.get("error") or ""))
            elif self.status_label.get_label().startswith(("Serviço do NitroSense", "lost conn",
                                                           "Interface de hardware")):
                self._show_status("")
            self._layout_settings_if_changed()
            self._update_fan_ui()
            if first:
                self._show_plan_tab("ac" if self.ac_online else "battery")
            else:
                self._show_plan_tab(self.plan_source)
            hw_cb = self.hw.get("coolboost")
            self._set_switch(self.coolboost, self.state["coolboost"]
                             if self.state["coolboost"] is not None else bool(hw_cb))
            od = self.hw.get("lcd_overdrive")
            self._set_switch(self.overdrive_toggle,
                             od if od is not None else bool(self.state["lcd_overdrive"]))
            self._set_switch(self.winkey_toggle,
                             True if self.state["win_key"] is None else self.state["win_key"])
            bl = self.hw.get("backlight_timeout")
            self._set_switch(self.backlight_toggle,
                             bl if bl is not None else bool(self.state["backlight_timeout"]))
            self._set_switch(self.dgpu_toggle, self.hw.get("gpu_mode") == 1)
            self._cal = self.hw.get("battery_calibration") or {}
            self._update_calibration()
            limit_ok = bool(self.hw.get("battery_limit_supported"))
            self.bat_ui["limit_card"].set_visible(limit_ok)
            if limit_ok:
                self._set_switch(self.battery_limit_toggle, self.hw.get("battery_limit"))
            ready = bool(status.get("ready"))
            for sw in (self.overdrive_toggle, self.winkey_toggle, self.backlight_toggle):
                sw.set_sensitive(ready)

        self.rpm = {"cpu": sensors.get("cpu_fan"), "gpu": sensors.get("gpu_fan")}
        cpu_temp = sensors.get("cpu_temp")
        gpu_temp = sensors.get("gpu_temp") or nv_temp
        suspended = bool(gpu_idle and self.gpu.present)
        self._power = {"cpu": sensors.get("cpu_power"),
                       "gpu": None if suspended else self.gpu.power}
        self._throttle = (status or {}).get("throttle") or {}
        self._gpu_slow = (status or {}).get("gpu_throttle") or {}
        self._gpu_perf = {} if suspended else {
            "clock": self.gpu.clock, "clock_max": self.gpu.clock_max,
            **gpu_throttle(self.gpu.reasons)}
        if suspended:
            gpu_temp, gpu_load = None, None
        self.hist["gpu"].note = GPU_SUSPENDED if suspended else None
        self.hist["cpu"].push(cpu_temp, cpu_load)
        self.hist["gpu"].push(gpu_temp, gpu_load)
        self._current = {"cpu": (cpu_temp, cpu_load), "gpu": (gpu_temp, gpu_load),
                         "gpu_suspended": suspended}
        self._update_disks()
        self._update_battery()
        self._update_perf()
        self._update_alerts(cpu_temp, gpu_temp)
        if self.stack.get_visible_child_name() in ("history", "battery"):
            self._load_history()
        if self.stack.get_visible_child_name() == "procs":
            self._load_procs()
        self._render()
        return False

    def _render(self) -> None:
        unit = self.prefs.get("unit", "C")
        cur = self._current
        if not cur:
            return
        for name in ("cpu", "gpu"):
            temp, load = cur[name]
            frac = None if temp is None else (temp - 20) / 80
            sub = "suspensa" if name == "gpu" and cur.get("gpu_suspended") else f"°{unit}"
            self.g_temp[name].set_value(frac, "--" if temp is None else f"{_conv(temp, unit)}°", sub)
            rpm = getattr(self, "rpm", {}).get(name)
            self.rpm_labels[name].set_label("-- RPM" if rpm is None else f"{rpm} RPM")
            vals = self.hist[name].temps()
            lo = f"{_conv(min(vals), unit)}°" if vals else "--"
            hi = f"{_conv(max(vals), unit)}°" if vals else "--"
            self.hist_range[name].set_label(f"Mín {lo} · Máx {hi}")
            watts = getattr(self, "_power", {}).get(name)
            self.pw_labels[name].set_label("--" if watts is None else f"{watts:.0f} W")
            clock = (f"  {self._throttle['mhz'] / 1000:.1f} GHz".replace(".", ",")
                     if name == "cpu" and self._throttle.get("mhz") else
                     f"  {self._gpu_perf['clock']} MHz" if name == "gpu" and self._gpu_perf.get("clock") else "")
            self.hist_now[name].set_label(
                f"{_conv(temp, unit)}°  {'--' if load is None else round(load)}%"
                + ("" if watts is None else f"  {watts:.0f} W") + clock)
        gpu_load = cur["gpu"][1]
        cpu_temp, cpu_load = cur["cpu"]
        gpu_temp = cur["gpu"][0]
        self.g_gpu_load.set_value(None if gpu_load is None else gpu_load / 100,
                                  "--" if gpu_load is None else f"{round(gpu_load)}%",
                                  "suspensa" if cur.get("gpu_suspended") else "")
        self.home_gpu_load.set_label("--%" if gpu_load is None else f"{round(gpu_load)}%")
        self.home_cpu_load.set_label("--%" if cpu_load is None else f"{round(cpu_load)}%")
        self.tiles["cpu_temp"].set_label(f"{_conv(cpu_temp, unit)}°{unit}")
        self.tiles["gpu_temp"].set_label(f"{_conv(gpu_temp, unit)}°{unit}")
        self.tiles["cpu_load"].set_label("--" if cpu_load is None else f"{round(cpu_load)}%")
        ram = _ram_used_gb()
        self.tiles["ram"].set_label("--" if ram is None else f"{ram:.1f} GB".replace(".", ","))
        if self._disk_assess:
            d, a = self._disk_assess[0]
            self.tiles["disk_temp"].set_label(f"{_conv(d['temp'], unit)}°{unit}")
            self.tiles["disk_health"].set_label(a["label"])
        if self._bats:
            b = self._bats[0]
            self.tiles["battery"].set_label("--" if b["capacity"] is None else f"{b['capacity']:.0f}%")
            self.tiles["bat_health"].set_label(self._bat_assess[0][1]["label"] if b["health"] is not None else "--")
        plan = self.state["power"]["ac" if self.ac_online else "battery"]
        self.prof_vals["mode"].set_label(PLAN_NAMES.get(plan, "--"))
        self.prof_vals["fan"].set_label(FAN_NAMES.get(self.state["fan"]["mode"], "--"))
        cb = self.coolboost.get_active() and self.state["fan"]["mode"] == "auto"
        self.prof_vals["coolboost"].set_label("Ligado" if cb else "Desligado")

    def _show_status(self, text: str, error: bool = True) -> None:
        self._status_is_error = bool(text) and error
        self.status_label.set_label(text)
        if not error and text:
            GLib.timeout_add_seconds(8, lambda: (self.status_label.get_label() == text
                                                 and self.status_label.set_label(""), False)[1])

    # ============================================================ prefs
    def _load_prefs(self) -> dict:
        try:
            with open(PREFS) as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_prefs(self) -> None:
        os.makedirs(os.path.dirname(PREFS), exist_ok=True)
        tmp = PREFS + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.prefs, f)
        os.replace(tmp, PREFS)


class App(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self) -> None:
        win = self.get_active_window()
        if win is None:
            win = MainWindow(self)
        win.present()


def main() -> int:
    # Without these the desktop shows the window as "python3" with a generic icon: the
    # program name (WM_CLASS) would come from the interpreter.
    set_process_name("nitrosense")
    GLib.set_prgname("nitrosense")
    GLib.set_application_name("NitroSense")
    Gtk.Window.set_default_icon_name(APP_ID)
    return App().run(None)
