"""Device discovery (sysfs) and hidraw transport."""
from __future__ import annotations

import errno
import os
import re
import select
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import protocol as P

VENDOR_ID = 0x1A2C
PRODUCTS = {
    0xA036: "wired",     # AK820 Max Plus over USB cable
    0x8FFF: "2.4GHz",    # USB receiver
}
CONFIG_USAGE_PAGE = 0xFF02
CONFIG_USAGE = 0x02

SYS_HIDRAW = Path("/sys/class/hidraw")


class DeviceError(Exception):
    pass


@dataclass
class HidrawNode:
    name: str               # hidraw0
    devnode: str            # /dev/hidraw0
    bus: int
    vid: int
    pid: int
    hid_name: str
    uniq: str
    interface: int | None
    usage_page: int | None
    usage: int | None
    report_descriptor: bytes
    sys_path: str

    @property
    def is_config_interface(self) -> bool:
        return (self.vid == VENDOR_ID and self.pid in PRODUCTS
                and self.usage_page == CONFIG_USAGE_PAGE and self.usage == CONFIG_USAGE)

    @property
    def connection(self) -> str:
        if self.bus == 0x05:
            return "bluetooth"
        return PRODUCTS.get(self.pid, "unknown")


def first_usage(desc: bytes) -> tuple[int | None, int | None]:
    """Return (usage page, usage) of the first top-level collection."""
    page = usage = None
    i = 0
    while i < len(desc):
        b = desc[i]
        if b == 0xFE:  # long item
            if i + 1 >= len(desc):
                break
            i += 3 + desc[i + 1]
            continue
        size = (0, 1, 2, 4)[b & 3]
        tag = b & 0xFC
        val = int.from_bytes(desc[i + 1:i + 1 + size], "little")
        if tag == 0x04:          # Usage Page (global)
            page = val
        elif tag == 0x08 and usage is None:  # Usage (local)
            if size == 4:
                page, usage = val >> 16, val & 0xFFFF
            else:
                usage = val
        elif tag == 0xA0:        # Collection
            return page, usage
        i += 1 + size
    return page, usage


def _read(p: Path, default: str = "") -> str:
    try:
        return p.read_text().strip()
    except OSError:
        return default


def enumerate_hidraw(root: Path = SYS_HIDRAW) -> list[HidrawNode]:
    nodes = []
    if not root.exists():
        return nodes
    for entry in sorted(root.iterdir(), key=lambda p: int(re.sub(r"\D", "", p.name) or 0)):
        dev = entry / "device"
        uevent = dict(line.split("=", 1) for line in _read(dev / "uevent").splitlines() if "=" in line)
        hid_id = uevent.get("HID_ID", "")
        m = re.fullmatch(r"([0-9A-Fa-f]+):([0-9A-Fa-f]+):([0-9A-Fa-f]+)", hid_id)
        if not m:
            continue
        bus, vid, pid = (int(x, 16) for x in m.groups())
        try:
            desc = (dev / "report_descriptor").read_bytes()
        except OSError:
            desc = b""
        real = os.path.realpath(entry)
        im = re.search(r"/\d+-[\d.]+:\d+\.(\d+)/", real)
        page, usage = first_usage(desc)
        nodes.append(HidrawNode(
            name=entry.name, devnode=f"/dev/{entry.name}", bus=bus, vid=vid, pid=pid,
            hid_name=uevent.get("HID_NAME", ""), uniq=uevent.get("HID_UNIQ", ""),
            interface=int(im.group(1)) if im else None, usage_page=page, usage=usage,
            report_descriptor=desc, sys_path=real))
    return nodes


def find_keyboards(root: Path = SYS_HIDRAW) -> list[HidrawNode]:
    """All config interfaces of supported devices, wired first."""
    found = [n for n in enumerate_hidraw(root) if n.is_config_interface]
    return sorted(found, key=lambda n: (n.pid != 0xA036, n.name))


def related_nodes(root: Path = SYS_HIDRAW) -> list[HidrawNode]:
    return [n for n in enumerate_hidraw(root) if n.vid == VENDOR_ID]


class Transport:
    """Abstract transport: send/receive 64-byte packets."""

    def write(self, packet: bytes) -> None:
        raise NotImplementedError

    def read(self, timeout: float) -> bytes | None:
        raise NotImplementedError

    def drain(self) -> list[bytes]:
        out = []
        while (pkt := self.read(0)) is not None:
            out.append(pkt)
        return out

    def close(self) -> None:
        pass


class HidrawTransport(Transport):
    def __init__(self, devnode: str):
        self.devnode = devnode
        try:
            self.fd = os.open(devnode, os.O_RDWR | os.O_CLOEXEC)
        except PermissionError as e:
            raise DeviceError(
                f"permission denied opening {devnode}. Install the udev rule "
                "(udev/70-ajazz-ak820.rules) and replug the keyboard, or see README.") from e
        except OSError as e:
            raise DeviceError(f"cannot open {devnode}: {e.strerror}") from e

    def write(self, packet: bytes) -> None:
        if len(packet) != P.PACKET_LEN:
            raise ValueError(f"packet must be {P.PACKET_LEN} bytes")
        # hidraw: first byte is the report number; 0 = device uses no report IDs
        buf = b"\x00" + packet
        try:
            n = os.write(self.fd, buf)
        except OSError as e:
            if e.errno in (errno.ENODEV, errno.EIO):
                raise DeviceError("keyboard disconnected") from e
            raise DeviceError(f"write failed: {e.strerror}") from e
        if n != len(buf):
            raise DeviceError(f"short write: {n} of {len(buf)} bytes")

    def read(self, timeout: float) -> bytes | None:
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return None
        try:
            data = os.read(self.fd, 256)
        except OSError as e:
            if e.errno in (errno.ENODEV, errno.EIO):
                raise DeviceError("keyboard disconnected") from e
            raise DeviceError(f"read failed: {e.strerror}") from e
        return data

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class SimulatedTransport(Transport):
    """In-memory keyboard for UI development (AJAZZCTL_FAKE=1). Never touches hardware."""

    def __init__(self):
        self.pending: list[bytes] = []
        self.sent = 0

    def write(self, packet: bytes) -> None:
        self.sent += 1
        if packet[4] == P.CMD_STATUS:
            self.pending.append(P.build(P.CMD_STATUS, (87, 2)))

    def read(self, timeout: float) -> bytes | None:
        return self.pending.pop(0) if self.pending else None


def simulated_node() -> HidrawNode:
    return HidrawNode(name="sim", devnode="(simulated)", bus=3, vid=VENDOR_ID, pid=0x8FFF,
                      hid_name="Simulated AK820", uniq="", interface=0,
                      usage_page=CONFIG_USAGE_PAGE, usage=CONFIG_USAGE,
                      report_descriptor=b"", sys_path="/nonexistent/a/b/c/d")


class Keyboard:
    """High-level operations. Timing mirrors the vendor application."""

    # vendor app: Sleep(100) after a write before reading, 500 ms read timeout
    REPLY_DELAY = 0.1
    REPLY_TIMEOUT = 0.5
    INTER_PACKET = 0.01

    def __init__(self, transport: Transport, node: HidrawNode | None = None, log=None):
        self.t = transport
        self.node = node
        self.log = log or (lambda msg: None)
        # serialises access when the GUI worker and the music thread share a device
        self.lock = threading.RLock()

    @classmethod
    def open(cls, devnode: str | None = None, log=None) -> "Keyboard":
        if os.environ.get("AJAZZCTL_FAKE"):
            return cls(SimulatedTransport(), simulated_node(), log)
        boards = find_keyboards()
        if devnode:
            boards = [b for b in boards if b.devnode == devnode]
            if not boards:
                raise DeviceError(f"{devnode} is not an AJAZZ AK820 configuration interface")
        if not boards:
            raise DeviceError("no AJAZZ AK820 Max Plus found (looked for 1a2c:a036 / 1a2c:8fff, "
                              "usage page 0xFF02)")
        node = boards[0]
        return cls(HidrawTransport(node.devnode), node, log)

    def close(self):
        self.t.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- low level ------------------------------------------------------------
    def send(self, packet: bytes) -> None:
        self.log(f">> {packet[:16].hex(' ')}{' …' if any(packet[16:]) else ''}")
        with self.lock:
            self.t.write(packet)

    def transact(self, packet: bytes, expect_cmd: int | None = None) -> bytes:
        with self.lock:
            return self._transact(packet, expect_cmd)

    def _transact(self, packet: bytes, expect_cmd: int | None) -> bytes:
        stale = self.t.drain()
        for s in stale:
            self.log(f"<< (stale) {s[:16].hex(' ')}")
        self.send(packet)
        deadline = time.monotonic() + self.REPLY_DELAY + self.REPLY_TIMEOUT
        while (left := deadline - time.monotonic()) > 0:
            data = self.t.read(left)
            if data is None:
                break
            self.log(f"<< {data[:16].hex(' ')}")
            if not P.is_reply(data):
                continue
            if expect_cmd is not None and data[4] != expect_cmd:
                continue
            return data
        raise DeviceError("no reply from keyboard (is it asleep or switched off?)")

    # -- operations -----------------------------------------------------------
    def status(self) -> P.Status:
        return P.parse_status(self.transact(P.status_request(), expect_cmd=P.CMD_STATUS))

    def set_lighting(self, s: P.LightSettings) -> None:
        self.send(P.light_packet(s))
        time.sleep(self.INTER_PACKET)

    def set_custom_colors(self, leds, brightness: int = 5) -> None:
        """Switch to custom mode and store per-key colours on the keyboard."""
        with self.lock:
            self.set_lighting(P.LightSettings(mode=P.MODE_CUSTOM, brightness=brightness))
            self.send(P.build(P.CMD_CUSTOM_PREPARE))
            time.sleep(self.INTER_PACKET)
            for pkt in P.rgb_chunks(leds, P.CUSTOM_CHUNK_BASE):
                self.send(pkt)
                time.sleep(0.003)  # vendor app: Sleep(3) between chunks

    def enter_live_mode(self, mode: int = 22) -> None:
        """Select a host-driven mode (22 music / 23 screen) and open the frame stream.

        Live frames are not stored; when they stop the keyboard reverts to its
        stored effect by itself (verified on hardware).
        """
        if mode not in (22, 23):
            raise ValueError("live mode must be 22 (music) or 23 (screen)")
        with self.lock:
            self.send(P.build(P.CMD_SET_LIGHT, (mode - 1, 4, 2, 0, 7)))
            time.sleep(self.INTER_PACKET)
            self.send(P.build(P.CMD_STREAM_BEGIN))  # vendor waits for a reply; none arrives
            time.sleep(0.05)

    def send_live_frame(self, leds) -> None:
        pkts = P.rgb_chunks(leds, P.LIVE_CHUNK_BASE)
        with self.lock:
            for pkt in pkts:
                self.t.write(pkt)

    def set_key(self, layer: int, source: int, target: int) -> None:
        self.send(P.key_assign_packet(layer, source, target))
        time.sleep(0.2)  # vendor app: Sleep(200) after each key write

    def set_sleep_time(self, index: int) -> None:
        self.send(P.sleep_time_packet(index))

    def set_response_time(self, index: int) -> None:
        self.send(P.response_time_packet(index))

    def set_fn_switch(self, enabled: bool) -> None:
        self.send(P.fn_switch_packet(enabled))
