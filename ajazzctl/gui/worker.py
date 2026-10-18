"""Background device access for the GUI.

All hidraw I/O happens off the GTK main thread. Ordinary commands go through a
single worker queue. Live-frame streams (per-key preview, music) run on their
own thread and share the Keyboard object, which serialises writes with a lock.
"""
from __future__ import annotations

import queue
import threading
import time

from gi.repository import GLib

from .. import protocol as P
from .. import state
from ..device import DeviceError, Keyboard


class DeviceWorker:
    def __init__(self, on_connected, on_error):
        self.q: queue.Queue = queue.Queue()
        self.kb: Keyboard | None = None
        self.on_connected = on_connected
        self.on_error = on_error
        threading.Thread(target=self._run, daemon=True, name="ajazz-worker").start()

    def submit(self, fn, *args, done=None, quiet=False):
        """Run fn(kb, *args) on the worker; call done(result) on the main thread."""
        self.q.put((fn, args, done, quiet))

    def _run(self):
        while True:
            fn, args, done, quiet = self.q.get()
            try:
                if self.kb is None:
                    self.kb = Keyboard.open()
                    GLib.idle_add(self.on_connected, self.kb.node)
                result = fn(self.kb, *args)
                if done:
                    GLib.idle_add(done, result)
            except DeviceError as e:
                if self.kb is not None:
                    self.kb.close()
                    self.kb = None
                    GLib.idle_add(self.on_connected, None)
                if not quiet:
                    GLib.idle_add(self.on_error, str(e))
            except Exception as e:  # keep the worker alive whatever happens
                GLib.idle_add(self.on_error, f"{type(e).__name__}: {e}")


def restore_lighting(kb: Keyboard) -> None:
    """Re-send the last stored lighting (used after a live stream ends)."""
    s = state.light_settings()
    if s.mode == P.MODE_CUSTOM:
        kb.set_custom_colors(state.custom_colors(), brightness=s.brightness)
    else:
        kb.set_lighting(s)


class FrameStreamer:
    """Streams frames from `frame_fn()` to the keyboard's live mode."""

    def __init__(self, kb: Keyboard, frame_fn, fps: int = 15, on_error=None):
        self.kb = kb
        self.frame_fn = frame_fn
        self.fps = fps
        self.on_error = on_error or (lambda e: None)
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self.kb.enter_live_mode(22)
        self._thread = threading.Thread(target=self._run, daemon=True, name="ajazz-stream")
        self._thread.start()
        return self

    def _run(self):
        period = 1 / self.fps
        try:
            while not self._stop.is_set():
                t = time.monotonic()
                self.kb.send_live_frame(self.frame_fn())
                self._stop.wait(max(0.0, period - (time.monotonic() - t)))
        except Exception as e:
            self.on_error(e)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(2)

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())
