"""GTK4 / libadwaita GUI for the AJAZZ AK820 Max Plus.

    ajazzctl-gui            open the window
    ajazzctl-gui --hidden   start in the tray only (used for autostart)

Single instance: launching again while running brings the window back.
"""
from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .. import desktop, state  # noqa: E402

APP_ID = desktop.APP_ID
THEMES = {"system": Adw.ColorScheme.DEFAULT, "light": Adw.ColorScheme.FORCE_LIGHT,
          "dark": Adw.ColorScheme.FORCE_DARK}
DATA = Path(__file__).resolve().parent.parent / "data"


def app_prefs() -> dict:
    p = state.load().get("app", {})
    return {"close_to_tray": p.get("close_to_tray", True),
            "music_on_launch": p.get("music_on_launch", False),
            "theme": p.get("theme", "system") if p.get("theme") in THEMES else "system"}


def set_app_pref(key, value):
    d = state.load()
    d.setdefault("app", {})[key] = value
    state.save(d)


class App(Adw.Application):
    def __init__(self, hidden=False):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.start_hidden = hidden
        self.win = None
        self.tray = None
        self._held = False
        self.set_accels_for_action("app.quit", ["<Control>q"])

    def do_startup(self):
        Adw.Application.do_startup(self)
        from .widgets import install_css
        Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(str(DATA))
        Gtk.Window.set_default_icon_name(APP_ID)
        install_css()
        try:
            desktop.ensure_user_integration()
        except OSError:
            pass
        for name, cb in (("quit", lambda *a: self.quit_app()), ("show", lambda *a: self.show_window())):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", cb)
            self.add_action(act)
        theme = app_prefs()["theme"]
        self.theme_action = Gio.SimpleAction.new_stateful(
            "theme", GLib.VariantType("s"), GLib.Variant("s", theme))
        self.theme_action.connect("change-state", self._theme_changed)
        self.add_action(self.theme_action)
        Adw.StyleManager.get_default().set_color_scheme(THEMES[theme])
        self._setup_tray()

    def _theme_changed(self, action, value):
        name = value.get_string()
        if name not in THEMES:
            return
        action.set_state(value)
        Adw.StyleManager.get_default().set_color_scheme(THEMES[name])
        set_app_pref("theme", name)

    def set_theme(self, name):
        self.theme_action.change_state(GLib.Variant("s", name))

    def _setup_tray(self):
        from .tray import MenuItem, TrayIcon
        if not TrayIcon.host_present():
            return
        try:
            self.tray = TrayIcon(
                APP_ID, "AJAZZ Keyboard", APP_ID, str(DATA), self.toggle_window, [
                    MenuItem("Open AJAZZ Keyboard", self.show_window),
                    MenuItem(separator=True),
                    MenuItem("Music sync", lambda: self.win and self.win.music.toggle(),
                             toggle=lambda: bool(self.win and self.win.live_kind == "music")),
                    MenuItem(separator=True),
                    MenuItem("Quit", self.quit_app),
                ])
            self.hold()          # keep running with no visible window
            self._held = True
        except GLib.Error as e:
            print(f"tray unavailable: {e.message}", file=sys.stderr)
            self.tray = None

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        hidden = "--hidden" in args
        if self.win is None:
            self._create_window()
            if hidden and self.tray:
                self.win.on_ready_hidden()
                return 0
        self.show_window()
        return 0

    def do_activate(self):
        if self.win is None:
            self._create_window()
        self.show_window()

    def _create_window(self):
        from .window import MainWindow
        self.win = MainWindow(self)
        if self.tray:
            self.win.on_live_changed = self.tray.refresh

    def show_window(self):
        if self.win is None:
            self._create_window()
        self.win.set_visible(True)
        self.win.present()

    def toggle_window(self):
        if self.win and self.win.get_visible() and self.win.is_active():
            self.win.set_visible(False)
        else:
            self.show_window()

    def tray_active(self) -> bool:
        return bool(self.tray and self.tray.available)

    def notify_still_running(self):
        d = state.load()
        if d.get("app", {}).get("told_tray"):
            return
        n = Gio.Notification.new("AJAZZ Keyboard is still running")
        n.set_body("It keeps running in the system tray. Right-click the tray icon and choose "
                   "Quit to exit.")
        self.send_notification("tray", n)
        set_app_pref("told_tray", True)

    def quit_app(self):
        if self.win:
            self.win.shutdown()
        if self.tray:
            self.tray.destroy()
        if self._held:
            self.release()
            self._held = False
        self.quit()


def main() -> int:
    return App().run(sys.argv)
