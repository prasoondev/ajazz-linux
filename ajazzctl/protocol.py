"""Packet construction and parsing for the AJAZZ AK820 Max Plus vendor protocol.

Everything here is pure (no I/O) so it can be unit tested without hardware.
See docs/PROTOCOL.md for the evidence behind each field.

Wire format (vendor interface 0, usage page 0xFF02, usage 0x02):
  * host -> device: 64-byte HID output report, no report ID
  * device -> host: 64-byte HID input report, no report ID
  * every packet starts with the magic AA 55 CC 33, followed by a command byte
"""
from __future__ import annotations

from dataclasses import dataclass, field

PACKET_LEN = 64
MAGIC = bytes((0xAA, 0x55, 0xCC, 0x33))

# --- command bytes (offset 4) -------------------------------------------------
CMD_KEY_ASSIGN = 0x04        # [5]=layer+1 [6]=key HID code [7]=target (0=default)
CMD_SET_LIGHT = 0x07         # [5]=mode-1 [6]=bright-1 [7]=speed-1 [8]=dir [9]=color
CMD_RESET = 0x08             # restore keyboard defaults (destructive)
CMD_STREAM_BEGIN = 0x09      # sent before per-key RGB chunks
CMD_CUSTOM_PREPARE = 0x0B    # sent after selecting custom mode
CMD_SLEEP_TIME = 0x0C        # [5]=index into SLEEP_TIMES
CMD_RESPONSE_TIME = 0x0D     # [5]=index into RESPONSE_TIMES
CMD_STATUS = 0x0E            # reply [5]=battery % [6]=power state
CMD_FN_SWITCH = 0x10         # [5]=0 normal / 1 Fn-switched (F-row vs media)

# per-key RGB is sent as 6 chunks of 54 bytes (18 LEDs x RGB) = 108 LEDs
CHUNK_DATA_LEN = 54
CHUNK_COUNT = 6
LED_COUNT = CHUNK_DATA_LEN * CHUNK_COUNT // 3          # 108
CUSTOM_CHUNK_BASE = 0xF6     # stored colours for custom mode (0xF6..0xFB)
LIVE_CHUNK_BASE = 0xF0       # real-time frame, not stored (0xF0..0xF5)

MODE_CUSTOM = 24

# attribute bits from the vendor layout file (kb-k600t.xml <light><info attribute=>)
ATTR_BRIGHTNESS = 0x01
ATTR_SPEED = 0x02
ATTR_DIRECTION = 0x04
ATTR_COLOR = 0x40
ATTR_CUSTOM = 0x100
ATTR_MUSIC = 0x200
ATTR_SCREEN = 0x400


@dataclass(frozen=True)
class Effect:
    mode: int
    key: str
    name: str
    attributes: int

    @property
    def has_brightness(self) -> bool:
        return bool(self.attributes & ATTR_BRIGHTNESS)

    @property
    def has_speed(self) -> bool:
        return bool(self.attributes & ATTR_SPEED)

    @property
    def has_direction(self) -> bool:
        return bool(self.attributes & ATTR_DIRECTION)

    @property
    def has_color(self) -> bool:
        return bool(self.attributes & ATTR_COLOR)


# Modes enabled for this keyboard in kb-k600t.xml (others are commented out
# there). Names come from language/1033.lan ids 501..522.
EFFECTS: tuple[Effect, ...] = (
    Effect(1, "ripple-lr", "Left and right ripples", 71),
    Effect(2, "starry", "Starry dots", 3),
    Effect(3, "ripple-ud", "Up and down ripples", 71),
    Effect(4, "ejection", "Bidirectional ejection", 67),
    Effect(5, "spectrum", "Spectral cycle", 3),
    Effect(6, "kaleidoscope", "Kaleidoscope", 71),
    Effect(7, "static", "Static constant light", 65),
    Effect(8, "breathing", "Overall breathing", 67),
    Effect(9, "cross", "Cross operation", 71),
    Effect(11, "key-breathing", "Single key breathing", 67),
    Effect(12, "scroll", "Jiangshan picture scroll", 67),
    Effect(15, "top-bottom", "Top three, bottom three", 67),
    Effect(16, "rain", "Rain falling pavilion", 67),
    Effect(17, "windmill", "Windmill", 67),
    Effect(18, "sine", "Sine wave", 67),
    Effect(19, "galloping", "Galloping horse", 71),
    Effect(24, "custom", "Custom (per-key colours)", 256),
)
EFFECTS_BY_KEY = {e.key: e for e in EFFECTS}
EFFECTS_BY_MODE = {e.mode: e for e in EFFECTS}

# Fixed palette (vendor UI buttons 0x58..0x5F, colorindex = button id - 0x58)
COLORS: tuple[tuple[str, tuple[int, int, int] | None], ...] = (
    ("red", (255, 0, 0)),
    ("green", (0, 255, 0)),
    ("blue", (0, 0, 255)),
    ("yellow", (255, 255, 0)),
    ("magenta", (255, 0, 255)),
    ("cyan", (0, 255, 255)),
    ("white", (255, 255, 255)),
    ("rainbow", None),
)
COLOR_INDEX = {name: i for i, (name, _) in enumerate(COLORS)}

BRIGHTNESS_RANGE = range(1, 6)   # brightness_max="5"
SPEED_RANGE = range(1, 6)        # speed_max="5"
DIRECTION_RIGHT = 0
DIRECTION_LEFT = 1

SLEEP_TIMES = ("5min", "15min", "30min", "never")      # lan ids 179..182
RESPONSE_TIMES = ("1", "2", "3")                        # lan ids 184..186

POWER_STATES = {0: "unknown", 1: "charging", 2: "on battery", 3: "fully charged"}


class ProtocolError(Exception):
    pass


def build(cmd: int, payload: bytes | list[int] = b"") -> bytes:
    """Return a 64-byte packet: MAGIC, cmd, payload, zero padding."""
    if not 0 <= cmd <= 0xFF:
        raise ValueError(f"command byte out of range: {cmd}")
    payload = bytes(payload)
    if len(payload) > PACKET_LEN - 5:
        raise ValueError(f"payload too long: {len(payload)} > {PACKET_LEN - 5}")
    pkt = MAGIC + bytes((cmd,)) + payload
    return pkt + bytes(PACKET_LEN - len(pkt))


@dataclass
class LightSettings:
    mode: int = 7
    brightness: int = 5
    speed: int = 4
    direction: int = DIRECTION_RIGHT
    color: int = COLOR_INDEX["rainbow"]

    def validate(self) -> None:
        if self.mode not in EFFECTS_BY_MODE:
            raise ValueError(f"unsupported mode {self.mode}")
        if self.brightness not in BRIGHTNESS_RANGE:
            raise ValueError(f"brightness must be 1..5, got {self.brightness}")
        if self.speed not in SPEED_RANGE:
            raise ValueError(f"speed must be 1..5, got {self.speed}")
        if self.direction not in (DIRECTION_LEFT, DIRECTION_RIGHT):
            raise ValueError(f"direction must be 0 or 1, got {self.direction}")
        if not 0 <= self.color < len(COLORS):
            raise ValueError(f"color index must be 0..{len(COLORS) - 1}, got {self.color}")


def light_packet(s: LightSettings) -> bytes:
    s.validate()
    return build(CMD_SET_LIGHT, (s.mode - 1, s.brightness - 1, s.speed - 1, s.direction, s.color))


def status_request() -> bytes:
    return build(CMD_STATUS)


@dataclass
class Status:
    battery: int | None
    power_state: int
    raw: bytes = field(repr=False)

    @property
    def power_state_name(self) -> str:
        return POWER_STATES.get(self.power_state, f"unknown ({self.power_state})")

    @property
    def charging(self) -> bool:
        # vendor app treats state 1 and 3 as "on charger"
        return self.power_state in (1, 3)


def is_reply(data: bytes) -> bool:
    return len(data) >= 5 and data[:4] == MAGIC


def parse_status(data: bytes) -> Status:
    if len(data) != PACKET_LEN:
        raise ProtocolError(f"status reply has length {len(data)}, expected {PACKET_LEN}")
    if not is_reply(data):
        raise ProtocolError(f"status reply lacks magic: {data[:8].hex(' ')}")
    battery = data[5] if data[5] <= 100 else None  # vendor app ignores values > 100
    return Status(battery=battery, power_state=data[6], raw=bytes(data))


def rgb_chunks(leds: dict[int, tuple[int, int, int]] | list[tuple[int, int, int]],
               base: int) -> list[bytes]:
    """Serialise a per-LED colour table into the 6 chunk packets.

    `leds` maps LED index (0..107, the layout's key_index) -> (r, g, b);
    missing LEDs are black.
    """
    if base not in (CUSTOM_CHUNK_BASE, LIVE_CHUNK_BASE):
        raise ValueError("chunk base must be CUSTOM_CHUNK_BASE or LIVE_CHUNK_BASE")
    buf = bytearray(LED_COUNT * 3)
    items = leds.items() if isinstance(leds, dict) else enumerate(leds)
    for idx, rgb in items:
        if not 0 <= idx < LED_COUNT:
            raise ValueError(f"LED index {idx} out of range 0..{LED_COUNT - 1}")
        r, g, b = rgb
        for c in (r, g, b):
            if not 0 <= c <= 255:
                raise ValueError(f"colour component out of range: {rgb}")
        buf[idx * 3:idx * 3 + 3] = bytes((r, g, b))
    return [build(base + i, buf[i * CHUNK_DATA_LEN:(i + 1) * CHUNK_DATA_LEN])
            for i in range(CHUNK_COUNT)]


def sleep_time_packet(index: int) -> bytes:
    if not 0 <= index < len(SLEEP_TIMES):
        raise ValueError(f"sleep index must be 0..{len(SLEEP_TIMES) - 1}")
    return build(CMD_SLEEP_TIME, (index,))


def response_time_packet(index: int) -> bytes:
    if not 0 <= index < len(RESPONSE_TIMES):
        raise ValueError(f"response index must be 0..{len(RESPONSE_TIMES) - 1}")
    return build(CMD_RESPONSE_TIME, (index,))


def fn_switch_packet(enabled: bool) -> bytes:
    return build(CMD_FN_SWITCH, (1 if enabled else 0,))


def parse_hex_color(text: str) -> tuple[int, int, int]:
    t = text.strip().lstrip("#")
    if len(t) == 3:
        t = "".join(c * 2 for c in t)
    if len(t) != 6:
        raise ValueError(f"not a hex colour: {text!r}")
    v = int(t, 16)
    return (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF
