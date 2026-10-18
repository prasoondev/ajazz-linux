import unittest.mock
import os
import tempfile
import unittest
from pathlib import Path

from ajazzctl import device as D
from ajazzctl import layout
from ajazzctl import protocol as P


class FakeTransport(D.Transport):
    """Replies queued in `on_write` are delivered only after the next write."""

    def __init__(self, on_write=()):
        self.sent = []
        self.on_write = list(on_write)
        self.inbox = []

    def write(self, packet):
        assert len(packet) == P.PACKET_LEN
        self.sent.append(bytes(packet))
        if self.on_write:
            self.inbox.extend(self.on_write.pop(0))

    def read(self, timeout):
        return self.inbox.pop(0) if self.inbox else None


def reply(cmd, *payload):
    return P.build(cmd, payload)


class BuildTests(unittest.TestCase):
    def test_framing(self):
        pkt = P.build(0x0E)
        self.assertEqual(len(pkt), 64)
        self.assertEqual(pkt[:5], bytes.fromhex("aa55cc330e"))
        self.assertEqual(pkt[5:], bytes(59))

    def test_payload_too_long(self):
        with self.assertRaises(ValueError):
            P.build(0x07, bytes(60))

    def test_light_packet_static_red(self):
        s = P.LightSettings(mode=7, brightness=5, speed=4, direction=0, color=0)
        self.assertEqual(P.light_packet(s)[:10], bytes.fromhex("aa55cc33 07 06 04 03 00 00"))

    def test_light_packet_offsets(self):
        s = P.LightSettings(mode=1, brightness=1, speed=1, direction=P.DIRECTION_LEFT, color=7)
        self.assertEqual(P.light_packet(s)[4:10], bytes((0x07, 0, 0, 0, 1, 7)))

    def test_light_validation(self):
        for bad in (dict(mode=10), dict(mode=0), dict(brightness=0), dict(brightness=6),
                    dict(speed=0), dict(direction=2), dict(color=8)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                P.light_packet(P.LightSettings(**bad))

    def test_settings_packets(self):
        self.assertEqual(P.sleep_time_packet(3)[4:6], b"\x0c\x03")
        self.assertEqual(P.response_time_packet(0)[4:6], b"\x0d\x00")
        self.assertEqual(P.fn_switch_packet(True)[4:6], b"\x10\x01")
        self.assertEqual(P.fn_switch_packet(False)[4:6], b"\x10\x00")
        with self.assertRaises(ValueError):
            P.sleep_time_packet(4)
        with self.assertRaises(ValueError):
            P.response_time_packet(3)

    def test_key_assign(self):
        self.assertEqual(P.key_assign_packet(0, 0x39, 0x29)[4:8], bytes((0x04, 1, 0x39, 0x29)))
        self.assertEqual(P.key_assign_packet(1, 0x3A, 0)[4:8], bytes((0x04, 2, 0x3A, 0)))
        for bad in ((2, 4, 4), (0, 0, 4), (0, 4, 256)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                P.key_assign_packet(*bad)
        self.assertEqual(P.HID_NAMES["f13"], 0x68)
        self.assertEqual(P.HID_NAMES["0"], 0x27)

    def test_rgb_chunks(self):
        chunks = P.rgb_chunks({0: (1, 2, 3), 18: (4, 5, 6), 107: (7, 8, 9)}, P.CUSTOM_CHUNK_BASE)
        self.assertEqual(len(chunks), 6)
        self.assertEqual([c[4] for c in chunks], list(range(0xF6, 0xFC)))
        self.assertEqual(chunks[0][5:8], b"\x01\x02\x03")
        self.assertEqual(chunks[1][5:8], b"\x04\x05\x06")      # LED 18 starts chunk 2
        self.assertEqual(chunks[5][5 + 51:5 + 54], b"\x07\x08\x09")  # last LED
        self.assertEqual(chunks[5][59:], bytes(5))

    def test_rgb_chunks_live_base(self):
        self.assertEqual(P.rgb_chunks({}, P.LIVE_CHUNK_BASE)[0][4], 0xF0)

    def test_rgb_chunks_validation(self):
        with self.assertRaises(ValueError):
            P.rgb_chunks({108: (0, 0, 0)}, P.CUSTOM_CHUNK_BASE)
        with self.assertRaises(ValueError):
            P.rgb_chunks({0: (256, 0, 0)}, P.CUSTOM_CHUNK_BASE)
        with self.assertRaises(ValueError):
            P.rgb_chunks({}, 0x00)

    def test_hex_color(self):
        self.assertEqual(P.parse_hex_color("#ff8000"), (255, 128, 0))
        self.assertEqual(P.parse_hex_color("0f0"), (0, 255, 0))
        with self.assertRaises(ValueError):
            P.parse_hex_color("12345")


class ParseTests(unittest.TestCase):
    def test_status(self):
        st = P.parse_status(reply(0x0E, 87, 1))
        self.assertEqual(st.battery, 87)
        self.assertEqual(st.power_state_name, "charging")
        self.assertTrue(st.charging)

    def test_status_battery_out_of_range(self):
        self.assertIsNone(P.parse_status(reply(0x0E, 200, 2)).battery)

    def test_status_bad_length(self):
        with self.assertRaises(P.ProtocolError):
            P.parse_status(b"\xaa\x55\xcc\x33\x0e")

    def test_status_bad_magic(self):
        with self.assertRaises(P.ProtocolError):
            P.parse_status(bytes(64))


class KeyboardTests(unittest.TestCase):
    def test_status_roundtrip_skips_noise(self):
        t = FakeTransport([[bytes(64), reply(0x07), reply(0x0E, 55, 2)]])
        t.inbox = [reply(0x0E, 99, 3)]  # stale packet must be drained, not returned
        kb = D.Keyboard(t)
        st = kb.status()
        self.assertEqual(st.battery, 55)
        self.assertEqual(t.sent, [P.status_request()])

    def test_status_timeout(self):
        kb = D.Keyboard(FakeTransport())
        kb.REPLY_TIMEOUT = kb.REPLY_DELAY = 0.01
        with self.assertRaises(D.DeviceError):
            kb.status()

    def test_custom_sequence(self):
        t = FakeTransport()
        D.Keyboard(t).set_custom_colors({15: (255, 0, 0)}, brightness=3)
        self.assertEqual([p[4] for p in t.sent], [0x07, 0x0B] + list(range(0xF6, 0xFC)))
        self.assertEqual(t.sent[0][5:7], bytes((23, 2)))     # mode 24 -> 0x17, brightness 3 -> 2
        self.assertEqual(t.sent[2][5 + 45:5 + 48], b"\xff\x00\x00")


class LayoutTests(unittest.TestCase):
    def test_unique(self):
        self.assertEqual(len(layout.KEYS), 82)
        self.assertEqual(len({k.led for k in layout.KEYS}), 82)
        self.assertEqual(len(layout.KEYS_BY_NAME), 82)
        self.assertTrue(all(0 <= k.led < P.LED_COUNT for k in layout.KEYS))

    def test_names(self):
        self.assertEqual(layout.KEYS_BY_NAME["esc"].led, 15)
        self.assertEqual(layout.KEYS_BY_NAME["a"].code, 0x04)
        self.assertEqual(layout.KEYS_BY_NAME["f12"].code, 0x45)


class DiscoveryTests(unittest.TestCase):
    VENDOR_DESC = bytes.fromhex("0602ff0902a1010903150026ff007508954081000904150026ff00750895409100c0")
    KBD_DESC = bytes.fromhex("05010906a101050719e029e7c0")

    def make_node(self, root, name, hid_id, iface, desc):
        real = Path(root) / "devices" / f"3-1.1:1.{iface}" / "0003:1A2C:A036.0001" / "hidraw" / name
        (real / "device").mkdir(parents=True)
        (real / "device" / "uevent").write_text(f"HID_ID={hid_id}\nHID_NAME=Test AK820\n")
        (real / "device" / "report_descriptor").write_bytes(desc)
        cls = Path(root) / "class"
        cls.mkdir(exist_ok=True)
        os.symlink(real, cls / name)
        return cls

    def test_first_usage(self):
        self.assertEqual(D.first_usage(self.VENDOR_DESC), (0xFF02, 0x02))
        self.assertEqual(D.first_usage(self.KBD_DESC), (0x01, 0x06))
        self.assertEqual(D.first_usage(b""), (None, None))

    def test_selects_vendor_interface_only(self):
        with tempfile.TemporaryDirectory() as root:
            self.make_node(root, "hidraw5", "0003:00001A2C:0000A036", 1, self.KBD_DESC)
            cls = self.make_node(root, "hidraw6", "0003:00001A2C:0000A036", 0, self.VENDOR_DESC)
            self.make_node(root, "hidraw7", "0003:00001234:0000A036", 0, self.VENDOR_DESC)
            found = D.find_keyboards(cls)
            self.assertEqual([n.name for n in found], ["hidraw6"])
            self.assertEqual(found[0].interface, 0)
            self.assertEqual(found[0].connection, "wired")


if __name__ == "__main__":
    unittest.main()


class PreviewTests(unittest.TestCase):
    def test_every_effect_renders_all_keys(self):
        from ajazzctl import preview
        for e in P.EFFECTS:
            if e.mode == P.MODE_CUSTOM:
                continue
            for t in (0.0, 0.37, 2.5):
                f = preview.frame(P.LightSettings(mode=e.mode, color=3), t)
                self.assertEqual(len(f), 82, e.key)
                self.assertTrue(all(0 <= c <= 255 for rgb in f.values() for c in rgb), e.key)

    def test_simulated_device(self):
        with unittest.mock.patch.dict(os.environ, {"AJAZZCTL_FAKE": "1"}):
            kb = D.Keyboard.open()
            self.assertEqual(kb.status().battery, 87)
