"""GTK4 / libadwaita GUI for the AJAZZ AK820 Max Plus."""
from __future__ import annotations

import queue
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from . import __version__, layout, state  # noqa: E402
from . import protocol as P  # noqa: E402
from .device import DeviceError, Keyboard  # noqa: E402

APP_ID = "io.github.ajazzctl"
STATUS_INTERVAL_S = 5   # vendor app polls every 5 s

CSS = b"""
.swatch { min-width: 30px; min-height: 30px; border-radius: 15px; padding: 0; border: 2px solid alpha(currentColor, .15); }
.swatch:checked { border: 3px solid @accent_color; }
.swatch-rainbow { background-image: conic-gradient(red, yellow, lime, cyan, blue, magenta, red); }
""" + "".join(f".swatch-{i} {{ background: rgb{rgb}; }}\n"
             for i, (_, rgb) in enumerate(P.COLORS) if rgb).encode()


class DeviceWorker:
    """Serialises all device I/O on one background thread."""

    def __init__(self, on_status, on_error, on_connected):
        self.q: queue.Queue = queue.Queue()
        self.kb: Keyboard | None = None
        self.on_status, self.on_error, self.on_connected = on_status, on_error, on_connected
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, fn, *args, done=None):
        self.q.put((fn, args, done))

    def _run(self):
        while True:
            fn, args, done = self.q.get()
            try:
                if self.kb is None:
                    self._connect()
                result = fn(self.kb, *args)
                if done:
                    GLib.idle_add(done, result)
            except DeviceError as e:
                if self.kb is not None:
                    self.kb.close()
                    self.kb = None
                    GLib.idle_add(self.on_connected, None)
                GLib.idle_add(self.on_error, str(e))
            except Exception as e:  # never kill the worker thread
                GLib.idle_add(self.on_error, f"{type(e).__name__}: {e}")

    def _connect(self):
        self.kb = Keyboard.open()
        GLib.idle_add(self.on_connected, self.kb.node)


class KeyboardCanvas(Gtk.DrawingArea):
    """Clickable key map for per-key colours. Left button paints, right erases."""

    OFF = (0.16, 0.16, 0.18)

    def __init__(self, colors: dict[int, tuple[int, int, int]]):
        super().__init__()
        self.colors = colors
        self.brush: tuple[int, int, int] = (255, 255, 255)
        self.on_change = lambda: None
        self.set_content_width(760)
        self.set_content_height(240)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)
        self._last_led = None
        self._erase = False
        # keys occupy x 29..635, y 41..245 in the vendor's 800x300 canvas
        xs = [k.rect[0] for k in layout.KEYS] + [k.rect[0] + k.rect[2] for k in layout.KEYS]
        ys = [k.rect[1] for k in layout.KEYS] + [k.rect[1] + k.rect[3] for k in layout.KEYS]
        self.bounds = (min(xs), min(ys), max(xs), max(ys))

        drag = Gtk.GestureDrag(button=0)
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", lambda *a: setattr(self, "_last_led", None))
        self.add_controller(drag)
        self._drag_origin = (0, 0)

    def _transform(self, w, h):
        x0, y0, x1, y1 = self.bounds
        pad = 6
        s = min((w - 2 * pad) / (x1 - x0), (h - 2 * pad) / (y1 - y0))
        ox = (w - (x1 - x0) * s) / 2 - x0 * s
        oy = (h - (y1 - y0) * s) / 2 - y0 * s
        return s, ox, oy

    def _key_at(self, x, y):
        s, ox, oy = self._transform(self.get_width(), self.get_height())
        ux, uy = (x - ox) / s, (y - oy) / s
        for k in layout.KEYS:
            kx, ky, kw, kh = k.rect
            if kx <= ux <= kx + kw and ky <= uy <= ky + kh:
                return k
        return None

    def _paint_at(self, x, y):
        k = self._key_at(x, y)
        if not k or k.led == self._last_led:
            return
        self._last_led = k.led
        if self._erase:
            self.colors.pop(k.led, None)
        else:
            self.colors[k.led] = self.brush
        self.queue_draw()
        self.on_change()

    def _drag_begin(self, gesture, x, y):
        self._erase = gesture.get_current_button() == Gdk.BUTTON_SECONDARY
        self._drag_origin = (x, y)
        self._last_led = None
        self._paint_at(x, y)

    def _drag_update(self, gesture, dx, dy):
        self._paint_at(self._drag_origin[0] + dx, self._drag_origin[1] + dy)

    def _draw(self, area, cr, w, h):
        s, ox, oy = self._transform(w, h)
        fg = self.get_color()
        layout_ = PangoCairo.create_layout(cr)
        font = Pango.FontDescription.from_string(f"Sans {max(6, int(9 * s))}px")
        font.set_absolute_size(max(6, 10 * s) * Pango.SCALE)
        layout_.set_font_description(font)
        for k in layout.KEYS:
            kx, ky, kw, kh = k.rect
            x, y, ww, hh = ox + kx * s + 1.5, oy + ky * s + 1.5, kw * s - 3, kh * s - 3
            r = 5 * s
            cr.new_sub_path()
            cr.arc(x + ww - r, y + r, r, -1.5708, 0)
            cr.arc(x + ww - r, y + hh - r, r, 0, 1.5708)
            cr.arc(x + r, y + hh - r, r, 1.5708, 3.1416)
            cr.arc(x + r, y + r, r, 3.1416, 4.7124)
            cr.close_path()
            c = self.colors.get(k.led)
            rgb = tuple(v / 255 for v in c) if c else self.OFF
            cr.set_source_rgb(*rgb)
            cr.fill_preserve()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.25)
            cr.set_line_width(1)
            cr.stroke()
            lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
            cr.set_source_rgb(*((0.1, 0.1, 0.1) if lum > 0.55 else (0.92, 0.92, 0.92)))
            layout_.set_text(k.label, -1)
            tw, th = layout_.get_pixel_size()
            cr.move_to(x + (ww - tw) / 2, y + (hh - th) / 2)
            PangoCairo.show_layout(cr, layout_)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="AJAZZ AK820 Max Plus")
        self.set_default_size(900, 640)
        self._suspend = True
        self._apply_source = 0
        self.settings = state.light_settings()
        self.connected_node = None

        self.toasts = Adw.ToastOverlay()
        tv = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)
        about = Gtk.Button(icon_name="help-about-symbolic", tooltip_text="About")
        about.connect("clicked", self._about)
        header.pack_end(about)
        tv.add_top_bar(header)

        self.banner = Adw.Banner(title="Searching for keyboard…", revealed=True)
        tv.add_top_bar(self.banner)

        self.stack.add_titled_with_icon(self._lighting_page(), "lighting", "Lighting",
                                        "display-brightness-symbolic")
        self.stack.add_titled_with_icon(self._custom_page(), "custom", "Per-key",
                                        "applications-graphics-symbolic")
        self.stack.add_titled_with_icon(self._settings_page(), "settings", "Settings",
                                        "preferences-system-symbolic")
        tv.set_content(self.stack)
        self.toasts.set_child(tv)
        self.set_content(self.toasts)

        self.worker = DeviceWorker(self._on_status, self._on_error, self._on_connected)
        self._suspend = False
        self._refresh_status()
        GLib.timeout_add_seconds(STATUS_INTERVAL_S, self._refresh_status)

    # -- pages ---------------------------------------------------------------
    def _lighting_page(self):
        page = Adw.PreferencesPage()
        grp = Adw.PreferencesGroup(title="Effect",
                                   description="Changes are sent to the keyboard immediately.")
        page.add(grp)

        self.effect_row = Adw.ComboRow(title="Effect",
                                       model=Gtk.StringList.new([e.name for e in P.EFFECTS
                                                                 if e.mode != P.MODE_CUSTOM]))
        self._effects = [e for e in P.EFFECTS if e.mode != P.MODE_CUSTOM]
        idx = next((i for i, e in enumerate(self._effects) if e.mode == self.settings.mode), 6)
        self.effect_row.set_selected(idx)
        self.effect_row.connect("notify::selected", lambda *a: self._changed())
        grp.add(self.effect_row)

        self.bright_row, self.bright = self._scale_row("Brightness", self.settings.brightness)
        self.speed_row, self.speed = self._scale_row("Speed", self.settings.speed)
        grp.add(self.bright_row)
        grp.add(self.speed_row)

        self.dir_row = Adw.ActionRow(title="Direction")
        self.dir_group = Adw.ToggleGroup(valign=Gtk.Align.CENTER)
        self.dir_group.add(Adw.Toggle(name="left", icon_name="go-previous-symbolic", tooltip="Left"))
        self.dir_group.add(Adw.Toggle(name="right", icon_name="go-next-symbolic", tooltip="Right"))
        self.dir_group.set_active_name("left" if self.settings.direction == P.DIRECTION_LEFT else "right")
        self.dir_group.connect("notify::active-name", lambda *a: self._changed())
        self.dir_row.add_suffix(self.dir_group)
        grp.add(self.dir_row)

        self.color_row = Adw.ActionRow(title="Colour")
        box = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        self.swatches = []
        first = None
        for i, (name, rgb) in enumerate(P.COLORS):
            b = Gtk.ToggleButton(tooltip_text=name.capitalize())
            b.add_css_class("swatch")
            if rgb is None:
                b.add_css_class("swatch-rainbow")
            else:
                b.add_css_class(f"swatch-{i}")
            if first:
                b.set_group(first)
            else:
                first = b
            b.set_active(i == self.settings.color)
            b.connect("toggled", self._swatch_toggled, i)
            self.swatches.append(b)
            box.append(b)
        self.color_row.add_suffix(box)
        grp.add(self.color_row)

        note = Adw.PreferencesGroup(
            description="The keyboard cannot report its current lighting, so the values shown are "
                        "the last ones sent from this computer. Fn shortcuts on the keyboard may "
                        "have changed them since.")
        page.add(note)
        self._update_sensitivity()
        return page

    def _scale_row(self, title, value):
        row = Adw.ActionRow(title=title)
        sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 5, 1)
        sc.set_value(value)
        sc.set_digits(0)
        sc.set_draw_value(True)
        sc.set_size_request(260, -1)
        sc.set_valign(Gtk.Align.CENTER)
        for i in range(1, 6):
            sc.add_mark(i, Gtk.PositionType.BOTTOM, None)
        sc.connect("value-changed", lambda *a: self._changed())
        row.add_suffix(sc)
        return row, sc

    def _custom_page(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                        margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        self.custom_colors = dict(state.custom_colors())
        self.canvas = KeyboardCanvas(self.custom_colors)
        self.canvas.set_vexpand(True)
        frame = Gtk.Frame(child=self.canvas)
        outer.append(Gtk.Label(label="Left-click or drag to paint keys, right-click to turn a key off.",
                               xalign=0, css_classes=["dim-label"]))
        outer.append(frame)

        bar = Gtk.Box(spacing=8)
        bar.append(Gtk.Label(label="Brush"))
        self.brush_btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False))
        rgba = Gdk.RGBA()
        rgba.parse("#ffffff")
        self.brush_btn.set_rgba(rgba)
        self.brush_btn.connect("notify::rgba", self._brush_changed)
        bar.append(self.brush_btn)
        fill = Gtk.Button(label="Fill all")
        fill.connect("clicked", self._fill_all)
        clear = Gtk.Button(label="Clear")
        clear.connect("clicked", self._clear)
        bar.append(fill)
        bar.append(clear)
        spacer = Gtk.Box(hexpand=True)
        bar.append(spacer)
        bar.append(Gtk.Label(label="Brightness"))
        self.custom_bright = Gtk.SpinButton.new_with_range(1, 5, 1)
        self.custom_bright.set_value(self.settings.brightness)
        bar.append(self.custom_bright)
        self.custom_apply = Gtk.Button(label="Apply to keyboard", css_classes=["suggested-action"])
        self.custom_apply.connect("clicked", self._apply_custom)
        bar.append(self.custom_apply)
        outer.append(bar)
        return outer

    def _settings_page(self):
        page = Adw.PreferencesPage()
        grp = Adw.PreferencesGroup(
            title="Keyboard", description="These settings are write-only: the keyboard does not "
                                          "report them, so the controls show what was last sent.")
        page.add(grp)
        saved = state.load().get("settings", {})

        self.sleep_row = Adw.ComboRow(title="Sleep after",
                                      model=Gtk.StringList.new(["5 minutes", "15 minutes",
                                                                "30 minutes", "Never"]))
        if saved.get("sleep_time") in P.SLEEP_TIMES:
            self.sleep_row.set_selected(P.SLEEP_TIMES.index(saved["sleep_time"]))
        self.sleep_row.connect("notify::selected", self._sleep_changed)
        grp.add(self.sleep_row)

        self.resp_row = Adw.ComboRow(
            title="Key response time",
            subtitle="Gear 1 is fastest (wired ≈2–3 ms, 2.4 GHz ≈5–6 ms)",
            model=Gtk.StringList.new(["Gear 1", "Gear 2", "Gear 3"]))
        if saved.get("response_time") in P.RESPONSE_TIMES:
            self.resp_row.set_selected(P.RESPONSE_TIMES.index(saved["response_time"]))
        self.resp_row.connect("notify::selected", self._resp_changed)
        grp.add(self.resp_row)

        self.fn_row = Adw.SwitchRow(title="Fn switch",
                                    subtitle="Swap the default action of the F-row")
        self.fn_row.set_active(bool(saved.get("fn_switch", False)))
        self.fn_row.connect("notify::active", self._fn_changed)
        grp.add(self.fn_row)

        info = Adw.PreferencesGroup(title="Device")
        self.dev_row = Adw.ActionRow(title="Connection", subtitle="—")
        self.batt_row = Adw.ActionRow(title="Battery", subtitle="—")
        info.add(self.dev_row)
        info.add(self.batt_row)
        page.add(info)
        return page

    # -- handlers --------------------------------------------------------------
    def _current_settings(self) -> P.LightSettings:
        e = self._effects[self.effect_row.get_selected()]
        color = next((i for i, b in enumerate(self.swatches) if b.get_active()), 7)
        return P.LightSettings(
            mode=e.mode, brightness=int(self.bright.get_value()), speed=int(self.speed.get_value()),
            direction=P.DIRECTION_LEFT if self.dir_group.get_active_name() == "left" else P.DIRECTION_RIGHT,
            color=color)

    def _update_sensitivity(self):
        e = self._effects[self.effect_row.get_selected()]
        self.bright_row.set_sensitive(e.has_brightness)
        self.speed_row.set_sensitive(e.has_speed)
        self.dir_row.set_sensitive(e.has_direction)
        self.color_row.set_sensitive(e.has_color)

    def _swatch_toggled(self, btn, idx):
        if btn.get_active():
            self._changed()

    def _changed(self):
        if self._suspend:
            return
        self._update_sensitivity()
        # debounce slider drags: send at most every 150 ms
        if self._apply_source:
            GLib.source_remove(self._apply_source)
        self._apply_source = GLib.timeout_add(150, self._apply_lighting)

    def _apply_lighting(self):
        self._apply_source = 0
        s = self._current_settings()

        def done(_):
            state.remember_lighting(s)
        self.worker.submit(lambda kb: kb.set_lighting(s), done=done)
        return GLib.SOURCE_REMOVE

    def _brush_changed(self, *a):
        c = self.brush_btn.get_rgba()
        self.canvas.brush = (round(c.red * 255), round(c.green * 255), round(c.blue * 255))

    def _fill_all(self, *a):
        for k in layout.KEYS:
            self.custom_colors[k.led] = self.canvas.brush
        self.canvas.queue_draw()

    def _clear(self, *a):
        self.custom_colors.clear()
        self.canvas.queue_draw()

    def _apply_custom(self, *a):
        colors = dict(self.custom_colors)
        b = int(self.custom_bright.get_value())
        self.custom_apply.set_sensitive(False)

        def done(_):
            state.remember_custom(colors, b)
            self.custom_apply.set_sensitive(True)
            self._toast("Custom colours sent")

        def job(kb):
            try:
                kb.set_custom_colors(colors, brightness=b)
            finally:
                GLib.idle_add(self.custom_apply.set_sensitive, True)
        self.worker.submit(job, done=done)

    def _sleep_changed(self, row, _):
        v = P.SLEEP_TIMES[row.get_selected()]
        self.worker.submit(lambda kb: kb.set_sleep_time(row.get_selected()),
                           done=lambda _: state.remember("sleep_time", v))

    def _resp_changed(self, row, _):
        v = P.RESPONSE_TIMES[row.get_selected()]
        self.worker.submit(lambda kb: kb.set_response_time(row.get_selected()),
                           done=lambda _: state.remember("response_time", v))

    def _fn_changed(self, row, _):
        on = row.get_active()
        self.worker.submit(lambda kb: kb.set_fn_switch(on),
                           done=lambda _: state.remember("fn_switch", on))

    # -- device status -----------------------------------------------------------
    def _refresh_status(self):
        self.worker.submit(lambda kb: kb.status(), done=self._on_status)
        return GLib.SOURCE_CONTINUE

    def _on_connected(self, node):
        self.connected_node = node
        if node is None:
            self.banner.set_title("Keyboard disconnected — retrying…")
            self.banner.set_revealed(True)
            self.dev_row.set_subtitle("not connected")
            self.batt_row.set_subtitle("—")
            return
        self.banner.set_revealed(False)
        self.dev_row.set_subtitle(f"{node.connection} · {node.hid_name} · {node.devnode}")

    def _on_status(self, st: P.Status):
        if st.battery is None or st.power_state == 0:
            self.batt_row.set_subtitle(f"no data ({st.power_state_name})")
        else:
            self.batt_row.set_subtitle(f"{st.battery}% · {st.power_state_name}")

    def _on_error(self, msg):
        if self.connected_node is None:
            self.banner.set_title(msg)
            self.banner.set_revealed(True)
        else:
            self._toast(msg)

    def _toast(self, msg):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(msg), timeout=4))

    def _about(self, *a):
        Adw.AboutDialog(application_name="ajazzctl", version=__version__,
                        comments="Linux configuration tool for the AJAZZ AK820 Max Plus.\n"
                                 "Unofficial; protocol reverse-engineered from the vendor software.",
                        license_type=Gtk.License.MIT_X11).present(self)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_startup(self):
        Adw.Application.do_startup(self)
        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        win = self.get_active_window() or MainWindow(self)
        win.present()


def main() -> int:
    return App().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
