"""Colours, fonts, extracted NitroSense artwork and icon drawing."""

from __future__ import annotations

import json
import math
import os

import cairo

from ..geometry import build_cairo_path, parse_svg_path

ASSET_DIRS = [os.environ.get("NITROSENSE_ASSETS", ""), "/usr/share/nitrosense/assets",
              os.path.expanduser("~/.local/share/nitrosense/assets")]

FONT = "Segoe UI, Open Sans, Noto Sans, sans-serif"

# Colours taken from the NitroSense styles (PSStyle.xaml) / code
RED = "#E60000"
DARK_RED = "#6E0000"
ORANGE = "#FF7800"
WHITE = "#FFFFFF"
GRAY_TEXT = "#808080"
GRAY_LABEL = "#666666"
ICON_NORMAL = "#4C4C4C"
ICON_HOVER = "#B2B2B2"
TITLE_ICON = "#808080"
TITLE_ICON_HOVER = "#FFFFFF"
TRACK = "#333333"
POPUP_BG = "#DADADA"
POPUP_LINE = "#999999"
PANEL_BG = "#151515"
PANEL_FRAME = "#72706C"


def rgba(color: str, alpha: float | None = None) -> tuple[float, float, float, float]:
    c = color.lstrip("#")
    a = 1.0
    if len(c) == 8:
        a = int(c[:2], 16) / 255
        c = c[2:]
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return r, g, b, a if alpha is None else alpha


def find_assets() -> str | None:
    for d in ASSET_DIRS:
        if d and os.path.exists(os.path.join(d, "icons.json")):
            return d
    return None


class Assets:
    def __init__(self) -> None:
        self.dir = find_assets()
        self.icons: dict[str, list[dict]] = {}
        self.strings: dict[str, str] = {}
        if self.dir:
            with open(os.path.join(self.dir, "icons.json")) as f:
                self.icons = json.load(f)
            with open(os.path.join(self.dir, "strings_en.json")) as f:
                self.strings = json.load(f)
        self._prepared: dict[str, list[dict]] = {}

    @property
    def available(self) -> bool:
        return self.dir is not None

    def image(self, name: str) -> str | None:
        if not self.dir:
            return None
        path = os.path.join(self.dir, "images", "100", name)
        return path if os.path.exists(path) else None

    def text(self, key: str, default: str) -> str:
        return self.strings.get(key, default)

    def fonts_dir(self) -> str | None:
        if not self.dir:
            return None
        d = os.path.join(self.dir, "fonts")
        return d if os.path.isdir(d) else None

    # ------------------------------------------------------------ icons
    def paths(self, key: str) -> list[dict]:
        if key not in self._prepared:
            prepared = []
            for p in self.icons.get(key, []):
                cmds = parse_svg_path(p["d"])
                bounds = _extents(cmds)
                prepared.append({**p, "cmds": cmds, "bounds": bounds})
            self._prepared[key] = prepared
        return self._prepared[key]

    def draw(self, cr, key: str, x: float, y: float, color: str | None = None,
             names: tuple[str, ...] | None = None, indices: tuple[int, ...] | None = None,
             alpha: float = 1.0, scale: float = 1.0, stroke: str | None = None,
             fill: str | None = None) -> bool:
        """Draw the paths of a style at (x, y) honouring Width/Height/Left/Top (Stretch=Fill).

        color overrides the fill of filled paths, stroke overrides the outline
        of stroked paths and fill adds a fill to outline-only paths.
        """
        paths = self.paths(key)
        if not paths:
            return False
        for i, p in enumerate(paths):
            if indices is not None and i not in indices:
                continue
            if names is not None and p.get("Name") not in names:
                continue
            x1, y1, x2, y2 = p["bounds"]
            w = float(p.get("Width") or (x2 - x1))
            h = float(p.get("Height") or (y2 - y1))
            sx = w / (x2 - x1) if x2 > x1 else 1.0
            sy = h / (y2 - y1) if y2 > y1 else 1.0
            cmds = _transform(p["cmds"], sx, sy, x1, y1)
            cr.save()
            cr.translate(x + float(p.get("Left", 0)) * scale, y + float(p.get("Top", 0)) * scale)
            cr.scale(scale, scale)
            cr.new_path()
            build_cairo_path(cr, cmds)
            cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD if p.get("fill_rule") == "evenodd"
                             else cairo.FILL_RULE_WINDING)
            own_fill, own_stroke = p.get("Fill"), p.get("Stroke")
            fill_color = (color or own_fill) if own_fill else fill
            stroke_color = (stroke or own_stroke) if own_stroke else None
            if fill_color:
                cr.set_source_rgba(*_with_alpha(fill_color, alpha))
                cr.fill_preserve()
            if stroke_color:
                cr.set_source_rgba(*_with_alpha(stroke_color, alpha))
                cr.set_line_width(float(p.get("StrokeThickness", 1)))
                cr.stroke_preserve()
            cr.new_path()
            cr.restore()
        return True


def _with_alpha(color: str, alpha: float) -> tuple[float, float, float, float]:
    r, g, b, a = rgba(color)
    return r, g, b, a * alpha


def _extents(cmds) -> tuple[float, float, float, float]:
    surf = cairo.ImageSurface(cairo.FORMAT_A8, 1, 1)
    cr = cairo.Context(surf)
    build_cairo_path(cr, cmds)
    return cr.fill_extents()


def _transform(cmds, sx, sy, x1, y1):
    out = []
    for c in cmds:
        k = c[0]
        if k == "Z":
            out.append(c)
            continue
        if k == "A":
            out.append(("A", c[1] * sx, c[2] * sy, c[3], c[4], c[5],
                        (c[6] - x1) * sx, (c[7] - y1) * sy))
            continue
        vals = list(c[1:])
        for i in range(0, len(vals), 2):
            vals[i] = (vals[i] - x1) * sx
            vals[i + 1] = (vals[i + 1] - y1) * sy
        out.append((k, *vals))
    return out


def register_fonts(directory: str | None) -> None:
    """Make the extracted Acer fonts available to this process (fontconfig)."""
    if not directory:
        return
    try:
        import ctypes
        fc = ctypes.CDLL("libfontconfig.so.1")
        fc.FcConfigAppFontAddDir.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        fc.FcConfigAppFontAddDir(None, directory.encode())
    except OSError:
        pass


def draw_fallback_icon(cr, key: str, w: float, h: float, color: str, alpha: float = 1.0) -> None:
    """Simple vector icons used when the original NitroSense artwork is not installed."""
    cr.save()
    cr.set_source_rgba(*_with_alpha(color, alpha))
    cr.set_line_width(2)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cx, cy = w / 2, h / 2
    if key.startswith("Close"):
        r = min(w, h) * 0.3
        cr.move_to(cx - r, cy - r)
        cr.line_to(cx + r, cy + r)
        cr.move_to(cx + r, cy - r)
        cr.line_to(cx - r, cy + r)
        cr.stroke()
    elif key.startswith("Minimize"):
        r = min(w, h) * 0.35
        cr.move_to(cx - r, cy + 4)
        cr.line_to(cx + r, cy + 4)
        cr.stroke()
    elif key.startswith("Setting"):
        r = min(w, h) * 0.2
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()
        for i in range(8):
            a = i * math.pi / 4
            cr.move_to(cx + math.cos(a) * (r + 2), cy + math.sin(a) * (r + 2))
            cr.line_to(cx + math.cos(a) * (r + 5), cy + math.sin(a) * (r + 5))
        cr.stroke()
    elif key.startswith("Lighting"):
        kw, kh = w - 6, h - 10
        x0, y0 = 3, 5
        cr.set_line_width(1.5)
        cr.rectangle(x0, y0, kw, kh)
        cr.stroke()
        for row in range(2):
            for col in range(4):
                kx = x0 + 3 + col * (kw - 6) / 4
                ky = y0 + 3 + row * (kh - 6) / 2
                cr.rectangle(kx, ky, (kw - 6) / 4 - 2, (kh - 6) / 2 - 2)
        cr.fill()
    elif key.startswith("ShowCoolBooster"):
        r = min(w, h) / 2 - 1.5
        cr.set_line_width(1.5)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()
        cr.move_to(cx, cy - r * 0.1)
        cr.line_to(cx, cy + r * 0.5)
        cr.stroke()
        cr.arc(cx, cy - r * 0.5, 0.9, 0, 2 * math.pi)
        cr.fill()
    cr.restore()


CARD_FILL = "#181818"
CARD_BORDER = "#2E2E2E"
TEXT_INACTIVE = "#8C8C8C"


def rounded_rect(cr, x: float, y: float, w: float, h: float, r: float) -> None:
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def draw_fallback_background(cr, w: float, h: float) -> None:
    """Gradient backdrop plus the three section cards, used when the NitroSense artwork
    (img_bg_nitro.png / img_bg_newboard_nitro.png) is not installed."""
    grad = cairo.LinearGradient(0, 0, 0, h)
    grad.add_color_stop_rgb(0, 0.035, 0.035, 0.043)
    grad.add_color_stop_rgb(1, 0.067, 0.067, 0.075)
    cr.set_source(grad)
    cr.paint()
    for x, y, cw, ch in ((84, 92, 1152, 272), (84, 372, 300, 336), (396, 372, 840, 336)):
        rounded_rect(cr, x + 0.5, y + 0.5, cw - 1, ch - 1, 10)
        cr.set_source_rgba(*rgba(CARD_FILL))
        cr.fill_preserve()
        cr.set_source_rgba(*rgba(CARD_BORDER))
        cr.set_line_width(1)
        cr.stroke()
