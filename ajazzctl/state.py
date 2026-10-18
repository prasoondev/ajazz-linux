"""Local record of the last settings this tool sent.

The keyboard protocol has no command to read lighting settings back, so this
file is the only way to show "current" values. It can be wrong if settings
were changed with Fn shortcuts on the keyboard itself.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from . import protocol as P


def state_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "ajazzctl" / "state.json"


def load() -> dict:
    try:
        return json.loads(state_path().read_text())
    except (OSError, ValueError):
        return {}


def save(data: dict) -> None:
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    tmp.replace(p)


def light_settings() -> P.LightSettings:
    d = load().get("lighting", {})
    s = P.LightSettings()
    for k in ("mode", "brightness", "speed", "direction", "color"):
        if isinstance(d.get(k), int):
            setattr(s, k, d[k])
    try:
        s.validate()
    except ValueError:
        s = P.LightSettings()
    return s


def remember_lighting(s: P.LightSettings) -> None:
    d = load()
    d["lighting"] = asdict(s)
    save(d)


def custom_colors() -> dict[int, tuple[int, int, int]]:
    raw = load().get("custom_colors", {})
    out = {}
    for k, v in raw.items():
        try:
            out[int(k)] = tuple(int(x) for x in v)[:3]
        except (TypeError, ValueError):
            continue
    return out


def remember_custom(colors: dict[int, tuple[int, int, int]], brightness: int) -> None:
    d = load()
    d["custom_colors"] = {str(k): list(v) for k, v in sorted(colors.items())}
    d["lighting"] = asdict(P.LightSettings(mode=P.MODE_CUSTOM, brightness=brightness))
    save(d)


def remember(key: str, value) -> None:
    d = load()
    d.setdefault("settings", {})[key] = value
    save(d)
