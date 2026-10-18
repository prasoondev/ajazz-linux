"""AK820 Max Plus key layout.

Derived from the vendor layout file app/layouts/kb-k600t.xml (active entries
only). Fields: HID usage code, label, LED index (the vendor "key_index", used
for per-key RGB), row, column, and the vendor UI rectangle (x, y, w, h) in an
800x300 canvas.
"""
from __future__ import annotations

from typing import NamedTuple


class Key(NamedTuple):
    code: int
    label: str
    led: int
    row: int
    col: int
    rect: tuple[int, int, int, int]


KEYS: tuple[Key, ...] = (
    Key(0x29, 'Esc', 15, 0, 0, (29, 41, 34, 34)),
    Key(0x3a, 'F1', 14, 0, 1, (71, 41, 34, 34)),
    Key(0x3b, 'F2', 13, 0, 2, (103, 41, 34, 34)),
    Key(0x3c, 'F3', 12, 0, 3, (136, 41, 34, 34)),
    Key(0x3d, 'F4', 11, 0, 4, (169, 41, 34, 34)),
    Key(0x3e, 'F5', 10, 0, 5, (210, 41, 34, 34)),
    Key(0x3f, 'F6', 9, 0, 6, (243, 41, 34, 34)),
    Key(0x40, 'F7', 8, 0, 7, (276, 41, 34, 34)),
    Key(0x41, 'F8', 7, 0, 8, (307, 41, 34, 34)),
    Key(0x42, 'F9', 6, 0, 9, (350, 41, 34, 34)),
    Key(0x43, 'F10', 5, 0, 10, (383, 41, 34, 34)),
    Key(0x44, 'F11', 4, 0, 11, (416, 41, 34, 34)),
    Key(0x45, 'F12', 3, 0, 12, (448, 41, 34, 34)),
    Key(0x4c, 'Del', 43, 0, 13, (489, 41, 34, 34)),
    Key(0x35, '`~', 16, 1, 0, (30, 81, 34, 34)),
    Key(0x1e, '1!', 17, 1, 1, (63, 81, 34, 34)),
    Key(0x1f, '2@', 18, 1, 2, (95, 81, 34, 34)),
    Key(0x20, '3#', 19, 1, 3, (128, 81, 34, 34)),
    Key(0x21, '4$', 20, 1, 4, (161, 81, 34, 34)),
    Key(0x22, '5%', 21, 1, 5, (194, 81, 34, 34)),
    Key(0x23, '6^', 22, 1, 6, (227, 81, 34, 34)),
    Key(0x24, '7&', 23, 1, 7, (260, 81, 34, 34)),
    Key(0x25, '8*', 24, 1, 8, (292, 81, 34, 34)),
    Key(0x26, '9(', 25, 1, 9, (325, 81, 34, 34)),
    Key(0x27, '0)', 26, 1, 10, (358, 81, 34, 34)),
    Key(0x2d, '-_', 27, 1, 11, (390, 81, 34, 34)),
    Key(0x2e, '=+', 28, 1, 12, (424, 81, 34, 34)),
    Key(0x2a, 'Backspace', 29, 1, 13, (457, 81, 65, 34)),
    Key(0x4a, 'Home', 31, 1, 14, (537, 81, 34, 34)),
    Key(0x2b, 'Tab', 57, 2, 0, (30, 114, 51, 34)),
    Key(0x14, 'Q', 56, 2, 1, (79, 114, 34, 34)),
    Key(0x1a, 'W', 55, 2, 2, (112, 114, 34, 34)),
    Key(0x08, 'E', 54, 2, 3, (144, 114, 34, 34)),
    Key(0x15, 'R', 53, 2, 4, (177, 114, 34, 34)),
    Key(0x17, 'T', 52, 2, 5, (210, 114, 34, 34)),
    Key(0x1c, 'Y', 51, 2, 6, (243, 114, 34, 34)),
    Key(0x18, 'U', 50, 2, 7, (276, 114, 34, 34)),
    Key(0x0c, 'I', 49, 2, 8, (309, 114, 34, 34)),
    Key(0x12, 'O', 48, 2, 9, (341, 114, 34, 34)),
    Key(0x13, 'P', 47, 2, 10, (375, 114, 34, 34)),
    Key(0x2f, '[{', 46, 2, 11, (407, 114, 34, 34)),
    Key(0x30, ']}', 45, 2, 12, (439, 114, 34, 34)),
    Key(0x31, '\\|', 44, 2, 13, (473, 114, 51, 34)),
    Key(0x4b, 'PgUp', 32, 2, 14, (537, 114, 34, 34)),
    Key(0x39, 'CapsLock', 58, 3, 0, (30, 148, 54, 34)),
    Key(0x04, 'A', 59, 3, 1, (88, 148, 34, 34)),
    Key(0x16, 'S', 60, 3, 2, (120, 148, 34, 34)),
    Key(0x07, 'D', 61, 3, 3, (153, 148, 34, 34)),
    Key(0x09, 'F', 62, 3, 4, (186, 148, 34, 34)),
    Key(0x0a, 'G', 63, 3, 5, (219, 148, 34, 34)),
    Key(0x0b, 'H', 64, 3, 6, (252, 148, 34, 34)),
    Key(0x0d, 'J', 65, 3, 7, (284, 148, 34, 34)),
    Key(0x0e, 'K', 66, 3, 8, (317, 148, 34, 34)),
    Key(0x0f, 'L', 67, 3, 9, (351, 148, 34, 34)),
    Key(0x33, ';:', 68, 3, 10, (383, 148, 34, 34)),
    Key(0x34, '\'"', 69, 3, 11, (416, 148, 34, 34)),
    Key(0x28, 'Enter', 70, 3, 12, (449, 148, 74, 34)),
    Key(0x4e, 'PgDn', 41, 3, 13, (537, 146, 34, 34)),
    Key(0xe1, 'Shift', 90, 4, 0, (30, 180, 74, 34)),
    Key(0x1d, 'Z', 89, 4, 1, (103, 180, 34, 34)),
    Key(0x1b, 'X', 88, 4, 2, (137, 180, 34, 34)),
    Key(0x06, 'C', 87, 4, 3, (169, 180, 34, 34)),
    Key(0x19, 'V', 86, 4, 4, (202, 180, 34, 34)),
    Key(0x05, 'B', 85, 4, 5, (235, 180, 34, 34)),
    Key(0x11, 'N', 84, 4, 6, (267, 180, 34, 34)),
    Key(0x10, 'M', 83, 4, 7, (300, 180, 34, 34)),
    Key(0x36, ',<', 82, 4, 8, (333, 180, 34, 34)),
    Key(0x37, '.>', 81, 4, 9, (366, 180, 34, 34)),
    Key(0x38, '/?', 80, 4, 10, (399, 180, 34, 34)),
    Key(0xe5, 'Shift', 79, 4, 11, (432, 180, 54, 34)),
    Key(0x52, '↑', 78, 4, 12, (497, 186, 34, 34)),
    Key(0x4d, 'End', 42, 4, 13, (537, 180, 34, 34)),
    Key(0xe0, 'Ctrl', 91, 5, 0, (31, 212, 42, 34)),
    Key(0xe3, 'Win', 92, 5, 1, (71, 212, 42, 34)),
    Key(0xe2, 'Alt', 93, 5, 2, (111, 212, 42, 34)),
    Key(0x2c, 'Space', 94, 5, 3, (153, 212, 208, 34)),
    Key(0xe6, 'Alt', 95, 5, 4, (357, 212, 34, 34)),
    Key(0xaf, 'Fn', 97, 5, 5, (390, 212, 34, 34)),
    Key(0xe4, 'Ctrl', 98, 5, 6, (424, 212, 34, 34)),
    Key(0x50, '←', 99, 5, 7, (464, 220, 31, 34)),
    Key(0x51, '↓', 100, 5, 8, (496, 220, 31, 34)),
    Key(0x4f, '→', 101, 5, 9, (530, 220, 31, 34)),
)

# Unique, shell-friendly names keyed by HID usage code.
_SPECIAL = {
    0x29: "esc", 0x4C: "del", 0x35: "grave", 0x2D: "minus", 0x2E: "equal", 0x2A: "backspace",
    0x4A: "home", 0x2B: "tab", 0x2F: "lbracket", 0x30: "rbracket", 0x31: "backslash",
    0x4B: "pgup", 0x39: "capslock", 0x33: "semicolon", 0x34: "quote", 0x28: "enter",
    0x4E: "pgdn", 0xE1: "lshift", 0x36: "comma", 0x37: "period", 0x38: "slash",
    0xE5: "rshift", 0x52: "up", 0x4D: "end", 0xE0: "lctrl", 0xE3: "lwin", 0xE2: "lalt",
    0x2C: "space", 0xE6: "ralt", 0xAF: "fn", 0xE4: "rctrl", 0x50: "left", 0x51: "down",
    0x4F: "right",
}


def key_name(code: int) -> str:
    if code in _SPECIAL:
        return _SPECIAL[code]
    if 0x04 <= code <= 0x1D:
        return chr(ord("a") + code - 0x04)
    if 0x1E <= code <= 0x26:
        return str(code - 0x1D)
    if code == 0x27:
        return "0"
    if 0x3A <= code <= 0x45:
        return f"f{code - 0x39}"
    return f"0x{code:02x}"


KEYS_BY_NAME = {key_name(k.code): k for k in KEYS}
KEYS_BY_LED = {k.led: k for k in KEYS}
CANVAS = (800, 300)
