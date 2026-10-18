#!/usr/bin/env python3
"""Interactive hardware verification for ajazzctl.

Sends one known setting at a time, asks the operator what the keyboard shows,
and appends every step (packets sent + answer) to docs/hw-test-log.jsonl.
Only uses commands already established from the vendor software; never
touches firmware, key mapping or factory reset.

    python3 tools/hwtest.py [--device /dev/hidrawN] [--only brightness,color,...]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ajazzctl import layout  # noqa: E402
from ajazzctl import protocol as P  # noqa: E402
from ajazzctl.device import Keyboard  # noqa: E402

LOG = Path(__file__).resolve().parent.parent / "docs" / "hw-test-log.jsonl"


class Recorder:
    def __init__(self, kb: Keyboard, connection: str):
        self.kb = kb
        self.connection = connection
        self.sent: list[str] = []
        kb.log = lambda m: self.sent.append(m) if m.startswith(">>") else None
        LOG.parent.mkdir(exist_ok=True)

    def ask(self, test: str, question: str) -> str:
        ans = input(f"  ? {question}\n    > ").strip()
        with LOG.open("a") as f:
            f.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"),
                                "connection": self.connection, "test": test,
                                "packets": self.sent, "question": question,
                                "answer": ans}) + "\n")
        self.sent = []
        return ans

    def light(self, **kw):
        self.kb.set_lighting(P.LightSettings(**kw))


def t_brightness(r: Recorder):
    print("\n[brightness] static white, brightness 1 -> 5")
    for b in range(1, 6):
        r.light(mode=7, color=6, brightness=b)
        r.ask("brightness", f"Brightness {b}/5 sent. Is it off, dim, medium or bright?")


def t_color(r: Recorder):
    print("\n[color] static effect, each palette colour")
    for i, (name, _) in enumerate(P.COLORS):
        r.light(mode=7, color=i, brightness=5)
        r.ask("color", f"Colour index {i} sent (expected: {name}). What colour do you see?")


def t_speed(r: Recorder):
    print("\n[speed] breathing effect, slowest vs fastest setting")
    for s in (1, 5):
        r.light(mode=8, color=2, brightness=5, speed=s)
        time.sleep(4)
        r.ask("speed", f"Breathing (blue) with speed {s}/5. Roughly how many seconds per breath?")


def t_direction(r: Recorder):
    print("\n[direction] left/right ripple effect")
    for d, name in ((P.DIRECTION_LEFT, "left"), (P.DIRECTION_RIGHT, "right")):
        r.light(mode=1, color=7, brightness=5, speed=3, direction=d)
        time.sleep(3)
        r.ask("direction", f"Ripple with direction={name}. Which way does the light travel?")


def t_effects(r: Recorder):
    print("\n[effects] every effect for a few seconds each (rainbow colour where supported)")
    for e in P.EFFECTS:
        if e.mode == P.MODE_CUSTOM:
            continue
        r.light(mode=e.mode, color=7, brightness=5, speed=3)
        r.ask("effects", f"Mode {e.mode} '{e.name}'. Does it animate / match the name? (ok / describe)")


def t_custom(r: Recorder):
    print("\n[custom] per-key colours: Esc red, W/A/S/D green, arrows blue, everything else off")
    k = layout.KEYS_BY_NAME
    colors = {k["esc"].led: (255, 0, 0)}
    colors.update({k[n].led: (0, 255, 0) for n in "wasd"})
    colors.update({k[n].led: (0, 0, 255) for n in ("up", "down", "left", "right")})
    r.kb.set_custom_colors(colors, brightness=5)
    r.ask("custom", "Are exactly Esc=red, WASD=green, arrows=blue lit and all others off? "
                    "(ok / describe what differs)")
    rainbow = {key.led: (key.col * 15 % 256, 255 - key.col * 15 % 256, key.row * 50) for key in layout.KEYS}
    r.kb.set_custom_colors(rainbow, brightness=5)
    r.ask("custom", "Now every key should be lit in a left-to-right gradient. "
                    "Any keys dark or wrong colour? (ok / list keys)")


def t_fnswitch(r: Recorder):
    print("\n[fn-switch] NOTE: changes what the F-row does by default; it is reverted afterwards")
    for on in (True, False):
        r.kb.set_fn_switch(on)
        r.ask("fn-switch", f"Fn switch {'ON' if on else 'OFF'} sent. Press F1/F2/F10 (without Fn) "
                           "in a text field or desktop — do they act as F-keys or media/system keys?")


def t_status(r: Recorder):
    st = r.kb.status()
    print(f"\n[status] battery={st.battery} state={st.power_state} ({st.power_state_name})")
    r.ask("status", f"Keyboard reports battery {st.battery}% / '{st.power_state_name}'. "
                    "Does that match reality (cable plugged? charge LED?)")


TESTS = {"status": t_status, "brightness": t_brightness, "color": t_color, "speed": t_speed,
         "direction": t_direction, "effects": t_effects, "custom": t_custom,
         "fn-switch": t_fnswitch}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device")
    ap.add_argument("--only", help="comma-separated subset of: " + ",".join(TESTS))
    args = ap.parse_args()
    names = args.only.split(",") if args.only else list(TESTS)
    with Keyboard.open(args.device) as kb:
        print(f"Testing {kb.node.hid_name} via {kb.node.devnode} ({kb.node.connection}).")
        print("Answer each question in a few words; answers are saved to", LOG)
        r = Recorder(kb, kb.node.connection)
        for n in names:
            TESTS[n](r)
        print("\nDone. Leaving the keyboard on static red; change it with ajazzctl or the GUI.")
        r.light(mode=7, color=0, brightness=5)


if __name__ == "__main__":
    main()
