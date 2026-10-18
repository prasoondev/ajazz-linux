#!/usr/bin/env python3
"""Live-frame streaming test: green bar sweeping over a dim blue background."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ajazzctl.device import Keyboard
from ajazzctl import layout, protocol as P

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 120
kb = Keyboard.open(sys.argv[2] if len(sys.argv) > 2 else None)
kb.send(P.build(P.CMD_SET_LIGHT, (22 - 1, 4, 2, 0, 7)))
time.sleep(0.05)
kb.send(P.build(P.CMD_STREAM_BEGIN))
time.sleep(0.1)
xs = {k.led: k.rect[0] + k.rect[2] / 2 for k in layout.KEYS}
lo, hi = min(xs.values()), max(xs.values())
t0 = time.monotonic(); frames = 0
while (t := time.monotonic() - t0) < secs:
    bar = lo + (hi - lo) * ((t / 2.0) % 1.0)
    frame = {led: ((0, 255, 0) if abs(x - bar) < 40 else (0, 0, 40)) for led, x in xs.items()}
    for pkt in P.rgb_chunks(frame, P.LIVE_CHUNK_BASE):
        kb.t.write(pkt)
    frames += 1
    time.sleep(max(0, frames / 20 - (time.monotonic() - t0)))
print(f"{frames} frames in {time.monotonic() - t0:.1f}s")
