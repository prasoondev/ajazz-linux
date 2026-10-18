"""Approximate on-screen previews of the keyboard's built-in effects.

These are hand-written imitations of what the firmware draws. They are used
only for the GUI, never sent to the keyboard.
"""
from __future__ import annotations

import colorsys
import math

from . import layout
from . import protocol as P

# normalised key centres (u: 0 left .. 1 right, v: 0 top .. 1 bottom)
_xs = [k.rect[0] + k.rect[2] / 2 for k in layout.KEYS]
_ys = [k.rect[1] + k.rect[3] / 2 for k in layout.KEYS]
_X0, _X1, _Y0, _Y1 = min(_xs), max(_xs), min(_ys), max(_ys)
POS = {k.led: ((x - _X0) / (_X1 - _X0), (y - _Y0) / (_Y1 - _Y0), k.row)
       for k, x, y in zip(layout.KEYS, _xs, _ys)}


def _rand(led: int, salt: int = 0) -> float:
    """Deterministic pseudo-random 0..1 per key."""
    h = (led * 2654435761 + salt * 40503) & 0xFFFFFFFF
    h ^= h >> 15
    h = (h * 2246822519) & 0xFFFFFFFF
    h ^= h >> 13
    return (h & 0xFFFF) / 0xFFFF


def _hue(h: float) -> tuple[float, float, float]:
    return colorsys.hsv_to_rgb(h % 1.0, 1.0, 1.0)


def _clamp(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def brightness_scale(level: int) -> float:
    return 0.18 + 0.82 * (level - 1) / 4


def frame(s: P.LightSettings, t: float,
          custom: dict[int, tuple[int, int, int]] | None = None) -> dict[int, tuple[int, int, int]]:
    """Colours for every key at time t (seconds) under settings s."""
    if s.mode == P.MODE_CUSTOM:
        b = brightness_scale(s.brightness)
        return {led: tuple(int(c * b) for c in rgb) for led, rgb in (custom or {}).items()}
    eff = P.EFFECTS_BY_MODE.get(s.mode)
    if eff is None:
        return {}
    sp = 0.25 + 0.3 * (s.speed - 1) if eff.has_speed else 0.5
    fixed = None
    if eff.has_color and s.color != P.COLOR_INDEX["rainbow"]:
        fixed = tuple(c / 255 for c in P.COLORS[s.color][1])
    left = eff.has_direction and s.direction == P.DIRECTION_LEFT
    bscale = brightness_scale(s.brightness) if eff.has_brightness else 1.0
    m = s.mode
    out = {}
    for led, (u, v, row) in POS.items():
        uu = 1 - u if left else u
        hue = None          # rainbow hue if colour not fixed
        k = 1.0             # intensity
        if m == 1:          # left/right ripples
            k = (0.5 + 0.5 * math.sin(2 * math.pi * (uu * 1.6 - t * sp))) ** 2
            hue = u * 0.8 + t * 0.05
        elif m == 2:        # starry dots
            k = max(0.0, math.sin(2 * math.pi * (t * sp * 0.6 + _rand(led)))) ** 10
            hue = _rand(led, 1)
        elif m == 3:        # up/down ripples
            vv = 1 - v if left else v
            k = (0.5 + 0.5 * math.sin(2 * math.pi * (vv * 1.4 - t * sp))) ** 2
            hue = v * 0.8 + t * 0.05
        elif m == 4:        # bidirectional ejection
            d = abs(u - 0.5) * 2
            k = (0.5 + 0.5 * math.sin(2 * math.pi * (d * 1.5 - t * sp))) ** 2
            hue = d * 0.7 + t * 0.05
        elif m == 5:        # spectral cycle
            hue = t * sp * 0.15
        elif m == 6:        # kaleidoscope
            a = math.atan2((v - 0.5) * 0.4, u - 0.5) / (2 * math.pi)
            hue = a + math.hypot(u - 0.5, v - 0.5) - t * sp * 0.25
            k = 0.6 + 0.4 * math.sin(2 * math.pi * (a * 3 + t * sp * 0.5))
        elif m == 7:        # static
            hue = u * 0.85
        elif m == 8:        # breathing
            k = 0.5 - 0.5 * math.cos(2 * math.pi * t * sp * 0.4)
            hue = t * 0.03
        elif m == 9:        # cross
            p = (t * sp * 0.5) % 1.0
            k = max(_clamp(1 - abs(uu - p) * 7), _clamp(1 - abs(v - p) * 5))
            hue = p + u * 0.3
        elif m == 11:       # single key breathing
            k = (0.5 - 0.5 * math.cos(2 * math.pi * (t * sp * 0.4 + _rand(led)))) ** 2
            hue = _rand(led, 2)
        elif m == 12:       # picture scroll
            hue = uu * 0.7 + v * 0.3 - t * sp * 0.25
            if fixed:
                k = 0.5 + 0.5 * math.sin(2 * math.pi * (uu + v * 0.5 - t * sp * 0.5))
        elif m == 15:       # top three, bottom three
            ph = 0.5 + 0.5 * math.sin(2 * math.pi * t * sp * 0.4)
            k = ph if row < 3 else 1 - ph
            hue = 0.0 if row < 3 else 0.6
        elif m == 16:       # rain
            col = round(u * 15)
            pos = (t * sp * 0.6 + _rand(col, 3)) % 1.4 - 0.2
            k = _clamp(1 - (pos - v) * 3) * _clamp(1 + (pos - v) * 12) if v <= pos + 0.1 else 0
            hue = _rand(col, 4)
        elif m == 17:       # windmill
            a = math.atan2((v - 0.5) * 0.4, u - 0.5)
            k = (0.5 + 0.5 * math.cos(4 * a - t * sp * 3)) ** 3
            hue = a / (2 * math.pi) + t * 0.05
        elif m == 18:       # sine wave
            y = 0.5 + 0.4 * math.sin(2 * math.pi * (uu - t * sp * 0.4))
            k = _clamp(1 - abs(v - y) * 4)
            hue = uu
        elif m == 19:       # galloping horse
            p = (t * sp * 0.45) % 1.2 - 0.1
            k = _clamp(1 - abs(uu - p) * 6)
            hue = p
        rgb = fixed if fixed is not None else _hue(hue if hue is not None else u)
        f = _clamp(k) * bscale
        out[led] = (int(rgb[0] * 255 * f), int(rgb[1] * 255 * f), int(rgb[2] * 255 * f))
    return out
