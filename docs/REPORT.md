# Reverse-engineering report: AJAZZ AK820 Max Plus on Linux

## Summary

The Windows configuration app talks to the keyboard through ordinary HID
input and output reports on a dedicated vendor interface: USB interface 0,
usage page `0xFF02`. There is no custom driver, no feature report and no
checksum. Every packet is 64 bytes: `AA 55 CC 33 <cmd> <payload>`. That makes
a pure userspace implementation over `/dev/hidraw` possible without detaching
the kernel's keyboard driver. The protocol was recovered by static analysis
alone; no Windows VM or USB capture was needed. It was then confirmed on the
real keyboard one command at a time.

## Method

1. **Inventory**: `file`, `strings`/`strings -el`, `objdump -p`, `ar t`,
   SQLite inspection, and XML/INI parsing of the extracted installer
   (`ajazz-files/app/`, left unmodified).
2. **Import analysis**: `HID.DLL` is imported only for `GetAttributes`,
   `GetPreparsedData`, `GetCaps` and `GetHidGuid`. `HidD_SetFeature` and
   `HidD_GetFeature` are resolved dynamically. `WriteFile`, `ReadFile` and
   `DeviceIoControl(IOCTL_HID_GET_FEATURE)` are imported directly. This
   pointed to an embedded copy of hidapi (Windows).
3. **Disassembly**: Python + capstone (`re-tools/xref.py`), which finds
   cross-references to strings and imports. Steps:
   * traced `HidP_GetCaps` to the device filter (`UP 0xFF02 / usage 2`);
   * traced `WriteFile` and `ReadFile` to the send/receive wrappers;
   * scanned every store of the constant `0x33CC55AA` to list all command
     builders, then named each one from nearby strings (`sleeptime`,
     `key_responsetime`, `fn_switch`), its SQLite queries, and UI control IDs;
   * mapped struct offsets with the SQLite column order (the
     `SELECT * FROM t_light_data` loader at `0x4067c0`).
4. **Hardware verification**: `tools/hwtest.py` sends one known packet at a
   time, asks the operator what the keyboard shows, and logs packets and
   answers to `docs/hw-test-log.jsonl`.

Tools installed: a Python venv with `capstone` and `pefile`, outside the
project. No system changes other than the udev rule.

## File inventory

| File | Type | Finding |
|---|---|---|
| `DeviceDriver.exe` (1.6 MB) | PE32 i386 GUI, MFC | entire protocol, embedded hidapi + SQLite |
| `DeviceDriver.lib` | `ar` archive | import library (link stubs only) |
| `XYUI.dll` / `XYUI.lib` | PE32 DLL / import lib | skinning UI toolkit, no device I/O |
| `config.xml` | XML | `1A2C:A036 MI_02` (USB), `1A2C:8FFF MI_03` (2.4G), device_type 301 |
| `layouts/kb-k600t.xml` | XML | effects + attribute flags, 82 keys (HID code, LED index, geometry) |
| `db/lightlayer_v1.data` | SQLite 3 | 371 076 pre-rendered preview frames, UI only |
| `language/1033.lan`, `2052.lan` | UTF-16 INI | English/Chinese UI strings |
| `firmware/700N(0X3B4F)defineV9_20230316.exe` | PE32 | firmware updater; not run, not used |
| `mfc140u.dll`, `msvcp140.dll`, `vcruntime140.dll` | MS runtime | — |
| `skins/`, `font/` | PNG/OTF | UI assets |

Note: the `MI_02` hint in `config.xml` is **misleading**. The app actually
selects the collection by usage (`0xFF02:2`), which is interface **0**.

## USB / HID identification (wired)

```
1a2c:a036  "Shinetek Technology" / "AK820"  bcdDevice 0x0030  full speed
 if0  HID   EP 0x04 OUT, 0x84 IN   FF02:0002  64B in / 64B out, no report IDs  <- config
 if1  HID boot keyboard  EP 0x81   0001:0006  6KRO
 if2  HID               EP 0x83   0001:0006 NKRO (ID1, ID4), 0001:0080 system (ID2),
                                   000C:0001 consumer (ID3), FF01:FF01 (ID6, 3B in)
1a2c:8fff  "2.4 Wireless Device"  bcdDevice 0x0006
 if0  FF02:0002 (same as above)   if1 keyboard   if2 mouse   if3 = keyboard if2 layout
```

Interface 0 report descriptor:
`06 02 FF 09 02 A1 01 09 03 15 00 26 FF 00 75 08 95 40 81 00 09 04 15 00 26 FF 00 75 08 95 40 91 00 C0`
(vendor page FF02, usage 2, 64-byte input report (usage 3), 64-byte output report (usage 4)).

## Hardware test results

Wired USB, 2026-10-18 (raw log: `hw-test-log.jsonl`):

| Test | Packets | Result |
|---|---|---|
| Discovery without root | — | ✓ correct interface on keyboard and receiver |
| udev rule scope | — | ✓ only hidraw0 (kbd if0) and hidraw7 (receiver if0) get ACLs; re-applied after replug |
| Status | `0E` → `0E 64 03` | ✓ 100 %, fully charged (on cable) |
| Static red | `07 06 04 03 00 00` | ✓ |
| Brightness 1–5 | `07 06 0b 03 00 06`, b = 0–4 | ✓ monotonic; level 1 dim, not off |
| Colours 0–7 | `07 06 04 03 00 c` | ✓ all eight as expected |
| Speed | breathing, speed 0 vs 4 | ✓ 4 faster |
| Direction | ripple, dir 1 / 0 | ✓ 1 = right→left, 0 = left→right |
| 16 effects | modes 1–9, 11, 12, 15–19 | ✓ all animate as named |
| Custom per-key | `07 17…`, `0B`, `F6…FB` | ✓ pattern and full-board gradient exactly right (LED map correct) |
| Live frames | `07 15…`, `09`, `F0…F5` × 2400 @ 20 fps | ✓ smooth; reverts to stored effect when stopped |
| Music sync (audio) | live frames | pending user test |
| Fn switch | `10 01` / `10 00` | ✗ no observable change in F-row behaviour |
| Key remap | `04 01 4E 04`, then `04 01 4E 00` | pending |
| Sleep / response time | `0C`, `0D` | not tested (no easy observable) |
| 2.4 GHz receiver | — | pending |

## Open questions / next steps

1. **2.4 GHz**: run `tools/hwtest.py --device /dev/hidraw7` with the cable
   unplugged. Does the receiver forward `0x07`, and what does `0x0E` report?
2. **Fn switch (`0x10`)**: no visible effect. It may only change which layer
   the vendor UI edits, or need an OS-mode switch first. Left as experimental.
3. **Key remap**: confirm `0x04` on hardware. Find out how "disable key"
   (type 1) and the multimedia / function-key list indices (types 5–7) are
   encoded.
4. **Macros**: decode the event encoders at `0x410c10` (type 3) and `0x410d80`
   (type 7).
5. **`0x0A`, `0x0F`**: purposes unconfirmed (`0x0F` precedes a full keymap upload).
6. **Screen-colour sync** (mode 23): uses the same live-frame path as music,
   so it would only need a screen-capture source (e.g. the xdg-desktop-portal
   ScreenCast portal + PipeWire).
7. **Bluetooth**: when paired, check whether the vendor interface is exposed
   over BLE HID (`bus 0005`). The vendor software doesn't support it.
