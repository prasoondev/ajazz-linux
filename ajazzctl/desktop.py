"""Desktop integration: launcher entry, icon, autostart.

On Wayland the compositor picks the taskbar icon by matching the window's app
id (io.github.ajazzctl) to a .desktop file, so one must exist even when
running from a source checkout. The Arch package installs system-wide copies;
these helpers write per-user ones only when no system copy exists.
"""
from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path

APP_ID = "io.github.ajazzctl"
PKG_DIR = Path(__file__).resolve().parent
ICON_SRC = PKG_DIR / "data" / f"{APP_ID}.svg"


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def _data_dirs() -> list[Path]:
    dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [Path(d) for d in dirs.split(":") if d]


def system_installed() -> bool:
    return any((d / "applications" / f"{APP_ID}.desktop").exists() for d in _data_dirs())


def launch_command(hidden: bool = False) -> str:
    """Command that starts the GUI, for the current installation."""
    exe = shutil.which("ajazzctl-gui")
    if exe and system_installed():
        cmd = [exe]
    else:  # source checkout
        cmd = ["env", f"PYTHONPATH={PKG_DIR.parent}", sys.executable, "-m", "ajazzctl.gui"]
    if hidden:
        cmd.append("--hidden")
    return " ".join(shlex.quote(c) for c in cmd)


def _entry(exec_cmd: str, autostart: bool = False) -> str:
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Name=AJAZZ Keyboard",
        "GenericName=Keyboard Lighting",
        "Comment=Configure the AJAZZ AK820 Max Plus (lighting, music sync, key remap)",
        f"Exec={exec_cmd}",
        f"Icon={APP_ID}",
        "Terminal=false",
        "Categories=Settings;HardwareSettings;",
        "Keywords=ajazz;ak820;rgb;keyboard;lighting;",
        "StartupNotify=false" if autostart else "StartupNotify=true",
        f"StartupWMClass={APP_ID}",
    ]
    if autostart:
        lines += ["X-GNOME-Autostart-enabled=true", "X-KDE-autostart-after=panel"]
    return "\n".join(lines) + "\n"


def ensure_user_integration() -> bool:
    """Install a per-user .desktop + icon if the app isn't installed system-wide.

    Returns True if anything was written. When the app *is* installed
    system-wide, per-user copies left by earlier source-checkout runs are
    removed so they don't shadow the packaged launcher.
    """
    if system_installed():
        changed = False
        for f in (_data_home() / "applications" / f"{APP_ID}.desktop",
                  _data_home() / "icons/hicolor/scalable/apps" / f"{APP_ID}.svg"):
            if f.exists() and (f.suffix == ".svg" or "PYTHONPATH=" in f.read_text()):
                f.unlink()
                changed = True
        a = autostart_path()
        if a.exists() and "PYTHONPATH=" in a.read_text():
            set_autostart(True)       # repoint autostart to the installed binary
            changed = True
        return changed
    changed = False
    icon_dst = _data_home() / "icons/hicolor/scalable/apps" / f"{APP_ID}.svg"
    if ICON_SRC.exists() and (not icon_dst.exists() or icon_dst.read_bytes() != ICON_SRC.read_bytes()):
        icon_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ICON_SRC, icon_dst)
        changed = True
    desk = _data_home() / "applications" / f"{APP_ID}.desktop"
    content = _entry(launch_command())
    if not desk.exists() or desk.read_text() != content:
        desk.parent.mkdir(parents=True, exist_ok=True)
        desk.write_text(content)
        changed = True
    return changed


def autostart_path() -> Path:
    return _config_home() / "autostart" / f"{APP_ID}.desktop"


def autostart_enabled() -> bool:
    return autostart_path().exists()


def set_autostart(enabled: bool) -> None:
    p = autostart_path()
    if enabled:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_entry(launch_command(hidden=True), autostart=True))
    elif p.exists():
        p.unlink()
