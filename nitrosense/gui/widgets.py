"""Purple dashboard widgets (ring gauge, history chart) and the application CSS.

Palette follows the Mint-Y-Dark-Purple accent (#8c5dd9) so the app matches the desktop.
"""

from __future__ import annotations

import math

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from .controls import draw_text  # noqa: E402
from .theme import rgba, rounded_rect  # noqa: E402

BG = "#1c1c21"
CARD = "#26262c"
INNER = "#202026"
BORDER = "#36363f"
TRACK = "#3a3a44"
TEXT = "#ece9f5"
DIM = "#a09db0"
ACCENT = "#8c5dd9"
ACCENT_LIGHT = "#b08cf0"
WARN = "#e8a23c"
HOT = "#e5677d"

CSS = f"""
window.nitrosense {{ background: {BG}; color: {TEXT}; }}
.ns-title {{ font-weight: 700; font-size: 15px; letter-spacing: 2px; }}
.ns-nav button {{ background: transparent; border: none; box-shadow: none; color: {DIM};
                 padding: 7px 18px; border-radius: 8px; font-size: 14px; }}
.ns-nav button:hover {{ background: #2c2c34; color: {TEXT}; }}
.ns-nav button:checked {{ background: {ACCENT}; color: #ffffff; }}
.ns-win button {{ background: transparent; border: none; box-shadow: none; color: {DIM};
                 padding: 6px; min-width: 0; min-height: 0; border-radius: 8px; }}
.ns-win button:hover {{ background: #2c2c34; color: #ffffff; }}
.ns-card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px; padding: 16px; }}
.ns-h {{ font-size: 13px; color: {DIM}; }}
.ns-big {{ font-size: 26px; font-weight: 700; color: #ffffff; }}
.ns-mid {{ font-size: 18px; font-weight: 700; color: #ffffff; }}
.ns-dim {{ color: {DIM}; font-size: 12px; }}
.ns-accent {{ color: {ACCENT_LIGHT}; }}
.ns-tile {{ background: {INNER}; border-radius: 10px; padding: 10px 12px; }}
.ns-row {{ padding: 9px 0; border-bottom: 1px solid {BORDER}; }}
.ns-row:last-child {{ border-bottom: none; }}
.ns-mode {{ background: {INNER}; border: 1px solid {BORDER}; border-radius: 12px;
           padding: 16px 18px; color: {DIM}; box-shadow: none; }}
.ns-mode:hover {{ border-color: {ACCENT}; color: {TEXT}; }}
.ns-mode:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: #ffffff; }}
.ns-seg {{ background: {INNER}; border: 1px solid {BORDER}; border-radius: 8px; padding: 5px 14px;
          color: {DIM}; box-shadow: none; font-size: 13px; }}
.ns-seg:hover {{ border-color: {ACCENT}; color: {TEXT}; }}
.ns-seg:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: #ffffff; }}
.ns-link {{ background: transparent; border: none; box-shadow: none; color: {ACCENT_LIGHT};
           padding: 4px 0; font-size: 13px; }}
.ns-link:hover {{ color: #ffffff; }}
.ns-status {{ color: #ff8fa3; font-size: 12px; }}
switch {{ background: {TRACK}; border: none; box-shadow: none; border-radius: 14px;
         min-width: 46px; min-height: 26px; }}
switch:checked {{ background: {ACCENT}; }}
switch slider {{ background: #ffffff; border: none; box-shadow: none; border-radius: 12px;
               min-width: 22px; min-height: 22px; margin: 2px; }}
.ns-mode:checked .ns-dim {{ color: #efe6ff; }}
.ns-mode:checked label {{ color: #ffffff; }}
scale trough {{ background: {TRACK}; min-height: 6px; border-radius: 3px; border: none; }}
scale trough highlight {{ background: {ACCENT}; border-radius: 3px; border: none; }}
scale trough slider {{ background: #ffffff; min-width: 18px; min-height: 18px; border-radius: 9px;
                     border: none; box-shadow: none; margin: -6px; }}
.ns-alert {{ border-radius: 10px; padding: 9px 16px; font-size: 13px; margin: 0 20px 10px 20px; }}
.ns-alert-warn {{ background: #4a3a16; color: #ffd98a; border: 1px solid #6b5420; }}
.ns-alert-crit {{ background: #4d1f2a; color: #ffb3c0; border: 1px solid #7a2d3d; }}
.ns-chip {{ border-radius: 12px; padding: 4px 14px; font-size: 12px; font-weight: 700; }}
.ns-chip-ok {{ background: #1f3d33; color: #8de0b5; }}
.ns-chip-warn {{ background: #4a3a16; color: #ffd98a; }}
.ns-chip-crit {{ background: #4d1f2a; color: #ffb3c0; }}
progressbar trough {{ background: {TRACK}; min-height: 8px; border-radius: 4px; border: none; }}
progressbar progress {{ background: {ACCENT}; min-height: 8px; border-radius: 4px; border: none; }}
progressbar.ns-bar-warn progress {{ background: {WARN}; }}
progressbar.ns-bar-crit progress {{ background: {HOT}; }}
popover > contents {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px;
                    color: {TEXT}; }}
"""


class Gauge(Gtk.DrawingArea):
    """270-degree ring: a value 0..1, a big centre text and a small caption under it."""

    def __init__(self, size: int = 150, color: str = ACCENT) -> None:
        super().__init__()
        self.size, self.color = size, color
        self.frac = 0.0
        self.text = "--"
        self.sub = ""
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_halign(Gtk.Align.CENTER)
        self.set_draw_func(lambda _a, cr, w, h: self._draw(cr, w, h))

    def set_value(self, frac: float | None, text: str, sub: str = "") -> None:
        self.frac = 0.0 if frac is None else max(0.0, min(1.0, frac))
        self.text, self.sub = text, sub
        self.queue_draw()

    def _draw(self, cr, w, h) -> None:
        cx, cy = w / 2, h / 2
        width = max(8.0, self.size * 0.075)
        r = min(w, h) / 2 - width
        start, sweep = 0.75 * math.pi, 1.5 * math.pi
        cr.set_line_width(width)
        cr.set_line_cap(1)  # round
        cr.set_source_rgba(*rgba(TRACK))
        cr.arc(cx, cy, r, start, start + sweep)
        cr.stroke()
        if self.frac > 0.005:
            color = HOT if self.frac > 0.9 else self.color
            cr.set_source_rgba(*rgba(color))
            cr.arc(cx, cy, r, start, start + sweep * self.frac)
            cr.stroke()
        draw_text(cr, self.text, cx, cy - self.size * 0.14, self.size * 0.2, "#ffffff",
                  bold=True, align="center")
        if self.sub:
            draw_text(cr, self.sub, cx, cy + self.size * 0.1, self.size * 0.085, DIM,
                      align="center")


class History(Gtk.DrawingArea):
    """Temperature (purple line) and load (lilac area) over the last 12 minutes (1 sample/s)."""

    SAMPLES = 720

    def __init__(self, height: int = 130) -> None:
        super().__init__()
        self.set_content_height(height)
        self.set_hexpand(True)
        self.temp: list[float | None] = [None] * self.SAMPLES
        self.load: list[float | None] = [None] * self.SAMPLES
        self.note: str | None = None
        self.set_draw_func(lambda _a, cr, w, h: self._draw(cr, w, h))

    def push(self, temp: float | None, load: float | None) -> None:
        self.temp = self.temp[1:] + [temp]
        self.load = self.load[1:] + [load]
        self.queue_draw()

    def temps(self) -> list[float]:
        return [v for v in self.temp if v is not None]

    def _series(self, cr, data, w, h, color, fill_alpha, line) -> None:
        step = w / (self.SAMPLES - 1)
        pts = [(i * step, h - 2 - max(0.0, min(100.0, v)) / 100 * (h - 4))
               for i, v in enumerate(data) if v is not None]
        if len(pts) < 2:
            return
        r, g, b, _ = rgba(color)
        if fill_alpha:
            cr.move_to(pts[0][0], h - 1)
            for x, y in pts:
                cr.line_to(x, y)
            cr.line_to(pts[-1][0], h - 1)
            cr.close_path()
            cr.set_source_rgba(r, g, b, fill_alpha)
            cr.fill()
        if line:
            cr.move_to(*pts[0])
            for x, y in pts[1:]:
                cr.line_to(x, y)
            cr.set_source_rgba(r, g, b, 1)
            cr.set_line_width(1.6)
            cr.stroke()

    def _draw(self, cr, w, h) -> None:
        rounded_rect(cr, 0.5, 0.5, w - 1, h - 1, 8)
        cr.set_source_rgba(*rgba(INNER))
        cr.fill_preserve()
        cr.set_source_rgba(*rgba(BORDER))
        cr.set_line_width(1)
        cr.stroke()
        cr.save()
        rounded_rect(cr, 0.5, 0.5, w - 1, h - 1, 8)
        cr.clip()
        cr.set_line_width(1)
        for frac in (0.25, 0.5, 0.75):
            y = round(h * frac) + 0.5
            cr.set_source_rgba(1, 1, 1, 0.06)
            cr.move_to(0, y)
            cr.line_to(w, y)
            cr.stroke()
        self._series(cr, self.load, w, h, ACCENT_LIGHT, 0.18, False)
        self._series(cr, self.temp, w, h, ACCENT, 0.0, True)
        cr.restore()
        if self.note:
            draw_text(cr, self.note, w / 2, h / 2 - 8, 13, DIM, align="center")


class TimeChart(Gtk.DrawingArea):
    """Long-range chart: average line, faint peak line, optional load area, time axis.

    Values are plain numbers; `fmt` turns an axis value into text (unit conversion).
    Gaps (suspend, service stopped) break the line instead of being interpolated.
    """

    LEFT, BOTTOM = 44, 18

    def __init__(self, height: int = 130, fmt=lambda v: f"{v:.0f}", suffix: str = "°",
                 mode: str = "temp") -> None:
        """mode: "temp" auto-scales, "zero" auto-scales from 0, "percent" is fixed 0-100."""
        super().__init__()
        self.suffix, self.mode = suffix, mode
        self.set_content_height(height)
        self.set_hexpand(True)
        self.fmt = fmt
        self.points: list[dict] = []
        self.key = ""
        self.since = self.until = 0.0
        self.step = 60.0
        self.load = False
        self.flag: str | None = None
        self.note: str | None = "Sem dados ainda"
        self.set_draw_func(lambda _a, cr, w, h: self._draw(cr, w, h))

    def set_data(self, points, key: str, since: float, until: float, step: float,
                 load: bool = False, flag: str | None = None) -> None:
        """flag: a series (0-100 %) whose non-zero buckets are shaded red, e.g. throttling."""
        self.points, self.key = points or [], key
        self.since, self.until, self.step, self.load, self.flag = since, until, step, load, flag
        self.note = None if any(key in p for p in self.points) else "Sem dados neste período"
        self.queue_draw()

    @staticmethod
    def _clock(t: float, span: float) -> str:
        import time
        return time.strftime("%H:%M" if span <= 86400 else "%d/%m %Hh", time.localtime(t))

    def _draw(self, cr, w, h) -> None:
        rounded_rect(cr, 0.5, 0.5, w - 1, h - 1, 8)
        cr.set_source_rgba(*rgba(INNER))
        cr.fill_preserve()
        cr.set_source_rgba(*rgba(BORDER))
        cr.set_line_width(1)
        cr.stroke()
        x0, x1, y0, y1 = self.LEFT, w - 10, 8, h - self.BOTTOM
        span = max(1.0, self.until - self.since)
        vals = [p[self.key] for p in self.points if self.key in p]
        vals += [p[self.key + "_max"] for p in self.points if self.key + "_max" in p]
        if not vals:
            if self.note:
                draw_text(cr, self.note, w / 2, h / 2 - 8, 13, DIM, align="center")
            return
        if self.mode == "percent":
            lo, hi, ticks = 0.0, 100.0, 5
        elif self.mode == "nice0":  # from 0, three even steps of 1 / 2 / 2.5 / 5 x 10^n
            lo, ticks = 0.0, 4
            top, unit = max(vals) * 1.05, 0.1
            while True:
                size = next((m * unit for m in (1, 2, 2.5, 5) if m * unit * 3 >= top), None)
                if size:
                    break
                unit *= 10
            hi = size * 3
        else:
            lo = 0.0 if self.mode == "zero" else max(0.0, math.floor((min(vals) - 5) / 10) * 10)
            hi = lo + max(1, math.ceil((max(vals) + 5 - lo) / 30)) * 30  # ticks on multiples of 10
            ticks = 4

        def px(t): return x0 + (t - self.since) / span * (x1 - x0)
        def py(v): return y1 - (v - lo) / (hi - lo) * (y1 - y0)

        cr.set_line_width(1)
        for i in range(ticks):
            v = lo + (hi - lo) * i / (ticks - 1)
            y = round(py(v)) + 0.5
            cr.set_source_rgba(1, 1, 1, 0.06)
            cr.move_to(x0, y)
            cr.line_to(x1, y)
            cr.stroke()
            draw_text(cr, self.fmt(v) + self.suffix, x0 - 6, y - 7, 10.5, DIM, align="right")
        for frac, align in ((0, "left"), (0.5, "center"), (1, "right")):
            draw_text(cr, self._clock(self.since + span * frac, span), x0 + (x1 - x0) * frac,
                      h - 15, 10.5, DIM, align=align)

        def runs(key):
            run, last = [], None
            for p in self.points:
                if key not in p:
                    continue
                if last is not None and p["t"] - last > self.step * 3:
                    yield run
                    run = []
                run.append((px(p["t"]), p[key]))
                last = p["t"]
            if run:
                yield run

        cr.save()
        cr.rectangle(x0, 0, x1 - x0, h)
        cr.clip()
        if self.flag:  # shade the buckets where the flag series is above zero
            r, g, b, _ = rgba(HOT)
            bar = max(2.0, self.step / span * (x1 - x0))
            for p in self.points:
                v = p.get(self.flag)
                if v:
                    cr.rectangle(px(p["t"]), y0, bar, y1 - y0)
                    cr.set_source_rgba(r, g, b, 0.18 + 0.30 * min(1.0, v / 100))
                    cr.fill()
        if self.load:  # CPU load 0-100 % as a lilac area behind the temperature
            r, g, b, _ = rgba(ACCENT_LIGHT)
            for run in runs("load"):
                cr.move_to(run[0][0], y1)
                for x, v in run:
                    cr.line_to(x, y1 - v / 100 * (y1 - y0))
                cr.line_to(run[-1][0], y1)
                cr.close_path()
                cr.set_source_rgba(r, g, b, 0.16)
                cr.fill()
        r, g, b, _ = rgba(ACCENT_LIGHT)
        for run in runs(self.key + "_max"):
            cr.move_to(run[0][0], py(run[0][1]))
            for x, v in run[1:]:
                cr.line_to(x, py(v))
            cr.set_source_rgba(r, g, b, 0.45)
            cr.set_line_width(1)
            cr.stroke()
        r, g, b, _ = rgba(ACCENT)
        for run in runs(self.key):
            if len(run) == 1:
                cr.arc(run[0][0], py(run[0][1]), 1.8, 0, 2 * math.pi)
                cr.set_source_rgba(r, g, b, 1)
                cr.fill()
                continue
            cr.move_to(run[0][0], py(run[0][1]))
            for x, v in run[1:]:
                cr.line_to(x, py(v))
            cr.set_source_rgba(r, g, b, 1)
            cr.set_line_width(1.8)
            cr.stroke()
        cr.restore()


class FanCurveEditor(Gtk.DrawingArea):
    """Fan speed (%) against temperature: drag the points up or down.

    The temperatures are fixed, only the speeds move; each point stays between its
    neighbours, never drops below `floor` and the last point is locked at 100 %.
    """

    LEFT, RIGHT, TOP, BOTTOM = 46, 16, 14, 24
    T_MIN, T_MAX = 30, 100
    SNAP = 5

    def __init__(self, height: int = 230, floor: int = 20, safety: int = 88,
                 fmt=lambda v: f"{v:.0f}", on_change=None) -> None:
        super().__init__()
        self.set_content_height(height)
        self.set_hexpand(True)
        self.floor, self.safety, self.fmt, self.on_change = floor, safety, fmt, on_change
        self.points: list[list[int]] = []
        self.live: tuple[float | None, int | None] = (None, None)
        self.dragging: int | None = None
        self._start_y = 0.0
        self.set_draw_func(lambda _a, cr, w, h: self._draw(cr, w, h))
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._begin)
        drag.connect("drag-update", self._update)
        drag.connect("drag-end", self._end)
        self.add_controller(drag)

    # ----------------------------------------------------------- data
    def set_points(self, points) -> None:
        if self.dragging is None:
            self.points = [list(p) for p in points]
            self.queue_draw()

    def set_live(self, temp, percent) -> None:
        self.live = (temp, percent)
        self.queue_draw()

    # -------------------------------------------------------- geometry
    def _box(self):
        w, h = self.get_width(), self.get_height()
        return self.LEFT, w - self.RIGHT, self.TOP, h - self.BOTTOM

    def _px(self, t: float) -> float:
        x0, x1, _y0, _y1 = self._box()
        return x0 + (t - self.T_MIN) / (self.T_MAX - self.T_MIN) * (x1 - x0)

    def _py(self, pct: float) -> float:
        _x0, _x1, y0, y1 = self._box()
        return y1 - pct / 100 * (y1 - y0)

    def _pct_at(self, y: float) -> float:
        _x0, _x1, y0, y1 = self._box()
        return (y1 - y) / (y1 - y0) * 100

    # ------------------------------------------------------ interaction
    def _begin(self, _g, x: float, y: float) -> None:
        best, best_d = None, 22.0
        for i, (t, p) in enumerate(self.points[:-1]):  # the last point is locked
            d = math.hypot(self._px(t) - x, self._py(p) - y)
            if d < best_d:
                best, best_d = i, d
        self.dragging = best
        self._start_y = y
        self._start_pct = self.points[best][1] if best is not None else 0

    def _update(self, _g, _dx: float, dy: float) -> None:
        i = self.dragging
        if i is None:
            return
        pct = self._start_pct - dy / (self._box()[3] - self._box()[2]) * 100
        lo = max(self.floor, self.points[i - 1][1] if i > 0 else self.floor)
        hi = self.points[i + 1][1]
        pct = round(pct / self.SNAP) * self.SNAP
        self.points[i][1] = int(max(lo, min(hi, pct)))
        self.queue_draw()

    def _end(self, _g, _dx: float, _dy: float) -> None:
        moved = self.dragging is not None
        self.dragging = None
        if moved and self.on_change:
            self.on_change([list(p) for p in self.points])
        self.queue_draw()

    # ---------------------------------------------------------- drawing
    def _draw(self, cr, w, h) -> None:
        rounded_rect(cr, 0.5, 0.5, w - 1, h - 1, 8)
        cr.set_source_rgba(*rgba(INNER))
        cr.fill_preserve()
        cr.set_source_rgba(*rgba(BORDER))
        cr.set_line_width(1)
        cr.stroke()
        x0, x1, y0, y1 = self._box()
        # danger zone: the service forces 100 % here whatever the curve says
        r, g, b, _ = rgba(HOT)
        cr.rectangle(self._px(self.safety), y0, x1 - self._px(self.safety), y1 - y0)
        cr.set_source_rgba(r, g, b, 0.13)
        cr.fill()
        draw_text(cr, "100% automático", x1 - 6, y1 - 17, 10.5, HOT, align="right")
        cr.set_line_width(1)
        for pct in (0, 25, 50, 75, 100):
            y = round(self._py(pct)) + 0.5
            cr.set_source_rgba(1, 1, 1, 0.06)
            cr.move_to(x0, y)
            cr.line_to(x1, y)
            cr.stroke()
            draw_text(cr, f"{pct}%", x0 - 6, y - 7, 10.5, DIM, align="right")
        for t in (40, 50, 60, 70, 80, 90, 100):
            draw_text(cr, self.fmt(t) + "°", self._px(t), h - 17, 10.5, DIM, align="center")
        if not self.points:
            return
        cr.save()
        cr.rectangle(x0, y0 - 4, x1 - x0, y1 - y0 + 8)
        cr.clip()
        cr.move_to(self._px(self.T_MIN), self._py(self.points[0][1]))
        for t, p in self.points:
            cr.line_to(self._px(t), self._py(p))
        cr.line_to(self._px(self.T_MAX), self._py(self.points[-1][1]))
        cr.set_source_rgba(*rgba(ACCENT))
        cr.set_line_width(2.2)
        cr.stroke()
        cr.restore()
        temp, pct = self.live
        if temp is not None and self.T_MIN <= temp <= self.T_MAX:
            x = self._px(temp)
            cr.set_source_rgba(*rgba(ACCENT_LIGHT))
            cr.set_line_width(1)
            cr.set_dash([4, 4])
            cr.move_to(x, y0)
            cr.line_to(x, y1)
            cr.stroke()
            cr.set_dash([])
            if pct is not None:
                cr.arc(x, self._py(pct), 4.5, 0, 2 * math.pi)
                cr.fill()
        for i, (t, p) in enumerate(self.points):
            cx, cy = self._px(t), self._py(p)
            locked = i == len(self.points) - 1
            cr.arc(cx, cy, 8 if self.dragging == i else 6, 0, 2 * math.pi)
            cr.set_source_rgba(*rgba(TRACK if locked else ACCENT))
            cr.fill_preserve()
            cr.set_source_rgba(1, 1, 1, 0.9)
            cr.set_line_width(1.5)
            cr.stroke()
            if self.dragging == i:
                draw_text(cr, f"{p}%", cx, cy - 26, 12, "#ffffff", bold=True, align="center")
