"""Custom-drawn controls reproducing the NitroSense WPF control templates."""

from __future__ import annotations

import math
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from . import theme  # noqa: E402
from .theme import Assets, rgba  # noqa: E402


def draw_text(cr, text: str, x: float, y: float, size: float, color: str,
              bold: bool = False, align: str = "left", width: float | None = None,
              valign_h: float | None = None, family: str = theme.FONT) -> tuple[int, int]:
    layout = PangoCairo.create_layout(cr)
    desc = Pango.FontDescription.from_string(f"{family} {'Bold ' if bold else ''}{size}px")
    desc.set_absolute_size(size * Pango.SCALE)
    layout.set_font_description(desc)
    layout.set_text(text, -1)
    if width is not None:
        layout.set_width(int(width * Pango.SCALE))
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        layout.set_alignment({"left": Pango.Alignment.LEFT, "center": Pango.Alignment.CENTER,
                              "right": Pango.Alignment.RIGHT}[align])
    tw, th = layout.get_pixel_size()
    if width is None:
        if align == "center":
            x -= tw / 2
        elif align == "right":
            x -= tw
    if valign_h is not None:
        y += (valign_h - th) / 2
    cr.set_source_rgba(*rgba(color))
    cr.move_to(x, y)
    PangoCairo.show_layout(cr, layout)
    return tw, th


def widget_pos(widget: Gtk.Widget, target: Gtk.Widget) -> tuple[float, float] | None:
    """Position of widget's origin in target coordinates (None if unrelated)."""
    res = widget.translate_coordinates(target, 0, 0)
    if res is None:
        return None
    if len(res) == 3:  # older PyGObject: (ok, x, y)
        ok, x, y = res
        return (x, y) if ok else None
    return res[0], res[1]


class Canvas(Gtk.DrawingArea):
    """Base class: fixed size, hover/press tracking, click callback."""

    def __init__(self, width: int, height: int, clickable: bool = True) -> None:
        super().__init__()
        self.set_size_request(width, height)
        self.set_content_width(width)
        self.set_content_height(height)
        self.w, self.h = width, height
        self.hover = False
        self.pressed = False
        self.enabled = True
        self.on_click = None
        self.set_draw_func(lambda _a, cr, w, h: self.draw(cr))
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", self._enter)
        motion.connect("leave", self._leave)
        self.add_controller(motion)
        if clickable:
            click = Gtk.GestureClick()
            click.connect("pressed", self._pressed)
            click.connect("released", self._released)
            self.add_controller(click)
            self.set_cursor(Gdk.Cursor.new_from_name("pointer"))

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.set_cursor(Gdk.Cursor.new_from_name("pointer" if enabled else "default"))
        self.queue_draw()

    def _enter(self, *_a) -> None:
        self.hover = True
        self.queue_draw()

    def _leave(self, *_a) -> None:
        self.hover = False
        self.pressed = False
        self.queue_draw()

    def _pressed(self, *_a) -> None:
        self.pressed = True
        self.queue_draw()

    def _released(self, gesture, _n, x, y) -> None:
        was = self.pressed
        self.pressed = False
        self.queue_draw()
        if was and self.enabled and 0 <= x <= self.w and 0 <= y <= self.h:
            self.activate_click(x, y)

    def activate_click(self, x: float, y: float) -> None:
        if self.on_click:
            self.on_click(self)

    def draw(self, cr) -> None:
        pass


class TitleButton(Canvas):
    """Close / minimise / settings / lighting buttons (#808080, hover #CCCCCC, pressed red)."""

    def __init__(self, assets: Assets, key: str, width: int, height: int,
                 offset: tuple[float, float] = (0, 0), tooltip: str = "") -> None:
        super().__init__(width, height)
        self.assets, self.key, self.offset = assets, key, offset
        if tooltip:
            self.set_tooltip_text(tooltip)

    def draw(self, cr) -> None:
        color = theme.RED if self.pressed else "#CCCCCC" if self.hover else theme.TITLE_ICON
        if not self.assets.draw(cr, self.key, self.offset[0], self.offset[1], color=color):
            theme.draw_fallback_icon(cr, self.key, self.w, self.h, color)


class ModeButton(Canvas):
    """Fan mode (Nitro_FanMode*Style) and power plan (PowerPlan_*_RadioButton_Style) buttons."""

    def __init__(self, assets: Assets, key: str, text: str, width: int = 220,
                 icon_x: float = 7, text_x: float = 54) -> None:
        super().__init__(width, 56)
        self.assets, self.key, self.text = assets, key, text
        self.icon_x, self.text_x = icon_x, text_x
        self.checked = False

    def set_checked(self, checked: bool) -> None:
        self.checked = checked
        self.queue_draw()

    def draw(self, cr) -> None:
        if self.checked:
            color = theme.RED
        elif self.hover and self.enabled:
            color = theme.ICON_HOVER
        else:
            color = theme.ICON_NORMAL if self.assets.available else theme.TEXT_INACTIVE
        alpha = 1.0 if self.enabled else 0.4
        paths = self.assets.paths(self.key)
        ih = float(paths[0].get("Height", 28)) if paths else 28
        if not self.assets.draw(cr, self.key, self.icon_x, (56 - ih) / 2, color=color,
                                alpha=alpha):
            # no artwork: a simple radio-style indicator instead of the original icon
            cx, cy = self.icon_x + 14, 28
            cr.set_source_rgba(*rgba(color, alpha))
            cr.set_line_width(1.5)
            cr.arc(cx, cy, 8, 0, 6.2832)
            cr.stroke()
            if self.checked:
                cr.arc(cx, cy, 4, 0, 6.2832)
                cr.fill()
        r, g, b, _a = rgba(color)
        cr.push_group()
        draw_text(cr, self.text, self.text_x, 0, 15, color, valign_h=56)
        cr.pop_group_to_source()
        cr.paint_with_alpha(alpha)


class HexToggle(Canvas):
    """SettingCheckBox_ControlTemplate: 52x20 hexagonal switch."""

    def __init__(self, assets: Assets, on_toggle=None) -> None:
        super().__init__(52, 20)
        self.assets = assets
        self.active = False
        self.on_toggle = on_toggle

    def set_active(self, active: bool) -> None:
        self.active = bool(active)
        self.queue_draw()

    def activate_click(self, x, y) -> None:
        self.active = not self.active
        self.queue_draw()
        if self.on_toggle:
            self.on_toggle(self, self.active)

    def draw(self, cr) -> None:
        alpha = 1.0 if self.enabled else 0.4
        if not self.assets.draw(cr, "SettingCheckBox_ControlTemplate", 0, 0,
                                indices=(0, 1) if self.active else (2, 3), alpha=alpha):
            # fallback when artwork is missing
            cr.set_source_rgba(*rgba(theme.DARK_RED if self.active else "#242424", alpha))
            cr.rectangle(0, 0, 52, 20)
            cr.fill()
            cr.set_source_rgba(*rgba(theme.RED if self.active else theme.ICON_NORMAL, alpha))
            cr.rectangle(23 if self.active else 3, 2, 26, 16)
            cr.fill()


class HexRadio(Canvas):
    """SettingRadioButton_Style / LightDynamicRadioButtionStyle: 28x20 hexagon radio."""

    def __init__(self, assets: Assets, group: list | None = None, on_select=None,
                 dark: bool = False) -> None:
        super().__init__(28, 20)
        self.assets = assets
        self.checked = False
        self.on_select = on_select
        self.group = group if group is not None else []
        self.group.append(self)
        self.dark = dark

    def set_checked(self, checked: bool) -> None:
        if checked:
            for other in self.group:
                if other is not self and other.checked:
                    other.checked = False
                    other.queue_draw()
        self.checked = checked
        self.queue_draw()

    def activate_click(self, x, y) -> None:
        if not self.checked:
            self.set_checked(True)
            if self.on_select:
                self.on_select(self)

    def draw(self, cr) -> None:
        key = "SettingRadioButton_Style"
        if self.checked:
            self.assets.draw(cr, key, 0, 0, indices=(4, 5))
        else:
            inner = "#5A5A5A" if self.hover else None
            self.assets.draw(cr, key, 0, 0, indices=(0,))
            self.assets.draw(cr, key, 0, 0, indices=(1,), color=inner)


class SpeedSlider(Canvas):
    """SpeedSliderStyle: 160x28, track #333333, value #6E0000, hexagon thumb #E60000."""

    def __init__(self, assets: Assets, minimum: int, maximum: int, width: int = 160,
                 on_change=None, on_release=None) -> None:
        super().__init__(width, 28, clickable=False)
        self.assets = assets
        self.minimum, self.maximum = minimum, maximum
        self.value = minimum
        self.on_change = on_change    # while dragging
        self.on_release = on_release  # when the user lets go (sends to hardware)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", self._drag_end)
        self.add_controller(drag)
        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._scroll)
        self.add_controller(scroll)
        self.set_cursor(Gdk.Cursor.new_from_name("pointer"))
        self._start_x = 0.0

    def set_value(self, value: int) -> None:
        self.value = max(self.minimum, min(self.maximum, int(value)))
        self.queue_draw()

    def _x_to_value(self, x: float) -> int:
        usable = self.w - 26
        frac = (x - 13) / usable if usable > 0 else 0
        frac = max(0.0, min(1.0, frac))
        return round(self.minimum + frac * (self.maximum - self.minimum))

    def _update(self, x: float) -> None:
        v = self._x_to_value(x)
        if v != self.value:
            self.value = v
            self.queue_draw()
            if self.on_change:
                self.on_change(self, v)

    def _drag_begin(self, _g, x, _y) -> None:
        if not self.enabled:
            return
        self._start_x = x
        self.pressed = True
        self._update(x)

    def _drag_update(self, _g, dx, _dy) -> None:
        if self.enabled and self.pressed:
            self._update(self._start_x + dx)

    def _drag_end(self, _g, dx, _dy) -> None:
        if self.enabled and self.pressed:
            self.pressed = False
            self._update(self._start_x + dx)
            if self.on_release:
                self.on_release(self, self.value)

    def _scroll(self, _c, _dx, dy) -> bool:
        if not self.enabled:
            return False
        v = self.value - (1 if dy > 0 else -1)
        if self.minimum <= v <= self.maximum:
            self.set_value(v)
            if self.on_release:
                self.on_release(self, self.value)
        return True

    def draw(self, cr) -> None:
        enabled = self.enabled
        track_y = 10
        frac = (self.value - self.minimum) / max(1, self.maximum - self.minimum)
        thumb_x = frac * (self.w - 26)
        cr.set_source_rgba(*rgba(theme.TRACK if enabled else "#242424"))
        cr.rectangle(0, track_y, self.w, 8)
        cr.fill()
        cr.set_source_rgba(*rgba(theme.DARK_RED if enabled else "#242424"))
        cr.rectangle(0, track_y, thumb_x + 13, 8)
        cr.fill()
        color = theme.RED if enabled else theme.TRACK
        if not self.assets.draw(cr, "SliderThumb", thumb_x, 6, color=color):
            cr.set_source_rgba(*rgba(color))
            cr.rectangle(thumb_x, 6, 26, 16)
            cr.fill()


class AutoButton(Canvas):
    """AutoCheckBoxStyle: 80x20 hexagon outline, red when checked."""

    def __init__(self, assets: Assets, text: str, on_toggle=None) -> None:
        super().__init__(80, 20)
        self.assets, self.text = assets, text
        self.active = False
        self.on_toggle = on_toggle

    def set_active(self, active: bool) -> None:
        self.active = bool(active)
        self.queue_draw()

    def activate_click(self, x, y) -> None:
        self.active = not self.active
        self.queue_draw()
        if self.on_toggle:
            self.on_toggle(self, self.active)

    def draw(self, cr) -> None:
        if self.active:
            stroke, fill, text = theme.RED, "#1AE60000", theme.RED
        elif self.hover:
            stroke, fill, text = "#666666", "#1A000000", "#666666"
        else:
            stroke, fill, text = theme.TRACK, None, theme.GRAY_LABEL
        if not self.assets.draw(cr, "AutoCheckBoxStyle", 0, 0, stroke=stroke, fill=fill):
            cr.set_source_rgba(*rgba(stroke))
            cr.rectangle(0.5, 0.5, 79, 19)
            cr.stroke()
        draw_text(cr, self.text, 40, 0, 12, text, align="center", valign_h=20)


class TabButton(Canvas):
    """PowerPlan_TabItem_ControlTemplate: 120x32 tab."""

    def __init__(self, assets: Assets, text: str, group: list) -> None:
        super().__init__(120, 32)
        self.assets, self.text = assets, text
        self.selected = False
        self.group = group
        group.append(self)
        self.on_select = None

    def set_selected(self, selected: bool) -> None:
        if selected:
            for t in self.group:
                if t is not self:
                    t.selected = False
                    t.queue_draw()
        self.selected = selected
        self.queue_draw()

    def activate_click(self, x, y) -> None:
        if not self.selected:
            self.set_selected(True)
            if self.on_select:
                self.on_select(self)

    def draw(self, cr) -> None:
        fill = "#FF333333" if self.selected else "#FF282828" if self.hover else "#FF1E1E1E"
        if not self.assets.draw(cr, "PowerPlan_TabItem_ControlTemplate", 0, 0, color=fill):
            cr.set_source_rgba(*rgba(fill))
            cr.rectangle(0, 0, 120, 32)
            cr.fill()
        draw_text(cr, self.text, 60, 0, 14, theme.WHITE if self.selected else "#999999",
                  align="center", valign_h=32)


class FanView(Gtk.DrawingArea):
    """Rotating fan image with RPM read-out (Nitro_FanControlPage.PushData_CPU)."""

    def __init__(self, image_path: str | None) -> None:
        super().__init__()
        self.set_size_request(216, 252)
        self.set_content_width(216)
        self.set_content_height(252)
        self.surface = None
        if image_path:
            try:
                import cairo
                self.surface = cairo.ImageSurface.create_from_png(image_path)
            except Exception:
                self.surface = None
        self.rpm: int | None = None
        self.angle = 0.0
        self.period = 0.0  # seconds per revolution, 0 = stopped
        self._last = time.monotonic()
        self.set_draw_func(lambda _a, cr, w, h: self.draw(cr))
        self.add_tick_callback(self._tick)

    def set_rpm(self, rpm: int | None) -> None:
        self.rpm = rpm
        if not rpm:
            self.period = 0.0
        else:
            duration = 11 - int(rpm / 450)
            if rpm > 4500:
                duration = 2
            self.period = float(max(1, duration))
        self.queue_draw()

    def _tick(self, _w, _clock) -> bool:
        now = time.monotonic()
        dt, self._last = now - self._last, now
        if self.period > 0:
            self.angle = (self.angle - 360.0 * dt / self.period) % 360.0
            self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def draw(self, cr) -> None:
        cx, top = 108, 0
        if self.surface is not None:
            cr.save()
            cr.translate(cx, top + 100)
            cr.rotate(math.radians(self.angle))
            cr.translate(-100, -100)
            cr.set_source_surface(self.surface, 0, 0)
            cr.paint()
            cr.restore()
        else:
            cr.set_source_rgba(*rgba("#202020"))
            cr.arc(cx, top + 100, 60, 0, 2 * math.pi)
            cr.fill()
        text = "--" if self.rpm is None else str(self.rpm)
        draw_text(cr, text, cx, top + 77, 28, theme.WHITE, bold=True, align="center")
        draw_text(cr, "RPM", cx, top + 121, 12, theme.GRAY_LABEL, align="center")


class LineChart(Gtk.DrawingArea):
    """720x100 history chart: temperature (red) and load (orange), 1 sample/s."""

    SAMPLES = 720

    def __init__(self, assets: Assets, title: str) -> None:
        super().__init__()
        self.set_size_request(720, 100)
        self.set_content_width(720)
        self.set_content_height(100)
        self.assets, self.title = assets, title
        self.temp: list[float | None] = [None] * self.SAMPLES
        self.load: list[float | None] = [None] * self.SAMPLES
        self.times: list[float | None] = [None] * self.SAMPLES
        self.idle_text: str | None = None
        self.unit = "C"
        self.mouse_x: float | None = None
        self._bg = self._chart = None
        try:
            import cairo
            for attr, name in (("_bg", "img_monitor_chartshadow.png"),
                               ("_chart", "img_monitor_chart.png")):
                p = assets.image(name)
                if p:
                    setattr(self, attr, cairo.ImageSurface.create_from_png(p))
        except Exception:
            pass
        self.set_draw_func(lambda _a, cr, w, h: self.draw(cr))
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda _c, x, y: self._hover(x))
        motion.connect("leave", lambda _c: self._hover(None))
        self.add_controller(motion)

    def _hover(self, x) -> None:
        self.mouse_x = x
        self.queue_draw()

    def push(self, temp: float | None, load: float | None) -> None:
        self.temp = self.temp[1:] + [temp]
        self.load = self.load[1:] + [load]
        self.times = self.times[1:] + [time.time()]
        self.queue_draw()

    def _series(self, cr, data, color) -> None:
        pts = [(i, 100 - max(0.0, min(100.0, v)) + 1) for i, v in enumerate(data) if v is not None]
        if len(pts) < 2:
            return
        r, g, b, _ = rgba(color)
        cr.move_to(pts[0][0], 99)
        for x, y in pts:
            cr.line_to(x, y)
        cr.line_to(pts[-1][0], 99)
        cr.close_path()
        cr.set_source_rgba(r, g, b, 0.15)
        cr.fill()
        cr.move_to(*pts[0])
        for x, y in pts[1:]:
            cr.line_to(x, y)
        cr.set_source_rgba(r, g, b, 1)
        cr.set_line_width(1)
        cr.stroke()

    def draw(self, cr) -> None:
        for surf in (self._bg, self._chart):
            if surf is not None:
                cr.set_source_surface(surf, 0, 0)
                cr.paint()
        if self._bg is None:
            cr.set_source_rgba(*rgba("#141414"))
            cr.paint()
            cr.set_line_width(1)
            for frac in (0.25, 0.5, 0.75):
                y = round(100 * frac) + 0.5
                cr.set_source_rgba(1, 1, 1, 0.07)
                cr.move_to(0, y)
                cr.line_to(720, y)
                cr.stroke()
            cr.set_source_rgba(*rgba(theme.CARD_BORDER))
            cr.rectangle(0.5, 0.5, 719, 99)
            cr.stroke()
        self._series(cr, self.load, theme.ORANGE)
        self._series(cr, self.temp, theme.RED)
        draw_text(cr, self.title, 10, 10, 16, theme.WHITE)
        if self.idle_text:
            cr.set_source_rgba(*rgba("#262626", 0.95))
            cr.rectangle(720 - 176, 100 - 52, 168, 48)
            cr.fill()
            draw_text(cr, self.idle_text, 720 - 170, 100 - 52, 12.5, theme.WHITE, width=156,
                      valign_h=48)
        if self.mouse_x is not None:
            i = int(max(0, min(self.SAMPLES - 1, self.mouse_x)))
            if self.times[i] is not None:
                self._popup(cr, i)

    def _popup(self, cr, i: int) -> None:
        t, l = self.temp[i], self.load[i]
        stamp = time.strftime("%H:%M:%S", time.localtime(self.times[i]))
        if t is not None and self.unit == "F":
            t = t * 9 / 5 + 32
        lines = [stamp, f"{'--' if t is None else round(t)}°", f"{'--' if l is None else round(l)}%"]
        x = min(i + 8, 720 - 90)
        cr.set_source_rgba(*rgba("#333333"))
        cr.rectangle(x, 18, 84, 64)
        cr.fill()
        cr.set_source_rgba(*rgba("#1E1E1E"))
        cr.rectangle(x, 50, 84, 32)
        cr.fill()
        draw_text(cr, lines[0], x + 10, 22, 12, theme.WHITE)
        draw_text(cr, lines[1], x + 10, 40, 12, theme.RED)
        draw_text(cr, lines[2], x + 46, 40, 12, theme.ORANGE)
        cr.set_source_rgba(1, 1, 1, 0.4)
        cr.move_to(i + 0.5, 0)
        cr.line_to(i + 0.5, 100)
        cr.set_line_width(1)
        cr.stroke()
