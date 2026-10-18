"""A rendered AK820 board: glowing keycaps, hover, selection, badges, animation."""
from __future__ import annotations

import time

from gi.repository import Adw, Gdk, Gtk, Pango, PangoCairo

from .. import layout

CAP = (0.15, 0.15, 0.17)       # unlit keycap
PLATE = (0.07, 0.07, 0.08)     # case
PAD = 14                       # case padding in layout units


def _rounded(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
    cr.arc(x + r, y + r, r, 3.1416, 4.7124)
    cr.close_path()


class KeyboardView(Gtk.DrawingArea):
    """Callbacks (all optional):
        on_press(key, button, x, y)  key clicked
        on_drag(key)                 pointer dragged onto another key while pressed
        on_release()
    """

    def __init__(self, interactive=False, legends=True):
        super().__init__()
        self.colors: dict[int, tuple[int, int, int]] = {}
        self.selected: set[int] = set()
        self.badges: dict[int, str] = {}
        self.dimmed: set[int] = set()
        self.legends = legends
        self.hover = None
        self.interactive = interactive
        self.on_press = self.on_drag = self.on_release = None
        self._animator = None
        self._tick_id = 0
        self._t0 = time.monotonic()
        self._font_cache = {}

        xs = [k.rect[0] for k in layout.KEYS] + [k.rect[0] + k.rect[2] for k in layout.KEYS]
        ys = [k.rect[1] for k in layout.KEYS] + [k.rect[1] + k.rect[3] for k in layout.KEYS]
        self.bounds = (min(xs) - PAD, min(ys) - PAD, max(xs) + PAD, max(ys) + PAD)
        bw, bh = self.bounds[2] - self.bounds[0], self.bounds[3] - self.bounds[1]
        self.aspect = bw / bh
        self.set_content_width(720)
        self.set_content_height(int(720 / self.aspect))
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

        if interactive:
            motion = Gtk.EventControllerMotion()
            motion.connect("motion", self._motion)
            motion.connect("leave", lambda *a: self._set_hover(None))
            self.add_controller(motion)
            drag = Gtk.GestureDrag(button=0)
            drag.connect("drag-begin", self._drag_begin)
            drag.connect("drag-update", self._drag_update)
            drag.connect("drag-end", self._drag_end)
            self.add_controller(drag)
            self._origin = (0, 0)
            self._last = None
            self.set_cursor(Gdk.Cursor.new_from_name("pointer"))

    # -- animation -------------------------------------------------------------
    def set_animator(self, fn):
        """fn(t) -> {led: (r, g, b)} called every frame, or None to stop."""
        self._animator = fn
        if fn and not self._tick_id:
            self._tick_id = self.add_tick_callback(self._tick)
        elif not fn and self._tick_id:
            self.remove_tick_callback(self._tick_id)
            self._tick_id = 0

    def _tick(self, widget, clock):
        if self._animator and self.get_mapped():
            self.colors = self._animator(time.monotonic() - self._t0)
            self.queue_draw()
        return True

    # -- geometry --------------------------------------------------------------
    def _transform(self):
        w, h = self.get_width(), self.get_height()
        x0, y0, x1, y1 = self.bounds
        s = min(w / (x1 - x0), h / (y1 - y0))
        ox = (w - (x1 - x0) * s) / 2 - x0 * s
        oy = (h - (y1 - y0) * s) / 2 - y0 * s
        return s, ox, oy

    def key_rect(self, key) -> Gdk.Rectangle:
        s, ox, oy = self._transform()
        x, y, w, h = key.rect
        r = Gdk.Rectangle()
        r.x, r.y, r.width, r.height = int(ox + x * s), int(oy + y * s), int(w * s), int(h * s)
        return r

    def key_at(self, x, y):
        s, ox, oy = self._transform()
        ux, uy = (x - ox) / s, (y - oy) / s
        for k in layout.KEYS:
            kx, ky, kw, kh = k.rect
            if kx <= ux <= kx + kw and ky <= uy <= ky + kh:
                return k
        return None

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_measure(self, orientation, for_size):
        # keep the board's aspect ratio when the width is known
        if orientation == Gtk.Orientation.VERTICAL and for_size > 0:
            h = int(for_size / self.aspect)
            return h, h, -1, -1
        if orientation == Gtk.Orientation.VERTICAL:
            return 120, int(720 / self.aspect), -1, -1
        return 240, 720, -1, -1

    # -- input -----------------------------------------------------------------
    def _set_hover(self, led):
        if led != self.hover:
            self.hover = led
            self.queue_draw()

    def _motion(self, ctl, x, y):
        k = self.key_at(x, y)
        self._set_hover(k.led if k else None)

    def _drag_begin(self, g, x, y):
        self._origin = (x, y)
        k = self.key_at(x, y)
        self._last = k.led if k else None
        if k and self.on_press:
            self.on_press(k, g.get_current_button(), x, y)

    def _drag_update(self, g, dx, dy):
        x, y = self._origin[0] + dx, self._origin[1] + dy
        k = self.key_at(x, y)
        self._set_hover(k.led if k else None)
        if k and k.led != self._last:
            self._last = k.led
            if self.on_drag:
                self.on_drag(k)

    def _drag_end(self, *a):
        self._last = None
        if self.on_release:
            self.on_release()

    # -- drawing ---------------------------------------------------------------
    def _font(self, px):
        f = self._font_cache.get(px)
        if f is None:
            f = Pango.FontDescription.from_string("Sans Semi-Bold")
            f.set_absolute_size(px * Pango.SCALE)
            self._font_cache[px] = f
        return f

    def _draw(self, area, cr, w, h):
        s, ox, oy = self._transform()
        x0, y0, x1, y1 = self.bounds
        accent = Adw.StyleManager.get_default().get_accent_color_rgba()

        # case
        _rounded(cr, ox + x0 * s, oy + y0 * s, (x1 - x0) * s, (y1 - y0) * s, 16 * s)
        cr.set_source_rgb(*PLATE)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.06)
        cr.set_line_width(1)
        cr.stroke()

        # underglow pass (soft halos behind lit keys)
        for k in layout.KEYS:
            c = self.colors.get(k.led)
            if not c or k.led in self.dimmed:
                continue
            m = max(c) / 255
            if m < 0.05:
                continue
            kx, ky, kw, kh = k.rect
            for grow, alpha in ((7, 0.07), (4, 0.10), (2, 0.14)):
                _rounded(cr, ox + (kx - grow) * s, oy + (ky - grow) * s,
                         (kw + 2 * grow) * s, (kh + 2 * grow) * s, (6 + grow) * s)
                cr.set_source_rgba(c[0] / 255, c[1] / 255, c[2] / 255, alpha * m)
                cr.fill()

        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(self._font(max(7, round(10.5 * s))))
        bfont = self._font(max(6, round(8 * s)))
        for k in layout.KEYS:
            kx, ky, kw, kh = k.rect
            x, y, ww, hh = ox + kx * s + 1.5, oy + ky * s + 1.5, kw * s - 3, kh * s - 3
            c = self.colors.get(k.led)
            lit = tuple(v / 255 for v in c) if c else (0, 0, 0)
            m = max(lit)
            dim = k.led in self.dimmed
            if dim:
                m *= 0.25
            fill = tuple(CAP[i] * (1 - 0.85 * m) + lit[i] * 0.85 * (1 if not dim else 0.25)
                         for i in range(3))
            _rounded(cr, x, y, ww, hh, 5 * s)
            cr.set_source_rgb(*fill)
            cr.fill()
            # top bevel highlight
            _rounded(cr, x + 2 * s, y + 1.5 * s, ww - 4 * s, hh * 0.55, 4 * s)
            cr.set_source_rgba(1, 1, 1, 0.05 + 0.05 * (1 - m))
            cr.fill()

            if self.legends:
                lum = 0.299 * fill[0] + 0.587 * fill[1] + 0.114 * fill[2]
                cr.set_source_rgba(*((0.08, 0.08, 0.1, 0.9) if lum > 0.55 else (0.93, 0.93, 0.95, 0.9)))
                lay.set_text(k.label, -1)
                tw, th = lay.get_pixel_size()
                cr.move_to(x + (ww - tw) / 2, y + (hh - th) / 2 - (3 * s if k.led in self.badges else 0))
                PangoCairo.show_layout(cr, lay)

            badge = self.badges.get(k.led)
            if badge:
                bl = PangoCairo.create_layout(cr)
                bl.set_font_description(bfont)
                bl.set_text(badge, -1)
                tw, th = bl.get_pixel_size()
                bw = min(ww - 4, tw + 6)
                bx, by = x + (ww - bw) / 2, y + hh - th - 4 * s
                _rounded(cr, bx, by, bw, th + 1, (th + 1) / 2)
                cr.set_source_rgba(accent.red, accent.green, accent.blue, 0.95)
                cr.fill()
                cr.set_source_rgb(1, 1, 1)
                cr.move_to(bx + (bw - tw) / 2, by + 0.5)
                PangoCairo.show_layout(cr, bl)

            if k.led in self.selected:
                _rounded(cr, x - 1, y - 1, ww + 2, hh + 2, 6 * s)
                cr.set_source_rgba(accent.red, accent.green, accent.blue, 1)
                cr.set_line_width(2.5)
                cr.stroke()
            elif self.interactive and k.led == self.hover:
                _rounded(cr, x - 0.5, y - 0.5, ww + 1, hh + 1, 5.5 * s)
                cr.set_source_rgba(1, 1, 1, 0.65)
                cr.set_line_width(1.5)
                cr.stroke()


class MiniBoard(Gtk.DrawingArea):
    """Tiny legend-less board for effect thumbnails."""

    def __init__(self, width=132):
        super().__init__()
        xs = [k.rect[0] for k in layout.KEYS] + [k.rect[0] + k.rect[2] for k in layout.KEYS]
        ys = [k.rect[1] for k in layout.KEYS] + [k.rect[1] + k.rect[3] for k in layout.KEYS]
        self.bounds = (min(xs) - 6, min(ys) - 6, max(xs) + 6, max(ys) + 6)
        aspect = (self.bounds[2] - self.bounds[0]) / (self.bounds[3] - self.bounds[1])
        self.set_content_width(width)
        self.set_content_height(int(width / aspect))
        self.colors: dict[int, tuple[int, int, int]] = {}
        self.set_draw_func(self._draw)

    def _draw(self, area, cr, w, h):
        x0, y0, x1, y1 = self.bounds
        s = min(w / (x1 - x0), h / (y1 - y0))
        ox = (w - (x1 - x0) * s) / 2 - x0 * s
        oy = (h - (y1 - y0) * s) / 2 - y0 * s
        _rounded(cr, ox + x0 * s, oy + y0 * s, (x1 - x0) * s, (y1 - y0) * s, 6)
        cr.set_source_rgb(*PLATE)
        cr.fill()
        for k in layout.KEYS:
            kx, ky, kw, kh = k.rect
            c = self.colors.get(k.led, (0, 0, 0))
            m = max(c) / 255
            cr.set_source_rgb(*(CAP[i] * (1 - m) + c[i] / 255 for i in range(3)))
            _rounded(cr, ox + kx * s + 0.6, oy + ky * s + 0.6, kw * s - 1.2, kh * s - 1.2, 1.5)
            cr.fill()
