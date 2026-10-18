"""Audio-reactive lighting (software driven, like the vendor's "Music rhythm").

The keyboard is put in music mode (22) and sent live frames (chunks 0xF0..0xF5,
not stored in flash). When frames stop, the firmware falls back to the stored
effect on its own; we also re-send the previous settings on a clean stop.

Audio comes from the PipeWire/PulseAudio monitor of the default output via
`parec`, so it reacts to whatever is playing. Requires numpy.
"""
from __future__ import annotations

import colorsys
import math
import os
import shutil
import subprocess
import threading
import time

from . import layout
from . import protocol as P

RATE = 48000
FFT_SIZE = 2048
BANDS = 16
F_LO, F_HI = 40.0, 16000.0
STYLES = ("spectrum", "pulse", "wave")
MODE_MUSIC = 22


class AudioError(Exception):
    pass


class AudioSource:
    """Mono s16 capture of the default sink monitor via parec."""

    def __init__(self, device: str = "@DEFAULT_MONITOR@"):
        exe = shutil.which("parec")
        if not exe:
            raise AudioError("`parec` not found (install libpulse / pipewire-pulse)")
        self.proc = subprocess.Popen(
            [exe, f"--device={device}", "--format=s16le", f"--rate={RATE}", "--channels=1",
             "--latency-msec=15", "--raw"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.fd = self.proc.stdout.fileno()
        os.set_blocking(self.fd, False)
        self.buf = bytearray()

    def read_latest(self, nbytes: int) -> bytes:
        """Return the newest `nbytes` of audio (discarding anything older)."""
        while True:
            try:
                chunk = os.read(self.fd, 65536)
            except BlockingIOError:
                break
            if not chunk:
                err = self.proc.stderr.read().decode(errors="replace").strip()
                raise AudioError(f"audio capture stopped: {err or 'parec exited'}")
            self.buf += chunk
        if len(self.buf) > nbytes:
            del self.buf[:len(self.buf) - nbytes]
        return bytes(self.buf)

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(1)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class Analyzer:
    """FFT -> BANDS levels in 0..1 with auto-gain and peak-hold smoothing."""

    def __init__(self, sensitivity: float = 1.0):
        import numpy as np
        self.np = np
        self.window = np.hanning(FFT_SIZE).astype(np.float32)
        freqs = np.fft.rfftfreq(FFT_SIZE, 1 / RATE)
        edges = np.geomspace(F_LO, F_HI, BANDS + 1)
        self.bins = [(int(np.searchsorted(freqs, lo)), max(int(np.searchsorted(freqs, hi)),
                                                           int(np.searchsorted(freqs, lo)) + 1))
                     for lo, hi in zip(edges[:-1], edges[1:])]
        centers = np.sqrt(edges[:-1] * edges[1:])
        self.tilt = (centers / 1000.0) ** 0.5     # flatten typical music spectrum (~pink)
        self.levels = np.zeros(BANDS, dtype=np.float32)
        self.peak_db = -30.0
        self.sensitivity = sensitivity
        self.energy = 0.0
        self.bass = 0.0

    def update(self, pcm: bytes):
        np = self.np
        x = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        if len(x) < FFT_SIZE:
            x = np.pad(x, (FFT_SIZE - len(x), 0))
        spec = np.abs(np.fft.rfft(x[-FFT_SIZE:] * self.window)) / (FFT_SIZE / 4)
        mags = np.array([spec[a:b].max() for a, b in self.bins]) * self.tilt
        db = 20 * np.log10(mags + 1e-9)
        top = float(db.max())
        # auto-gain: follow loud peaks quickly, fall back slowly
        self.peak_db = max(top, self.peak_db - 0.15, -60.0)
        span = 40.0 / self.sensitivity
        lv = np.clip((db - (self.peak_db - span)) / span, 0.0, 1.0)
        if top < -70:      # silence
            lv[:] = 0
        self.levels = np.maximum(lv, self.levels * 0.82)
        self.energy = float(self.levels.mean())
        self.bass = max(float(self.levels[:3].max()), self.bass * 0.85)
        return self.levels


def _hsv(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, max(0.0, min(1.0, v)))
    return int(r * 255), int(g * 255), int(b * 255)


class Renderer:
    def __init__(self, style: str = "spectrum", color: tuple[int, int, int] | None = None):
        if style not in STYLES:
            raise ValueError(f"style must be one of {STYLES}")
        self.style = style
        self.color = color          # None = rainbow
        xs = [k.rect[0] + k.rect[2] / 2 for k in layout.KEYS]
        ys = [k.rect[1] + k.rect[3] / 2 for k in layout.KEYS]
        self.x0, self.x1, self.y0, self.y1 = min(xs), max(xs), min(ys), max(ys)
        self.keys = []
        for k in layout.KEYS:
            cx, cy = k.rect[0] + k.rect[2] / 2, k.rect[1] + k.rect[3] / 2
            u = (cx - self.x0) / (self.x1 - self.x0)          # 0..1 left->right
            v = (cy - self.y0) / (self.y1 - self.y0)          # 0..1 top->bottom
            band = min(BANDS - 1, int(u * BANDS))
            r = math.hypot(u - 0.5, (v - 0.5) * 0.45)         # distance from centre
            self.keys.append((k.led, u, v, band, r))
        self.history = [0.0] * 32
        self.t0 = time.monotonic()

    def _tint(self, hue: float, value: float):
        if self.color is None:
            return _hsv(hue, 1.0, value)
        return tuple(int(c * max(0.0, min(1.0, value))) for c in self.color)

    def frame(self, an: Analyzer) -> dict[int, tuple[int, int, int]]:
        t = time.monotonic() - self.t0
        lv = an.levels
        out = {}
        if self.style == "spectrum":
            for led, u, v, band, _ in self.keys:
                height = float(lv[band])            # fraction of the board height lit
                fill = 1.0 - v                      # this key's height from the bottom (0..1)
                on = max(0.0, min(1.0, (height * 1.15 - fill) * 6 + 1))
                hue = 0.33 * (1 - fill) if self.color is None else 0   # green bottom -> red top
                out[led] = self._tint(hue, 0.04 + 0.96 * on) if on > 0 else (0, 0, 0)
        elif self.style == "pulse":
            val = 0.08 + 0.92 * an.bass ** 1.5
            for led, u, v, band, _ in self.keys:
                out[led] = self._tint(t * 0.05 + u * 0.3, val)
        else:  # wave
            self.history = [an.bass] + self.history[:-1]
            n = len(self.history)
            for led, u, v, band, r in self.keys:
                e = self.history[min(n - 1, int(r * 2 * n))]
                out[led] = self._tint(t * 0.04 + r, 0.05 + 0.95 * e ** 1.3)
        return out


class Visualizer:
    """Runs capture -> analysis -> frames on a background thread."""

    def __init__(self, kb, style="spectrum", color=None, fps=30, sensitivity=1.0,
                 source="@DEFAULT_MONITOR@", on_error=None):
        self.kb = kb
        self.renderer = Renderer(style, color)
        self.fps = fps
        self.sensitivity = sensitivity
        self.source = source
        self.on_error = on_error or (lambda e: None)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.analyzer: Analyzer | None = None

    def start(self):
        try:
            import numpy  # noqa: F401
        except ImportError as e:
            raise AudioError("music mode needs numpy (pacman -S python-numpy)") from e
        self.audio = AudioSource(self.source)
        self.analyzer = Analyzer(self.sensitivity)
        self.kb.enter_live_mode(MODE_MUSIC)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def set_style(self, style: str):
        self.renderer.style = style if style in STYLES else self.renderer.style

    def set_color(self, color):
        self.renderer.color = color

    def _run(self):
        period = 1.0 / self.fps
        nxt = time.monotonic()
        try:
            while not self._stop.is_set():
                pcm = self.audio.read_latest(FFT_SIZE * 2)
                self.analyzer.update(pcm)
                self.kb.send_live_frame(self.renderer.frame(self.analyzer))
                nxt += period
                delay = nxt - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                else:
                    nxt = time.monotonic()
        except Exception as e:
            self.on_error(e)
        finally:
            self.audio.close()

    def stop(self, restore: P.LightSettings | None = None, custom=None):
        self._stop.set()
        if self._thread:
            self._thread.join(2)
        if restore is not None:
            if restore.mode == P.MODE_CUSTOM:
                self.kb.set_custom_colors(custom or {}, brightness=restore.brightness)
            else:
                self.kb.set_lighting(restore)

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())
