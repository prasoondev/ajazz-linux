"""Small reusable widgets and the application stylesheet."""
from __future__ import annotations

import math

from gi.repository import Adw, Gdk, GObject, Gtk

CSS = """
.device-card { padding: 14px; border-radius: 14px; }
.device-card .title { font-weight: 700; font-size: 1.05em; }
.status-dot { min-width: 9px; min-height: 9px; border-radius: 99px; background: alpha(currentColor, .3); }
.status-dot.online { background: #33d17a; box-shadow: 0 0 6px #33d17a; }
levelbar.battery trough { min-height: 6px; border-radius: 99px; }
levelbar.battery block { border-radius: 99px; }

.board-card { padding: 18px; border-radius: 18px; background: #1b1b1f; }
.board-card .board-caption { font-size: .85em; color: rgba(255, 255, 255, .5); opacity: 1; }

flowbox.effect-grid > flowboxchild { padding: 0; border-radius: 14px; background: none; }
flowbox.effect-grid > flowboxchild:selected { background: none; }
.effect-card { padding: 8px 8px 10px 8px; border-radius: 14px; background: alpha(currentColor, .05);
               transition: background 150ms ease, box-shadow 150ms ease; }
.effect-card:hover { background: alpha(currentColor, .09); }
flowboxchild:selected .effect-card { background: alpha(var(--accent-bg-color), .18);
                                     box-shadow: inset 0 0 0 2px var(--accent-bg-color); }
.effect-card label { font-size: .9em; }

.swatch { padding: 0; min-width: 34px; min-height: 34px; border-radius: 99px; background: none; box-shadow: none; }
.swatch:hover { background: alpha(currentColor, .08); }

.hero-button { min-width: 84px; min-height: 84px; border-radius: 99px; padding: 0; }
.hero-button image { -gtk-icon-size: 36px; }
.hero-title { font-size: 1.4em; font-weight: 800; }

.power-button:checked { background: var(--accent-bg-color); color: var(--accent-fg-color); }
.toolbar-card { padding: 10px 12px; border-radius: 14px; }
.value-label { font-feature-settings: "tnum"; min-width: 2.2em; }
.experimental { font-size: .75em; font-weight: 700; padding: 2px 8px; border-radius: 99px;
                color: var(--warning-fg-color); background: var(--warning-bg-color); }
"""


def install_css():
    prov = Gtk.CssProvider()
    prov.load_from_string(CSS)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


class Swatch(Gtk.Button):
    """Round colour button. rgb=None draws a rainbow wheel."""

    __gsignals__ = {}

    def __init__(self, rgb, tooltip=None, size=28):
        super().__init__(tooltip_text=tooltip, valign=Gtk.Align.CENTER)
        self.add_css_class("swatch")
        self.rgb = rgb
        self._selected = False
        self.area = Gtk.DrawingArea(content_width=size + 6, content_height=size + 6)
        self.area.set_draw_func(self._draw)
        self.set_child(self.area)

    @property
    def selected(self):
        return self._selected

    @selected.setter
    def selected(self, v):
        self._selected = v
        self.area.queue_draw()

    def set_rgb(self, rgb):
        self.rgb = rgb
        self.area.queue_draw()

    def _draw(self, area, cr, w, h):
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 4
        if self.rgb is None:
            n = 36
            for i in range(n):
                a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1.2) / n
                import colorsys
                cr.set_source_rgb(*colorsys.hsv_to_rgb(i / n, 1, 1))
                cr.move_to(cx, cy)
                cr.arc(cx, cy, r, a0, a1)
                cr.close_path()
                cr.fill()
        else:
            cr.arc(cx, cy, r, 0, 2 * math.pi)
            cr.set_source_rgb(*(c / 255 for c in self.rgb))
            cr.fill()
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.set_source_rgba(1, 1, 1, 0.18)
        cr.set_line_width(1)
        cr.stroke()
        if self._selected:
            accent = Adw.StyleManager.get_default().get_accent_color_rgba()
            cr.arc(cx, cy, r + 2.5, 0, 2 * math.pi)
            cr.set_source_rgba(accent.red, accent.green, accent.blue, 1)
            cr.set_line_width(2.5)
            cr.stroke()
            # check mark
            light = self.rgb is not None and (0.299 * self.rgb[0] + 0.587 * self.rgb[1] + 0.114 * self.rgb[2]) > 150
            cr.set_source_rgb(*((0.1, 0.1, 0.1) if light else (1, 1, 1)))
            cr.set_line_width(2.4)
            cr.set_line_cap(1)
            cr.move_to(cx - r * 0.38, cy + 0.02 * r)
            cr.line_to(cx - r * 0.08, cy + r * 0.3)
            cr.line_to(cx + r * 0.42, cy - r * 0.3)
            cr.stroke()


class ValueSlider(Gtk.Box):
    """Scale with discrete steps and a live value label: [ scale ] [3/5]"""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, (float,))}

    def __init__(self, lo, hi, step, value, fmt="{:.0f}", width=240, marks=True):
        super().__init__(spacing=10, valign=Gtk.Align.CENTER)
        self.fmt = fmt
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
        self.scale.set_size_request(width, -1)
        self.scale.set_draw_value(False)
        self.scale.set_value(value)
        if marks:
            v = lo
            while v <= hi + 1e-9:
                self.scale.add_mark(v, Gtk.PositionType.BOTTOM, None)
                v += step
        self.label = Gtk.Label(xalign=1)
        self.label.add_css_class("value-label")
        self.label.add_css_class("dim-label")
        self.append(self.scale)
        self.append(self.label)
        self._update()
        self.scale.connect("value-changed", self._changed)

    def _update(self):
        self.label.set_text(self.fmt.format(self.scale.get_value()))

    def _changed(self, sc):
        self._update()
        self.emit("changed", sc.get_value())

    def get_value(self):
        return self.scale.get_value()

    def set_value(self, v):
        self.scale.set_value(v)


def experimental_tag():
    lbl = Gtk.Label(label="EXPERIMENTAL", valign=Gtk.Align.CENTER)
    lbl.add_css_class("experimental")
    return lbl
