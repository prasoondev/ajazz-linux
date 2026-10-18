"""Lights on/off and "re-apply what the user last chose".

The firmware has no dedicated off command (none was found in the vendor
software either), so "off" is per-key custom mode with every LED black. That
uses only hardware-verified packets and is stored on the keyboard. The user's
real settings and custom colours stay in the local state file, so "on"
restores them exactly.
"""
from __future__ import annotations

from . import protocol as P
from . import state


def apply_saved(kb) -> None:
    """Send the lighting the user last chose (or keep it off)."""
    if state.lights_off():
        kb.set_custom_colors({}, brightness=1)
        return
    s = state.light_settings()
    if s.mode == P.MODE_CUSTOM:
        kb.set_custom_colors(state.custom_colors(), brightness=s.brightness)
    else:
        kb.set_lighting(s)


def turn_off(kb) -> None:
    kb.set_custom_colors({}, brightness=1)
    state.set_lights_off(True)


def turn_on(kb) -> None:
    state.set_lights_off(False)
    apply_saved(kb)
