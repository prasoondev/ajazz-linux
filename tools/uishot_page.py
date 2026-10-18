"""Helper for tools/uishot.sh: open the GUI on one page, then quit after 12 s."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gi.repository import GLib  # noqa: E402

from ajazzctl import gui  # noqa: E402
from ajazzctl.gui import window  # noqa: E402

idx, W, H = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
theme = sys.argv[4] if len(sys.argv) > 4 else "dark"


class A(gui.App):
    def do_command_line(self, cl):
        self.set_theme(theme)
        w = window.MainWindow(self)
        self.win = w
        w.set_default_size(W, H)
        w.nav.select_row(w.nav.get_row_at_index(idx))
        w.present()
        GLib.timeout_add_seconds(12, self.quit)
        return 0


A().run([])
