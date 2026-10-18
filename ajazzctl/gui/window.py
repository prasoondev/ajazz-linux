"""Main window: sidebar navigation + Lighting / Per-key / Music / Keymap / Settings."""
from __future__ import annotations

import time
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .. import __version__, layout, preview, state
from .. import protocol as P
from ..device import DeviceError
from .keyboard_view import KeyboardView, MiniBoard
from .widgets import Swatch, ValueSlider, experimental_tag
from .worker import DeviceWorker, FrameStreamer, restore_lighting

STATUS_INTERVAL_S = 5

PAGES = (
    ("lighting", "Lighting", "display-brightness-symbolic"),
    ("perkey", "Per-key RGB", "applications-graphics-symbolic"),
    ("music", "Music Sync", "audio-x-generic-symbolic"),
    ("keymap", "Key Remap", "input-keyboard-symbolic"),
    ("settings", "Settings", "emblem-system-symbolic"),
)


def _page_scroller(*children, maximum=980):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24,
                  margin_top=24, margin_bottom=32, margin_start=18, margin_end=18)
    for c in children:
        box.append(c)
    clamp = Adw.Clamp(maximum_size=maximum, tightening_threshold=600, child=box)
    return Gtk.ScrolledWindow(child=clamp, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True), box


def _board_card(view, caption=None):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.add_css_class("board-card")
    box.append(view)
    if caption:
        lbl = Gtk.Label(label=caption, xalign=0.5)
        lbl.add_css_class("dim-label")
        lbl.add_css_class("board-caption")
        box.append(lbl)
        box.caption = lbl
    return box


def _section_title(text, suffix=None):
    row = Gtk.Box(spacing=8)
    lbl = Gtk.Label(label=text, xalign=0, hexpand=True)
    lbl.add_css_class("heading")
    row.append(lbl)
    if suffix:
        row.append(suffix)
    return row


# ---------------------------------------------------------------------------
class LightingPage:
    def __init__(self, win):
        self.win = win
        self.settings = state.light_settings()
        self._suspend = True
        self._apply_id = 0

        self.view = KeyboardView()
        self.view.set_animator(lambda t: {} if state.lights_off()
                               else preview.frame(self.settings, t, state.custom_colors()))
        card = _board_card(self.view, "Preview, approximately what the keyboard shows")

        power = Adw.PreferencesGroup()
        self.power_row = Adw.SwitchRow(title="Keyboard lighting",
                                       subtitle="Turn all LEDs off; your settings are kept",
                                       active=not state.lights_off())
        self.power_row.add_prefix(Gtk.Image(icon_name="system-shutdown-symbolic"))
        self.power_row.connect("notify::active", lambda r, _: win.set_lights(r.get_active()))
        power.add(self.power_row)

        # effect gallery
        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.SINGLE, homogeneous=True,
                                min_children_per_line=2, max_children_per_line=6,
                                column_spacing=10, row_spacing=10, activate_on_single_click=True)
        self.flow.add_css_class("effect-grid")
        self.cards = []
        for e in P.EFFECTS:
            mini = MiniBoard()
            lbl = Gtk.Label(label=e.name, wrap=True, justify=Gtk.Justification.CENTER,
                            lines=2, ellipsize=3, max_width_chars=14)
            b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            b.add_css_class("effect-card")
            b.append(mini)
            b.append(lbl)
            child = Gtk.FlowBoxChild(child=b)
            child.effect = e
            self.flow.append(child)
            self.cards.append((child, mini, e))
            if e.mode == self.settings.mode:
                self.flow.select_child(child)
        self.flow.connect("child-activated", self._effect_chosen)

        # options
        opts = Adw.PreferencesGroup(title="Options")
        self.bright = ValueSlider(1, 5, 1, self.settings.brightness)
        self.bright_row = Adw.ActionRow(title="Brightness")
        self.bright_row.add_prefix(Gtk.Image(icon_name="display-brightness-symbolic"))
        self.bright_row.add_suffix(self.bright)
        self.speed = ValueSlider(1, 5, 1, self.settings.speed)
        self.speed_row = Adw.ActionRow(title="Speed")
        self.speed_row.add_prefix(Gtk.Image(icon_name="media-seek-forward-symbolic"))
        self.speed_row.add_suffix(self.speed)
        self.dir = Adw.ToggleGroup(valign=Gtk.Align.CENTER)
        self.dir.add(Adw.Toggle(name="left", label="Left", icon_name="go-previous-symbolic"))
        self.dir.add(Adw.Toggle(name="right", label="Right", icon_name="go-next-symbolic"))
        self.dir.set_active_name("left" if self.settings.direction == P.DIRECTION_LEFT else "right")
        self.dir_row = Adw.ActionRow(title="Direction")
        self.dir_row.add_prefix(Gtk.Image(icon_name="object-flip-horizontal-symbolic"))
        self.dir_row.add_suffix(self.dir)

        self.color_row = Adw.ActionRow(title="Colour")
        self.color_row.add_prefix(Gtk.Image(icon_name="color-select-symbolic"))
        wrap = Adw.WrapBox(child_spacing=4, line_spacing=4, valign=Gtk.Align.CENTER,
                           justify=Adw.JustifyMode.NONE)
        self.swatches = []
        for i, (name, rgb) in enumerate(P.COLORS):
            sw = Swatch(rgb, tooltip=name.capitalize())
            sw.connect("clicked", self._color_clicked, i)
            sw.selected = i == self.settings.color
            self.swatches.append(sw)
            wrap.append(sw)
        self.color_row.add_suffix(wrap)
        for r in (self.bright_row, self.speed_row, self.dir_row, self.color_row):
            opts.add(r)
        self.bright.connect("changed", lambda *a: self._changed())
        self.speed.connect("changed", lambda *a: self._changed())
        self.dir.connect("notify::active-name", lambda *a: self._changed())

        note = Gtk.Label(
            label="The keyboard can't report its current lighting, so these are the values last "
                  "sent from this computer. Fn shortcuts on the keyboard may have changed them.",
            wrap=True, xalign=0)
        note.add_css_class("dim-label")
        note.add_css_class("caption")

        self.widget, _ = _page_scroller(power, card, _section_title("Effects"), self.flow, opts, note)
        self._sync_sensitivity()
        GLib.timeout_add(70, self._animate_thumbs)
        self._suspend = False

    def _animate_thumbs(self):
        if self.flow.get_mapped():
            t = time.monotonic()
            for child, mini, e in self.cards:
                if e.mode == P.MODE_CUSTOM:
                    s = P.LightSettings(mode=e.mode)
                    mini.colors = preview.frame(s, t, state.custom_colors() or
                                                {k.led: (40, 40, 48) for k in layout.KEYS})
                else:
                    s = P.LightSettings(mode=e.mode, color=self.settings.color if e.has_color else 7,
                                        speed=3, brightness=5)
                    mini.colors = preview.frame(s, t)
                mini.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _sync_sensitivity(self):
        e = P.EFFECTS_BY_MODE[self.settings.mode]
        custom = e.mode == P.MODE_CUSTOM
        self.bright_row.set_sensitive(e.has_brightness or custom)
        self.speed_row.set_sensitive(e.has_speed)
        self.dir_row.set_sensitive(e.has_direction)
        self.color_row.set_sensitive(e.has_color)

    def _effect_chosen(self, flow, child):
        self.settings.mode = child.effect.mode
        self._changed()

    def _color_clicked(self, sw, idx):
        for i, s in enumerate(self.swatches):
            s.selected = i == idx
        self.settings.color = idx
        self._changed()

    def _changed(self):
        if self._suspend:
            return
        self.settings.brightness = int(self.bright.get_value())
        self.settings.speed = int(self.speed.get_value())
        self.settings.direction = (P.DIRECTION_LEFT if self.dir.get_active_name() == "left"
                                   else P.DIRECTION_RIGHT)
        self._sync_sensitivity()
        if self._apply_id:
            GLib.source_remove(self._apply_id)
        self._apply_id = GLib.timeout_add(120, self._apply)

    def _apply(self):
        self._apply_id = 0
        s = P.LightSettings(**vars(self.settings))
        self.win.stop_live(restore=False)
        if s.mode == P.MODE_CUSTOM:
            colors = state.custom_colors()
            self.win.worker.submit(lambda kb: kb.set_custom_colors(colors, s.brightness),
                                   done=lambda _: (state.remember_custom(colors, s.brightness),
                                                   self.win.sync_lights_ui()))
        else:
            self.win.worker.submit(lambda kb: kb.set_lighting(s),
                                   done=lambda _: (state.remember_lighting(s),
                                                   self.win.sync_lights_ui()))
        return GLib.SOURCE_REMOVE

    def refresh_from_state(self):
        self.settings = state.light_settings()


# ---------------------------------------------------------------------------
PALETTE = [(255, 0, 0), (255, 96, 0), (255, 200, 0), (120, 255, 0), (0, 255, 80), (0, 255, 220),
           (0, 140, 255), (40, 40, 255), (150, 0, 255), (255, 0, 200), (255, 255, 255),
           (255, 170, 120)]


class PerKeyPage:
    def __init__(self, win):
        self.win = win
        self.colors = dict(state.custom_colors())
        self.brush = (0, 140, 255)
        self.undo_stack, self.redo_stack = [], []
        self.recent: list[tuple[int, int, int]] = []
        self.streamer = None

        self.view = KeyboardView(interactive=True)
        self.view.colors = self.colors
        self.view.on_press = self._press
        self.view.on_drag = self._drag
        card = _board_card(self.view, "Drag to paint · right-click erases · Ctrl+Z undo")

        # tool bar
        self.tool = Adw.ToggleGroup(valign=Gtk.Align.CENTER)
        self.tool.add(Adw.Toggle(name="paint", label="Paint", icon_name="document-edit-symbolic"))
        self.tool.add(Adw.Toggle(name="erase", label="Erase", icon_name="edit-clear-symbolic"))
        self.tool.add(Adw.Toggle(name="pick", label="Pick", icon_name="color-select-symbolic"))
        self.tool.set_active_name("paint")

        undo = Gtk.Button(icon_name="edit-undo-symbolic", tooltip_text="Undo (Ctrl+Z)",
                          valign=Gtk.Align.CENTER)
        redo = Gtk.Button(icon_name="edit-redo-symbolic", tooltip_text="Redo (Ctrl+Shift+Z)",
                          valign=Gtk.Align.CENTER)
        undo.connect("clicked", lambda *a: self.undo())
        redo.connect("clicked", lambda *a: self.redo())
        self.undo_btn, self.redo_btn = undo, redo

        menu = Gio.Menu()
        for label, action in (("Rainbow", "rainbow"), ("Gradient from brush", "gradient"),
                              ("Gaming (WASD + arrows)", "gaming"), ("Fill all with brush", "fill"),
                              ("Clear all", "clear")):
            menu.append(label, f"perkey.{action}")
        group = Gio.SimpleActionGroup()
        for name in ("rainbow", "gradient", "gaming", "fill", "clear"):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda act, _p, n=name: self.preset(n))
            group.add_action(a)
        win.insert_action_group("perkey", group)
        presets = Gtk.MenuButton(label="Presets", menu_model=menu, valign=Gtk.Align.CENTER,
                                 always_show_arrow=True)

        tools = Gtk.Box(spacing=8)
        tools.add_css_class("card")
        tools.add_css_class("toolbar-card")
        tools.append(self.tool)
        tools.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        tools.append(undo)
        tools.append(redo)
        tools.append(Gtk.Box(hexpand=True))
        tools.append(presets)

        # palette
        pal = Adw.PreferencesGroup(title="Brush colour")
        self.brush_sw = Swatch(self.brush, size=36)
        self.brush_sw.set_can_target(False)
        self.custom_btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False),
                                                valign=Gtk.Align.CENTER, tooltip_text="Custom colour")
        self.custom_btn.connect("notify::rgba", self._custom_color)
        wrap = Adw.WrapBox(child_spacing=4, line_spacing=4, valign=Gtk.Align.CENTER)
        self.pal_swatches = []
        for rgb in PALETTE:
            sw = Swatch(rgb, size=24)
            sw.connect("clicked", lambda s: self.set_brush(s.rgb))
            wrap.append(sw)
            self.pal_swatches.append(sw)
        row = Adw.ActionRow(title="Palette")
        row.add_prefix(self.brush_sw)
        row.add_suffix(wrap)
        row.add_suffix(self.custom_btn)
        pal.add(row)
        self.recent_row = Adw.ActionRow(title="Recent")
        self.recent_box = Gtk.Box(spacing=4, valign=Gtk.Align.CENTER)
        self.recent_row.add_suffix(self.recent_box)
        self.recent_row.set_visible(False)
        pal.add(self.recent_row)

        # apply
        out = Adw.PreferencesGroup(title="Keyboard")
        self.bright = ValueSlider(1, 5, 1, state.light_settings().brightness)
        r = Adw.ActionRow(title="Brightness")
        r.add_suffix(self.bright)
        out.add(r)
        self.live_row = Adw.SwitchRow(title="Live preview on keyboard",
                                      subtitle="Mirror edits on the keyboard instantly (not saved)")
        self.live_row.connect("notify::active", self._live_toggled)
        out.add(self.live_row)
        save = Adw.ButtonRow(title="Save to Keyboard", start_icon_name="document-save-symbolic")
        save.add_css_class("suggested-action")
        save.connect("activated", lambda *a: self.save())
        out.add(save)

        self.widget, _ = _page_scroller(card, tools, pal, out)
        self._sync_buttons()

    # brush / tools
    def set_brush(self, rgb):
        self.brush = tuple(rgb)
        self.brush_sw.set_rgb(self.brush)
        for sw in self.pal_swatches:
            sw.selected = sw.rgb == self.brush
        if self.tool.get_active_name() != "paint":
            self.tool.set_active_name("paint")

    def _custom_color(self, btn, _):
        c = btn.get_rgba()
        self.set_brush((round(c.red * 255), round(c.green * 255), round(c.blue * 255)))

    def _remember_recent(self):
        if self.brush in PALETTE or self.brush in self.recent:
            return
        self.recent = [self.brush] + self.recent[:7]
        child = self.recent_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.recent_box.remove(child)
            child = nxt
        for rgb in self.recent:
            sw = Swatch(rgb, size=22)
            sw.connect("clicked", lambda s: self.set_brush(s.rgb))
            self.recent_box.append(sw)
        self.recent_row.set_visible(True)

    def _apply_tool(self, key, button):
        tool = "erase" if button == Gdk.BUTTON_SECONDARY else self.tool.get_active_name()
        if tool == "pick":
            if key.led in self.colors:
                self.set_brush(self.colors[key.led])
            return False
        if tool == "erase":
            self.colors.pop(key.led, None)
        else:
            self.colors[key.led] = self.brush
        self.view.queue_draw()
        return True

    def _press(self, key, button, x, y):
        self._button = button
        self._snapshot()
        if self.tool.get_active_name() == "paint" and button != Gdk.BUTTON_SECONDARY:
            self._remember_recent()
        if not self._apply_tool(key, button):
            self.undo_stack.pop()
        self._sync_buttons()

    def _drag(self, key):
        if self.tool.get_active_name() != "pick":
            self._apply_tool(key, getattr(self, "_button", 1))

    # history
    def _snapshot(self):
        self.undo_stack.append(dict(self.colors))
        self.undo_stack = self.undo_stack[-100:]
        self.redo_stack.clear()

    def _restore(self, snap):
        self.colors.clear()
        self.colors.update(snap)
        self.view.queue_draw()
        self._sync_buttons()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(dict(self.colors))
            self._restore(self.undo_stack.pop())

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(dict(self.colors))
            self._restore(self.redo_stack.pop())

    def _sync_buttons(self):
        self.undo_btn.set_sensitive(bool(self.undo_stack))
        self.redo_btn.set_sensitive(bool(self.redo_stack))

    def preset(self, name):
        import colorsys
        self._snapshot()
        pos = preview.POS
        if name == "clear":
            self.colors.clear()
        elif name == "fill":
            for k in layout.KEYS:
                self.colors[k.led] = self.brush
        elif name == "rainbow":
            for led, (u, v, _) in pos.items():
                r, g, b = colorsys.hsv_to_rgb(u * 0.85, 1, 1)
                self.colors[led] = (int(r * 255), int(g * 255), int(b * 255))
        elif name == "gradient":
            h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in self.brush))
            for led, (u, vv, _) in pos.items():
                r, g, b = colorsys.hsv_to_rgb(h + u * 0.25, s, v)
                self.colors[led] = (int(r * 255), int(g * 255), int(b * 255))
        elif name == "gaming":
            self.colors.clear()
            for k in layout.KEYS:
                self.colors[k.led] = (20, 0, 40)
            for n in ("w", "a", "s", "d"):
                self.colors[layout.KEYS_BY_NAME[n].led] = (255, 40, 0)
            for n in ("up", "down", "left", "right"):
                self.colors[layout.KEYS_BY_NAME[n].led] = (0, 160, 255)
            for n in ("esc", "space", "lshift", "lctrl", "tab", "q", "e", "r", "f"):
                self.colors[layout.KEYS_BY_NAME[n].led] = (255, 180, 0)
        self.view.queue_draw()
        self._sync_buttons()

    # keyboard I/O
    def _frame(self):
        b = 0.18 + 0.82 * (int(self.bright.get_value()) - 1) / 4
        return {led: tuple(int(c * b) for c in rgb) for led, rgb in list(self.colors.items())}

    def _live_toggled(self, row, _):
        if row.get_active():
            def on_error(e):
                GLib.idle_add(self._live_failed, str(e))

            def job(kb):
                return FrameStreamer(kb, self._frame, fps=15, on_error=on_error).start()

            def started(streamer):
                self.win.set_live("preview", streamer, on_stop=lambda: self.live_row.set_active(False))
            self.win.stop_live(restore=False)
            self.win.worker.submit(job, done=started)
        elif self.win.live_kind == "preview":
            self.win.stop_live(restore=True)

    def _live_failed(self, msg):
        self.win.stop_live(restore=False)
        self.live_row.set_active(False)
        self.win.toast(f"Live preview stopped: {msg}")

    def save(self):
        colors = dict(self.colors)
        b = int(self.bright.get_value())
        self.win.stop_live(restore=False)

        def done(_):
            state.remember_custom(colors, b)
            self.win.lighting.refresh_from_state()
            self.win.sync_lights_ui()
            self.win.toast("Per-key colours saved to the keyboard")
        self.win.worker.submit(lambda kb: kb.set_custom_colors(colors, brightness=b), done=done)


# ---------------------------------------------------------------------------
class MusicPage:
    def __init__(self, win):
        from .. import music
        self.music = music
        self.win = win
        self.vis = None
        self.demo = music.DemoAnalyzer()
        self.renderer = music.Renderer("spectrum")

        self.view = KeyboardView(legends=False)
        self.view.set_animator(self._frame)
        card = _board_card(self.view, "Demo preview, start to react to your audio")
        self.caption = card.caption

        # hero controls
        self.play = Gtk.Button(icon_name="media-playback-start-symbolic", valign=Gtk.Align.CENTER,
                               tooltip_text="Start music sync")
        self.play.add_css_class("hero-button")
        self.play.add_css_class("suggested-action")
        self.play.connect("clicked", lambda *a: self.toggle())
        self.title = Gtk.Label(label="Music sync is off", xalign=0)
        self.title.add_css_class("hero-title")
        self.subtitle = Gtk.Label(label="Lights follow whatever plays on your default audio output. "
                                        "Keeps running from the tray when the window is closed.", xalign=0, wrap=True)
        self.subtitle.add_css_class("dim-label")
        self.level = Gtk.LevelBar(min_value=0, max_value=1, valign=Gtk.Align.CENTER)
        self.level.set_size_request(-1, 8)
        self.level.add_css_class("battery")
        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.CENTER,
                      hexpand=True)
        txt.append(self.title)
        txt.append(self.subtitle)
        txt.append(self.level)
        hero = Gtk.Box(spacing=20)
        hero.add_css_class("card")
        hero.add_css_class("toolbar-card")
        hero.append(self.play)
        hero.append(txt)

        opts = Adw.PreferencesGroup(title="Appearance")
        self.style = Adw.ToggleGroup(valign=Gtk.Align.CENTER)
        for name, label, icon in (("spectrum", "Spectrum", "view-continuous-symbolic"),
                                  ("pulse", "Pulse", "media-record-symbolic"),
                                  ("wave", "Wave", "network-wireless-symbolic")):
            self.style.add(Adw.Toggle(name=name, label=label, icon_name=icon))
        self.style.set_active_name("spectrum")
        self.style.connect("notify::active-name", self._style_changed)
        r = Adw.ActionRow(title="Style")
        r.add_suffix(self.style)
        opts.add(r)

        self.rainbow = Adw.SwitchRow(title="Rainbow colours", active=True)
        self.rainbow.connect("notify::active", self._color_changed)
        opts.add(self.rainbow)
        self.color_btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False),
                                               valign=Gtk.Align.CENTER)
        rgba = Gdk.RGBA()
        rgba.parse("#00a0ff")
        self.color_btn.set_rgba(rgba)
        self.color_btn.connect("notify::rgba", self._color_changed)
        self.color_row = Adw.ActionRow(title="Colour", sensitive=False)
        self.color_row.add_suffix(self.color_btn)
        opts.add(self.color_row)
        self.sens = ValueSlider(0.5, 2.0, 0.1, 1.0, fmt="{:.1f}×", marks=False)
        self.sens.connect("changed", self._sens_changed)
        r = Adw.ActionRow(title="Sensitivity", subtitle="Higher reacts to quieter sounds")
        r.add_suffix(self.sens)
        opts.add(r)

        self.widget, _ = _page_scroller(card, hero, opts)

    def _color(self):
        if self.rainbow.get_active():
            return None
        c = self.color_btn.get_rgba()
        return (round(c.red * 255), round(c.green * 255), round(c.blue * 255))

    def _frame(self, t):
        if self.vis and self.vis.running:
            an = self.vis.analyzer
            self.level.set_value(min(1.0, an.energy * 1.4) if an else 0)
            return self.vis.last_frame
        self.demo.update(t)
        self.level.set_value(0)
        return {k: tuple(int(c * 0.7) for c in v) for k, v in self.renderer.frame(self.demo).items()}

    def toggle(self):
        if self.vis:
            self.win.stop_live(restore=True)
            return
        style = self.style.get_active_name()

        def on_error(e):
            GLib.idle_add(self._failed, str(e))

        def job(kb):
            vis = self.music.Visualizer(kb, style=style, color=self._color(),
                                        sensitivity=self.sens.get_value(), on_error=on_error)
            vis.start()
            return vis

        def started(vis):
            self.vis = vis
            self.win.set_live("music", vis, on_stop=self._stopped)
            self.play.set_icon_name("media-playback-stop-symbolic")
            self.play.remove_css_class("suggested-action")
            self.play.add_css_class("destructive-action")
            self.play.set_tooltip_text("Stop music sync")
            self.title.set_label("Music sync is on")
            self.caption.set_label("Live: this is what your keyboard shows")
        self.win.stop_live(restore=False)
        self.win.worker.submit(job, done=started)

    def _stopped(self):
        self.vis = None
        self.play.set_icon_name("media-playback-start-symbolic")
        self.play.remove_css_class("destructive-action")
        self.play.add_css_class("suggested-action")
        self.play.set_tooltip_text("Start music sync")
        self.title.set_label("Music sync is off")
        self.caption.set_label("Demo preview, start to react to your audio")

    def _failed(self, msg):
        self.win.stop_live(restore=False)
        self.win.toast(f"Music sync stopped: {msg}")

    def _style_changed(self, *a):
        name = self.style.get_active_name()
        self.renderer.style = name
        if self.vis:
            self.vis.set_style(name)

    def _color_changed(self, *a):
        self.color_row.set_sensitive(not self.rainbow.get_active())
        self.renderer.color = self._color()
        if self.vis:
            self.vis.set_color(self._color())

    def _sens_changed(self, *a):
        if self.vis and self.vis.analyzer:
            self.vis.analyzer.sensitivity = self.sens.get_value()


# ---------------------------------------------------------------------------
def _pretty(name: str) -> str:
    special = {"lbracket": "[", "rbracket": "]", "backslash": "\\", "semicolon": ";", "quote": "'",
               "grave": "`", "comma": ",", "period": ".", "slash": "/", "minus": "-", "equal": "=",
               "capslock": "Caps", "backspace": "Bksp", "printscreen": "PrtSc",
               "scrolllock": "ScrLk", "pgup": "PgUp", "pgdn": "PgDn"}
    if name in special:
        return special[name]
    return name.upper() if len(name) <= 3 else name.capitalize()


class KeymapPage:
    def __init__(self, win):
        self.win = win
        self.names = {v: k for k, v in P.HID_NAMES.items()}
        self.current = None

        self.layer = Adw.ToggleGroup(valign=Gtk.Align.CENTER)
        self.layer.add(Adw.Toggle(name="base", label="Base layer"))
        self.layer.add(Adw.Toggle(name="fn", label="Fn layer"))
        self.layer.set_active_name("base")
        self.layer.connect("notify::active-name", lambda *a: self._refresh())

        self.view = KeyboardView(interactive=True)
        self.view.on_press = self._press
        card = _board_card(self.view, "Click a key to remap it")

        head = Gtk.Box(spacing=12)
        head.append(self.layer)
        head.append(Gtk.Box(hexpand=True))
        head.append(experimental_tag())
        reset_all = Gtk.Button(label="Reset All", valign=Gtk.Align.CENTER)
        reset_all.add_css_class("destructive-action")
        reset_all.connect("clicked", self._reset_all)
        head.append(reset_all)

        info = Gtk.Label(
            label="Remaps are stored on the keyboard and work everywhere, including other computers. "
                  "Only single keys can be stored; for shortcuts or app launching use your "
                  "desktop's keyboard settings.", wrap=True, xalign=0)
        info.add_css_class("dim-label")
        info.add_css_class("caption")

        # popover
        self.pop = Gtk.Popover(has_arrow=True)
        self.pop.set_parent(self.view)
        self.pop.connect("closed", self._pop_closed)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=6,
                      margin_bottom=6, margin_start=6, margin_end=6)
        self.pop_title = Gtk.Label(xalign=0)
        self.pop_title.add_css_class("heading")
        self.search = Gtk.SearchEntry(placeholder_text="Search keys…")
        self.search.connect("search-changed", lambda *a: self.list.invalidate_filter())
        self.search.connect("activate", self._activate_first)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("navigation-sidebar")
        for name, code in sorted(P.HID_NAMES.items(), key=lambda kv: kv[1]):
            row = Gtk.ListBoxRow()
            row.code, row.key = code, name
            hb = Gtk.Box(spacing=8, margin_start=4, margin_end=4)
            hb.append(Gtk.Label(label=_pretty(name), xalign=0, hexpand=True))
            hint = Gtk.Label(label=f"0x{code:02X}")
            hint.add_css_class("dim-label")
            hint.add_css_class("caption")
            hb.append(hint)
            row.set_child(hb)
            self.list.append(row)
        self.list.set_filter_func(lambda r: self.search.get_text().lower() in r.key)
        self.list.connect("row-activated", lambda lb, row: self._assign(row.code))
        sc = Gtk.ScrolledWindow(child=self.list, min_content_height=260, max_content_height=260,
                                hscrollbar_policy=Gtk.PolicyType.NEVER)
        sc.set_size_request(220, -1)
        self.default_btn = Gtk.Button(label="Restore Default")
        self.default_btn.connect("clicked", lambda *a: self._assign(0))
        box.append(self.pop_title)
        box.append(self.search)
        box.append(sc)
        box.append(self.default_btn)
        self.pop.set_child(box)

        self.widget, _ = _page_scroller(head, card, info)
        self._refresh()

    def _layer(self):
        return P.LAYER_FN if self.layer.get_active_name() == "fn" else P.LAYER_BASE

    def _remaps(self):
        km = state.load().get("keymap", {})
        prefix = f"{self._layer()}:"
        return {k[len(prefix):]: v for k, v in km.items() if k.startswith(prefix)}

    def _refresh(self):
        rm = self._remaps()
        self.view.badges = {}
        for name, code in rm.items():
            k = layout.KEYS_BY_NAME.get(name)
            if k:
                self.view.badges[k.led] = _pretty(self.names.get(code, f"{code:02x}"))
        self.view.colors = {k.led: (0, 90, 160) for k in layout.KEYS if k.led in self.view.badges}
        self.view.queue_draw()

    def _press(self, key, button, x, y):
        if key.code == 0xAF:
            self.win.toast("The Fn key can't be remapped")
            return
        self.current = key
        self.view.selected = {key.led}
        self.view.queue_draw()
        layer = "Fn + " if self._layer() == P.LAYER_FN else ""
        self.pop_title.set_label(f"Remap {layer}{key.label}")
        self.default_btn.set_sensitive(layout.key_name(key.code) in self._remaps())
        self.search.set_text("")
        self.pop.set_pointing_to(self.view.key_rect(key))
        self.pop.popup()
        self.search.grab_focus()

    def _pop_closed(self, *a):
        self.view.selected = set()
        self.view.queue_draw()

    def _activate_first(self, *a):
        row = self.list.get_first_child()
        while row and not (row.get_visible() and row.get_child_visible()
                           and self.search.get_text().lower() in row.key):
            row = row.get_next_sibling()
        if row:
            self._assign(row.code)

    def _assign(self, target):
        key, layer = self.current, self._layer()
        self.pop.popdown()
        if key is None:
            return

        def done(_):
            d = state.load()
            km = d.setdefault("keymap", {})
            slot = f"{layer}:{layout.key_name(key.code)}"
            if target:
                km[slot] = target
            else:
                km.pop(slot, None)
            state.save(d)
            self._refresh()
            what = _pretty(self.names.get(target, "")) if target else "default"
            self.win.toast(f"{key.label} → {what}")
        self.win.worker.submit(lambda kb: kb.set_key(layer, key.code, target), done=done)

    def _reset_all(self, *a):
        rm = self._remaps()
        layer = self._layer()
        if not rm:
            self.win.toast("No remaps on this layer")
            return

        def job(kb):
            for name in rm:
                k = layout.KEYS_BY_NAME.get(name)
                if k:
                    kb.set_key(layer, k.code, 0)

        def done(_):
            d = state.load()
            d["keymap"] = {k: v for k, v in d.get("keymap", {}).items()
                           if not k.startswith(f"{layer}:")}
            state.save(d)
            self._refresh()
            self.win.toast(f"Restored {len(rm)} key(s)")
        self.win.worker.submit(job, done=done)


# ---------------------------------------------------------------------------
class SettingsPage:
    def __init__(self, win):
        self.win = win
        saved = state.load().get("settings", {})
        page = Adw.PreferencesPage()

        g = Adw.PreferencesGroup(title="Power &amp; input",
                                 description="The keyboard can't report these back, so the values "
                                             "shown are the last ones sent from this computer.")
        self.sleep = Adw.ComboRow(title="Sleep after", subtitle="Turn off lights and radio when idle",
                                  model=Gtk.StringList.new(["5 minutes", "15 minutes", "30 minutes",
                                                            "Never"]))
        self.sleep.add_prefix(Gtk.Image(icon_name="weather-clear-night-symbolic"))
        if saved.get("sleep_time") in P.SLEEP_TIMES:
            self.sleep.set_selected(P.SLEEP_TIMES.index(saved["sleep_time"]))
        self.sleep.connect("notify::selected", self._sleep)
        g.add(self.sleep)
        self.resp = Adw.ComboRow(title="Key response time",
                                 subtitle="Gear 1 is fastest (wired ≈2–3 ms, 2.4 GHz ≈5–6 ms)",
                                 model=Gtk.StringList.new(["Gear 1", "Gear 2", "Gear 3"]))
        self.resp.add_prefix(Gtk.Image(icon_name="preferences-system-time-symbolic"))
        if saved.get("response_time") in P.RESPONSE_TIMES:
            self.resp.set_selected(P.RESPONSE_TIMES.index(saved["response_time"]))
        self.resp.connect("notify::selected", self._resp)
        g.add(self.resp)
        self.fn = Adw.SwitchRow(title="Fn switch", subtitle="Swap the F-row default (no visible effect "
                                                             "observed on this firmware)")
        self.fn.add_suffix(experimental_tag())
        self.fn.set_active(bool(saved.get("fn_switch", False)))
        self.fn.connect("notify::active", self._fn)
        g.add(self.fn)
        page.add(g)

        d = Adw.PreferencesGroup(title="Device")
        self.rows = {}
        for key, title in (("model", "Model"), ("connection", "Connection"),
                           ("battery", "Battery"), ("firmware", "Firmware"),
                           ("node", "Interface")):
            r = Adw.ActionRow(title=title, subtitle="—")
            r.add_css_class("property")
            d.add(r)
            self.rows[key] = r
        page.add(d)

        from .. import desktop
        from . import app_prefs, set_app_pref
        prefs = app_prefs()
        ag = Adw.PreferencesGroup(title="App")
        self.theme = Adw.ToggleGroup(valign=Gtk.Align.CENTER)
        for name, label, icon in (("system", "System", "emblem-system-symbolic"),
                                  ("light", "Light", "weather-clear-symbolic"),
                                  ("dark", "Dark", "weather-clear-night-symbolic")):
            self.theme.add(Adw.Toggle(name=name, label=label, icon_name=icon))
        self.theme.set_active_name(prefs["theme"])
        self.theme.connect("notify::active-name",
                           lambda g, _: win.get_application().set_theme(g.get_active_name()))
        theme_row = Adw.ActionRow(title="Appearance")
        theme_row.add_prefix(Gtk.Image(icon_name="applications-graphics-symbolic"))
        theme_row.add_suffix(self.theme)
        ag.add(theme_row)
        self.autostart = Adw.SwitchRow(title="Launch at login",
                                       subtitle="Start quietly in the system tray")
        self.autostart.add_prefix(Gtk.Image(icon_name="system-run-symbolic"))
        self.autostart.set_active(desktop.autostart_enabled())
        self.autostart.connect("notify::active", self._autostart)
        ag.add(self.autostart)
        self.tray_row = Adw.SwitchRow(title="Keep running in the tray",
                                      subtitle="Closing the window hides it; quit from the tray menu")
        self.tray_row.add_prefix(Gtk.Image(icon_name="window-minimize-symbolic"))
        self.tray_row.set_active(prefs["close_to_tray"])
        self.tray_row.connect("notify::active", lambda r, _: set_app_pref("close_to_tray", r.get_active()))
        ag.add(self.tray_row)
        self.music_row = Adw.SwitchRow(title="Start music sync on login",
                                       subtitle="When launched at login, begin music sync automatically")
        self.music_row.add_prefix(Gtk.Image(icon_name="audio-x-generic-symbolic"))
        self.music_row.set_active(prefs["music_on_launch"])
        self.music_row.connect("notify::active", lambda r, _: set_app_pref("music_on_launch", r.get_active()))
        ag.add(self.music_row)
        page.add(ag)

        a = Adw.PreferencesGroup()
        about = Adw.ButtonRow(title="About ajazzctl", end_icon_name="go-next-symbolic")
        about.connect("activated", lambda *x: win.show_about())
        a.add(about)
        page.add(a)
        self.widget = page

    def update_device(self, node, status):
        if node is None:
            for r in self.rows.values():
                r.set_subtitle("—")
            self.rows["connection"].set_subtitle("Not connected")
            return
        self.rows["model"].set_subtitle("AJAZZ AK820 Max Plus")
        self.rows["connection"].set_subtitle(
            {"wired": "USB cable", "2.4GHz": "2.4 GHz receiver"}.get(node.connection, node.connection))
        self.rows["node"].set_subtitle(f"{node.devnode} · {node.vid:04x}:{node.pid:04x}")
        try:
            bcd = (Path(node.sys_path).parents[3] / "bcdDevice").read_text().strip()
            self.rows["firmware"].set_subtitle(f"0x{bcd}")
        except OSError:
            pass
        if status is not None:
            self.rows["battery"].set_subtitle(
                f"{status.battery}% · {status.power_state_name}" if status.battery is not None
                else status.power_state_name)

    def _autostart(self, row, _):
        from .. import desktop
        try:
            desktop.set_autostart(row.get_active())
        except OSError as e:
            self.win.toast(f"Couldn't change autostart: {e}")

    def _sleep(self, row, _):
        i = row.get_selected()
        self.win.worker.submit(lambda kb: kb.set_sleep_time(i),
                               done=lambda _: state.remember("sleep_time", P.SLEEP_TIMES[i]))

    def _resp(self, row, _):
        i = row.get_selected()
        self.win.worker.submit(lambda kb: kb.set_response_time(i),
                               done=lambda _: state.remember("response_time", P.RESPONSE_TIMES[i]))

    def _fn(self, row, _):
        on = row.get_active()
        self.win.worker.submit(lambda kb: kb.set_fn_switch(on),
                               done=lambda _: state.remember("fn_switch", on))


# ---------------------------------------------------------------------------
class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="AJAZZ Keyboard", icon_name="io.github.ajazzctl")
        self.set_default_size(1100, 760)
        self.set_size_request(380, 500)
        self.node = None
        self.status = None
        self.live = None
        self.live_kind = None
        self._live_on_stop = None
        self.on_live_changed = None

        self.worker = DeviceWorker(self._on_connected, self._on_error)

        # pages
        self.lighting = LightingPage(self)
        self.perkey = PerKeyPage(self)
        self.music = MusicPage(self)
        self.keymap = KeymapPage(self)
        self.settings_page = SettingsPage(self)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                               transition_duration=150)
        for (name, title, _), page in zip(PAGES, (self.lighting, self.perkey, self.music,
                                                   self.keymap, self.settings_page)):
            self.stack.add_titled(page.widget, name, title)

        # content
        self.content_title = Adw.WindowTitle(title="Lighting")
        content_header = Adw.HeaderBar(title_widget=self.content_title)
        self.banner = Adw.Banner(title="Looking for your keyboard…", button_label="Retry",
                                 revealed=True)
        self.banner.connect("button-clicked", lambda *a: self._poll_status())
        ctv = Adw.ToolbarView(content=self.stack)
        ctv.add_top_bar(content_header)
        ctv.add_top_bar(self.banner)
        content = Adw.NavigationPage(child=ctv, title="Lighting", tag="content")

        # sidebar
        side_header = Adw.HeaderBar(title_widget=Adw.WindowTitle(title="AJAZZ"))
        menu = Gio.Menu()
        themes = Gio.Menu()
        themes.append("Follow System", "app.theme::system")
        themes.append("Light", "app.theme::light")
        themes.append("Dark", "app.theme::dark")
        menu.append_section("Appearance", themes)
        rest = Gio.Menu()
        rest.append("About ajazzctl", "win.about")
        rest.append("Quit", "app.quit")
        menu.append_section(None, rest)
        side_header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                            tooltip_text="Main menu", primary=True))
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", lambda *a: self.show_about())
        self.add_action(about)

        self.nav = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.nav.add_css_class("navigation-sidebar")
        for name, title, icon in PAGES:
            row = Gtk.ListBoxRow()
            row.page = name
            hb = Gtk.Box(spacing=12, margin_top=4, margin_bottom=4)
            hb.append(Gtk.Image(icon_name=icon))
            hb.append(Gtk.Label(label=title, xalign=0))
            row.set_child(hb)
            self.nav.append(row)
        self.nav.connect("row-selected", self._nav_selected)

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        side.append(self._device_card())
        side.append(self.nav)
        stv = Adw.ToolbarView(content=Gtk.ScrolledWindow(child=side,
                                                         hscrollbar_policy=Gtk.PolicyType.NEVER))
        stv.add_top_bar(side_header)
        sidebar = Adw.NavigationPage(child=stv, title="AJAZZ", tag="sidebar")

        self.split = Adw.NavigationSplitView(sidebar=sidebar, content=content,
                                             min_sidebar_width=230, max_sidebar_width=280)
        self.content_page = content
        self.toasts = Adw.ToastOverlay(child=self.split)
        self.set_content(self.toasts)

        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 760sp"))
        bp.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(bp)

        self.nav.select_row(self.nav.get_row_at_index(0))
        self.set_focus(self.nav.get_row_at_index(0))
        self.connect("close-request", self._on_close)
        self._install_shortcuts()
        app.theme_action.connect("notify::state", lambda a, _: self.settings_page.theme.set_active_name(
            a.get_state().get_string()))
        self._poll_status()
        GLib.timeout_add_seconds(STATUS_INTERVAL_S, self._poll_status)

    # -- sidebar device card ---------------------------------------------------
    def _device_card(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=10,
                       margin_end=10, margin_top=6, margin_bottom=6)
        card.add_css_class("card")
        card.add_css_class("device-card")
        top = Gtk.Box(spacing=10)
        icon = Gtk.Image(icon_name="io.github.ajazzctl", pixel_size=40)
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        t = Gtk.Label(label="AK820 Max Plus", xalign=0)
        t.add_css_class("title")
        conn = Gtk.Box(spacing=6)
        self.dot = Gtk.Box(valign=Gtk.Align.CENTER)
        self.dot.add_css_class("status-dot")
        self.conn_label = Gtk.Label(label="Searching…", xalign=0)
        self.conn_label.add_css_class("dim-label")
        self.conn_label.add_css_class("caption")
        conn.append(self.dot)
        conn.append(self.conn_label)
        names.append(t)
        names.append(conn)
        top.append(icon)
        top.append(names)
        self.power_btn = Gtk.ToggleButton(icon_name="system-shutdown-symbolic", valign=Gtk.Align.CENTER,
                                          tooltip_text="Keyboard lighting on/off",
                                          active=not state.lights_off())
        self.power_btn.add_css_class("circular")
        self.power_btn.add_css_class("power-button")
        self.power_btn.connect("toggled", lambda b: self.set_lights(b.get_active()))
        top.append(self.power_btn)
        card.append(top)
        bat = Gtk.Box(spacing=8)
        self.batt_bar = Gtk.LevelBar(min_value=0, max_value=100, hexpand=True,
                                     valign=Gtk.Align.CENTER)
        self.batt_bar.add_css_class("battery")
        self.batt_bar.add_offset_value("low", 20)
        self.batt_bar.add_offset_value("high", 50)
        self.batt_label = Gtk.Label(label="—")
        self.batt_label.add_css_class("caption")
        self.batt_label.add_css_class("value-label")
        bat.append(self.batt_bar)
        bat.append(self.batt_label)
        card.append(bat)
        return card

    def _nav_selected(self, lb, row):
        if row is None:
            return
        self.stack.set_visible_child_name(row.page)
        title = dict((n, t) for n, t, _ in PAGES)[row.page]
        self.content_title.set_title(title)
        self.content_page.set_title(title)
        self.split.set_show_content(True)

    def _install_shortcuts(self):
        ctl = Gtk.ShortcutController(scope=Gtk.ShortcutScope.GLOBAL)
        for i in range(len(PAGES)):
            ctl.add_shortcut(Gtk.Shortcut(
                trigger=Gtk.ShortcutTrigger.parse_string(f"<Control>{i + 1}"),
                action=Gtk.CallbackAction.new(
                    lambda *a, i=i: self.nav.select_row(self.nav.get_row_at_index(i)) or True)))
        for trig, fn in (("<Control>z", self.perkey.undo), ("<Control><Shift>z", self.perkey.redo)):
            ctl.add_shortcut(Gtk.Shortcut(
                trigger=Gtk.ShortcutTrigger.parse_string(trig),
                action=Gtk.CallbackAction.new(
                    lambda *a, fn=fn: (fn() if self.stack.get_visible_child_name() == "perkey"
                                       else None) or True)))
        self.add_controller(ctl)

    # -- lights on/off ----------------------------------------------------------
    def set_lights(self, on: bool):
        if getattr(self, "_syncing", False) or on == (not state.lights_off()):
            return
        from .. import lights
        self.stop_live(restore=False)
        self.worker.submit(lights.turn_on if on else lights.turn_off,
                           done=lambda _: (self.sync_lights_ui(),
                                           self.toast("Lights on" if on else "Lights off")))
        # if the device is unreachable, snap the switches back
        GLib.timeout_add(1500, lambda: (self.sync_lights_ui(), False)[-1])

    def sync_lights_ui(self):
        on = not state.lights_off()
        self._syncing = True
        try:
            self.lighting.power_row.set_active(on)
            self.power_btn.set_active(on)
        finally:
            self._syncing = False
        if self.on_live_changed:       # refresh tray menu checkmarks
            self.on_live_changed()

    # -- live streams ------------------------------------------------------------
    def set_live(self, kind, obj, on_stop=None):
        self.live, self.live_kind, self._live_on_stop = obj, kind, on_stop
        if self.on_live_changed:
            self.on_live_changed()

    def stop_live(self, restore=True):
        if not self.live:
            return
        obj, cb = self.live, self._live_on_stop
        self.live = self.live_kind = self._live_on_stop = None

        def job(kb):
            obj.stop()
            if restore:
                restore_lighting(kb)
        self.worker.submit(job)
        if cb:
            cb()
        if self.on_live_changed:
            self.on_live_changed()

    # -- device status -------------------------------------------------------------
    def _poll_status(self):
        self.worker.submit(lambda kb: kb.status(), done=self._on_status, quiet=True)
        return GLib.SOURCE_CONTINUE

    def _on_connected(self, node):
        self.node = node
        if node is None:
            self.stop_live(restore=False)
            self.dot.remove_css_class("online")
            self.conn_label.set_label("Disconnected")
            self.banner.set_title("Keyboard not connected. Plug it in or switch it on.")
            self.banner.set_revealed(True)
            self.batt_label.set_label("—")
            self.batt_bar.set_value(0)
        else:
            self.dot.add_css_class("online")
            self.conn_label.set_label({"wired": "USB cable", "2.4GHz": "2.4 GHz wireless"}
                                      .get(node.connection, node.connection))
            self.banner.set_revealed(False)
        self.settings_page.update_device(node, self.status)

    def _on_status(self, st):
        self.status = st
        if st.battery is not None and st.power_state:
            self.batt_bar.set_value(st.battery)
            self.batt_label.set_label(f"{st.battery}%" + (" ⚡" if st.charging else ""))
            self.batt_bar.set_tooltip_text(f"Battery {st.battery}%, {st.power_state_name}")
        else:
            self.batt_label.set_label("—")
        self.settings_page.update_device(self.node, st)

    def _on_error(self, msg):
        if self.node is None:
            self.banner.set_title(msg)
            self.banner.set_revealed(True)
        else:
            self.toast(msg)

    def toast(self, msg):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(msg), timeout=3))

    def show_about(self):
        about = Adw.AboutDialog(
            application_name="AJAZZ Keyboard", application_icon="io.github.ajazzctl",
            developer_name="ajazzctl contributors", version=__version__,
            comments="Unofficial Linux configuration tool for the AJAZZ AK820 Max Plus. "
                     "Protocol reverse-engineered from the vendor software.",
            website="https://github.com/prasoondev/ajazz-linux",
            issue_url="https://github.com/prasoondev/ajazz-linux/issues",
            license_type=Gtk.License.MIT_X11)
        about.present(self)

    def _on_close(self, *a):
        from . import app_prefs
        app = self.get_application()
        if app.tray_active() and app_prefs()["close_to_tray"]:
            self.set_visible(False)
            app.notify_still_running()
            return True          # keep running in the tray
        self.shutdown()
        app.quit_app() if app.tray else None
        return False

    def on_ready_hidden(self):
        """Started via autostart (--hidden): no window, optionally resume music."""
        from . import app_prefs
        if app_prefs()["music_on_launch"]:
            GLib.timeout_add_seconds(2, lambda: (self.music.toggle() if not self.live else None,
                                                 False)[-1])

    def shutdown(self):
        """Stop live streams and put the stored lighting back (used on quit)."""
        if self.live:
            obj = self.live
            self.live = self.live_kind = None
            try:
                obj.stop()
                if self.worker.kb:
                    restore_lighting(self.worker.kb)
            except DeviceError:
                pass
