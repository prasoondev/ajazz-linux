"""ajazzctl — command-line control for the AJAZZ AK820 Max Plus."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from . import __version__, layout, state
from . import protocol as P
from .device import DeviceError, Keyboard, find_keyboards, related_nodes


def _out(args, data, text: str) -> None:
    print(json.dumps(data, indent=2) if args.json else text)


def _open(args) -> Keyboard:
    log = (lambda m: print(m, file=sys.stderr)) if args.verbose else None
    return Keyboard.open(args.device, log=log)


def cmd_detect(args) -> int:
    nodes = related_nodes()
    boards = find_keyboards()
    data = [{
        "hidraw": n.devnode, "vid": f"{n.vid:04x}", "pid": f"{n.pid:04x}", "bus": n.bus,
        "connection": n.connection, "name": n.hid_name, "interface": n.interface,
        "usage_page": f"{n.usage_page:04x}" if n.usage_page is not None else None,
        "usage": f"{n.usage:04x}" if n.usage is not None else None,
        "config_interface": n.is_config_interface,
    } for n in nodes]
    lines = []
    for d in data:
        tag = "  <- configuration interface" if d["config_interface"] else ""
        lines.append(f"{d['hidraw']:<13} {d['vid']}:{d['pid']} {d['connection']:<7} if{d['interface']} "
                     f"usage {d['usage_page']}:{d['usage']}  {d['name']}{tag}")
    if not nodes:
        lines.append("No AJAZZ (1a2c) HID devices found.")
    elif not boards:
        lines.append("AJAZZ devices found, but none expose the configuration interface.")
    _out(args, data, "\n".join(lines))
    return 0 if boards else 1


def cmd_info(args) -> int:
    with _open(args) as kb:
        st = kb.status()
        n = kb.node
        data = {"hidraw": n.devnode, "connection": n.connection, "name": n.hid_name,
                "vid": f"{n.vid:04x}", "pid": f"{n.pid:04x}",
                "battery_percent": st.battery, "power_state": st.power_state_name,
                "raw_status": st.raw.hex()}
        _out(args, data,
             f"Device:      {n.hid_name} ({n.vid:04x}:{n.pid:04x}, {n.connection}, {n.devnode})\n"
             f"Battery:     {st.battery if st.battery is not None else 'n/a'}%\n"
             f"Power state: {st.power_state_name}")
    return 0


def cmd_effects(args) -> int:
    data = [{"name": e.key, "mode": e.mode, "description": e.name,
             "brightness": e.has_brightness, "speed": e.has_speed,
             "direction": e.has_direction, "color": e.has_color} for e in P.EFFECTS]
    lines = [f"{'name':<14} {'mode':>4}  {'options':<32} description"]
    for d in data:
        opts = ",".join(k for k in ("brightness", "speed", "direction", "color") if d[k])
        lines.append(f"{d['name']:<14} {d['mode']:>4}  {opts:<32} {d['description']}")
    lines.append("\ncolours: " + ", ".join(n for n, _ in P.COLORS))
    _out(args, data, "\n".join(lines))
    return 0


def _describe(s: P.LightSettings) -> dict:
    e = P.EFFECTS_BY_MODE[s.mode]
    return {"effect": e.key, "mode": s.mode, "brightness": s.brightness, "speed": s.speed,
            "direction": "left" if s.direction == P.DIRECTION_LEFT else "right",
            "color": P.COLORS[s.color][0]}


def cmd_light_status(args) -> int:
    d = _describe(state.light_settings())
    d["lights"] = "off" if state.lights_off() else "on"
    d["source"] = "last settings sent by ajazzctl (the keyboard cannot report them)"
    _out(args, d, "\n".join(f"{k:<11} {v}" for k, v in d.items()))
    return 0


def _parse_effect(name: str) -> P.Effect:
    if name in P.EFFECTS_BY_KEY:
        return P.EFFECTS_BY_KEY[name]
    if name.isdigit() and int(name) in P.EFFECTS_BY_MODE:
        return P.EFFECTS_BY_MODE[int(name)]
    raise SystemExit(f"unknown effect {name!r}; see `ajazzctl lighting effects`")


def _parse_color(name: str) -> int:
    if name in P.COLOR_INDEX:
        return P.COLOR_INDEX[name]
    raise SystemExit(f"unknown colour {name!r}; effects support only: "
                     + ", ".join(n for n, _ in P.COLORS)
                     + ". For arbitrary RGB use `ajazzctl lighting custom --all RRGGBB`.")


def cmd_light_set(args) -> int:
    s = state.light_settings()
    if args.effect:
        s.mode = _parse_effect(args.effect).mode
    if args.brightness is not None:
        s.brightness = args.brightness
    if args.speed is not None:
        s.speed = args.speed
    if args.direction:
        s.direction = P.DIRECTION_LEFT if args.direction == "left" else P.DIRECTION_RIGHT
    if args.color:
        s.color = _parse_color(args.color)
    if s.mode == P.MODE_CUSTOM:
        return _apply_custom(args, state.custom_colors() or {}, s.brightness)
    try:
        s.validate()
    except ValueError as e:
        raise SystemExit(str(e))
    with _open(args) as kb:
        kb.set_lighting(s)
    state.remember_lighting(s)
    _out(args, _describe(s), "sent: " + ", ".join(f"{k}={v}" for k, v in _describe(s).items()))
    return 0


def cmd_light_power(args) -> int:
    from . import lights
    with _open(args) as kb:
        on = args.power == "on" or (args.power == "toggle" and state.lights_off())
        (lights.turn_on if on else lights.turn_off)(kb)
    _out(args, {"lights": "on" if on else "off"}, f"lights {'on' if on else 'off'}")
    return 0


def _apply_custom(args, colors, brightness) -> int:
    with _open(args) as kb:
        kb.set_custom_colors(colors, brightness=brightness)
    state.remember_custom(colors, brightness)
    _out(args, {"custom_leds": len(colors)}, f"sent custom colours for {len(colors)} keys")
    return 0


def cmd_light_custom(args) -> int:
    colors = {} if args.clear else dict(state.custom_colors())
    try:
        if args.all:
            rgb = P.parse_hex_color(args.all)
            colors = {k.led: rgb for k in layout.KEYS}
        if args.file:
            with open(args.file) as f:
                for name, hexv in json.load(f).items():
                    colors[_key(name).led] = P.parse_hex_color(hexv)
        for spec in args.key or []:
            name, _, hexv = spec.partition("=")
            if not hexv:
                raise SystemExit(f"expected KEY=RRGGBB, got {spec!r}")
            colors[_key(name).led] = P.parse_hex_color(hexv)
    except ValueError as e:
        raise SystemExit(str(e))
    b = args.brightness if args.brightness is not None else state.light_settings().brightness
    if b not in P.BRIGHTNESS_RANGE:
        raise SystemExit("brightness must be 1..5")
    return _apply_custom(args, colors, b)


def _key(name: str) -> layout.Key:
    k = layout.KEYS_BY_NAME.get(name.lower())
    if not k:
        raise SystemExit(f"unknown key {name!r}; see `ajazzctl keys`")
    return k


def cmd_keys(args) -> int:
    data = [{"name": layout.key_name(k.code), "label": k.label, "hid": k.code, "led": k.led,
             "row": k.row, "col": k.col} for k in layout.KEYS]
    _out(args, data, "\n".join(f"{d['name']:<10} {d['label']:<10} hid=0x{d['hid']:02x} led={d['led']}"
                               for d in data))
    return 0


def cmd_sleep(args) -> int:
    idx = P.SLEEP_TIMES.index(args.value)
    with _open(args) as kb:
        kb.set_sleep_time(idx)
    state.remember("sleep_time", args.value)
    _out(args, {"sleep_time": args.value}, f"sent: sleep time = {args.value}")
    return 0


def cmd_response(args) -> int:
    idx = P.RESPONSE_TIMES.index(args.value)
    with _open(args) as kb:
        kb.set_response_time(idx)
    state.remember("response_time", args.value)
    _out(args, {"response_time": args.value}, f"sent: key response gear = {args.value}")
    return 0


def cmd_fn_switch(args) -> int:
    on = args.value == "on"
    with _open(args) as kb:
        kb.set_fn_switch(on)
    state.remember("fn_switch", on)
    _out(args, {"fn_switch": on}, f"sent: Fn switch = {args.value}")
    return 0


def cmd_music(args) -> int:
    import signal
    import threading
    from . import music
    color = None
    if args.color and args.color != "rainbow":
        try:
            color = P.parse_hex_color(args.color)
        except ValueError as e:
            raise SystemExit(str(e))
    previous = state.light_settings()
    done = threading.Event()
    errors = []

    def on_error(e):
        errors.append(e)
        done.set()
    with _open(args) as kb:
        vis = music.Visualizer(kb, style=args.style, color=color, fps=args.fps,
                               sensitivity=args.sensitivity, source=args.source, on_error=on_error)
        try:
            vis.start()
        except music.AudioError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        signal.signal(signal.SIGTERM, lambda *a: done.set())
        print(f"music sync running ({args.style}); Ctrl-C to stop", file=sys.stderr)
        try:
            while not done.wait(0.5):
                pass
        except KeyboardInterrupt:
            pass
        vis.stop(restore=previous, custom=state.custom_colors())
    if errors:
        print(f"error: {errors[0]}", file=sys.stderr)
        return 1
    print("stopped; previous lighting restored", file=sys.stderr)
    return 0


def _target(name: str) -> int:
    n = name.lower()
    if n in P.HID_NAMES:
        return P.HID_NAMES[n]
    if n.startswith("0x"):
        try:
            return int(n, 16)
        except ValueError:
            pass
    raise SystemExit(f"unknown target key {name!r}; see `ajazzctl keymap targets`")


def cmd_keymap_set(args) -> int:
    src = _key(args.key)
    if src.code == 0xAF:
        raise SystemExit("the Fn key cannot be remapped")
    layer = P.LAYER_FN if args.fn_layer else P.LAYER_BASE
    tgt = 0 if args.reset else _target(args.target)
    with _open(args) as kb:
        kb.set_key(layer, src.code, tgt)
    d = state.load()
    km = d.setdefault("keymap", {})
    slot = f"{layer}:{layout.key_name(src.code)}"
    if tgt:
        km[slot] = tgt
    else:
        km.pop(slot, None)
    state.save(d)
    what = "default" if not tgt else f"0x{tgt:02x}"
    _out(args, {"layer": layer, "key": args.key, "target": tgt},
         f"sent: {'Fn+' if layer else ''}{args.key} -> {what}  (experimental)")
    return 0


def cmd_keymap_list(args) -> int:
    km = state.load().get("keymap", {})
    names = {v: k for k, v in P.HID_NAMES.items()}
    lines = [f"{'Fn+' if s.startswith('1:') else ''}{s[2:]:<10} -> {names.get(v, hex(v))}"
             for s, v in sorted(km.items())] or ["no remaps sent from this computer"]
    _out(args, km, "\n".join(lines))
    return 0


def cmd_keymap_targets(args) -> int:
    _out(args, P.HID_NAMES, " ".join(sorted(P.HID_NAMES, key=lambda k: P.HID_NAMES[k])))
    return 0


def cmd_unsupported(args) -> int:
    print(f"`{args.feature}` is not implemented yet: the packet format was located in the vendor "
          "software but has not been verified on hardware. See docs/PROTOCOL.md.", file=sys.stderr)
    return 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ajazzctl", description=__doc__)
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--device", help="hidraw node to use (default: auto-detect, wired first)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("-v", "--verbose", action="store_true", help="log raw packets to stderr")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("detect", help="list AJAZZ HID interfaces").set_defaults(fn=cmd_detect)
    sub.add_parser("info", help="query battery / power state").set_defaults(fn=cmd_info)
    sub.add_parser("keys", help="list key names usable with `lighting custom`").set_defaults(fn=cmd_keys)

    lp = sub.add_parser("lighting", help="RGB lighting").add_subparsers(dest="lcmd", required=True)
    lp.add_parser("effects", help="list effects and colours").set_defaults(fn=cmd_effects)
    lp.add_parser("status", help="show last settings sent").set_defaults(fn=cmd_light_status)
    sp = lp.add_parser("set", help="set effect and/or options (unspecified options keep last value)")
    sp.add_argument("--effect", "-e")
    sp.add_argument("--brightness", "-b", type=int, choices=P.BRIGHTNESS_RANGE)
    sp.add_argument("--speed", "-s", type=int, choices=P.SPEED_RANGE)
    sp.add_argument("--direction", "-d", choices=("left", "right"))
    sp.add_argument("--color", "-c")
    sp.set_defaults(fn=cmd_light_set)
    for name, kw in (("effect", "effect"), ("brightness", "brightness"), ("speed", "speed"),
                     ("color", "color"), ("direction", "direction")):
        q = lp.add_parser(name, help=f"shortcut for `lighting set --{name}`")
        if name in ("brightness", "speed"):
            q.add_argument(kw, type=int, choices=P.BRIGHTNESS_RANGE)
        elif name == "direction":
            q.add_argument(kw, choices=("left", "right"))
        else:
            q.add_argument(kw)
        q.set_defaults(fn=cmd_light_set, **{k: None for k in
                                             ("effect", "brightness", "speed", "direction", "color")
                                             if k != kw})
    for name, hlp in (("off", "turn all LEDs off (remembers your settings)"),
                      ("on", "turn lighting back on with your previous settings"),
                      ("toggle", "toggle lights on/off")):
        lp.add_parser(name, help=hlp).set_defaults(fn=cmd_light_power, power=name)
    cp = lp.add_parser("custom", help="per-key colours (custom mode)")
    cp.add_argument("--all", metavar="RRGGBB", help="set every key to one colour")
    cp.add_argument("--key", "-k", action="append", metavar="KEY=RRGGBB")
    cp.add_argument("--file", help="JSON object {key name: 'RRGGBB'}")
    cp.add_argument("--clear", action="store_true", help="start from all-off instead of last saved")
    cp.add_argument("--brightness", "-b", type=int, choices=P.BRIGHTNESS_RANGE)
    cp.set_defaults(fn=cmd_light_custom)

    st = sub.add_parser("settings", help="keyboard settings").add_subparsers(dest="scmd", required=True)
    q = st.add_parser("sleep", help="auto-sleep timeout")
    q.add_argument("value", choices=P.SLEEP_TIMES)
    q.set_defaults(fn=cmd_sleep)
    q = st.add_parser("response", help="key response gear (1 = fastest)")
    q.add_argument("value", choices=P.RESPONSE_TIMES)
    q.set_defaults(fn=cmd_response)
    q = st.add_parser("fn-switch", help="swap F-row default between F-keys and media")
    q.add_argument("value", choices=("on", "off"))
    q.set_defaults(fn=cmd_fn_switch)

    mp = sub.add_parser("music", help="audio-reactive lighting (runs until Ctrl-C)")
    mp.add_argument("--style", choices=("spectrum", "pulse", "wave"), default="spectrum")
    mp.add_argument("--color", default="rainbow", help="'rainbow' or RRGGBB")
    mp.add_argument("--fps", type=int, default=30, choices=range(5, 61), metavar="5..60")
    mp.add_argument("--sensitivity", type=float, default=1.0, help="0.5 (calm) .. 2.0 (jumpy)")
    mp.add_argument("--source", default="@DEFAULT_MONITOR@",
                    help="PulseAudio/PipeWire source (default: monitor of default output)")
    mp.set_defaults(fn=cmd_music)

    kp = sub.add_parser("keymap", help="remap keys (experimental)").add_subparsers(
        dest="kcmd", required=True)
    q = kp.add_parser("set", help="remap KEY to TARGET (single key, stored on the keyboard)")
    q.add_argument("key", help="physical key name, see `ajazzctl keys`")
    q.add_argument("target", help="target key name, see `ajazzctl keymap targets`")
    q.add_argument("--fn-layer", action="store_true", help="remap Fn+KEY instead of KEY")
    q.set_defaults(fn=cmd_keymap_set, reset=False)
    q = kp.add_parser("reset", help="restore KEY's default function")
    q.add_argument("key")
    q.add_argument("--fn-layer", action="store_true")
    q.set_defaults(fn=cmd_keymap_set, reset=True, target=None)
    kp.add_parser("list", help="remaps sent from this computer").set_defaults(fn=cmd_keymap_list)
    kp.add_parser("targets", help="list target key names").set_defaults(fn=cmd_keymap_targets)

    for feat in ("macro",):
        sub.add_parser(feat, help="(not yet supported)").set_defaults(fn=cmd_unsupported, feature=feat)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except DeviceError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
