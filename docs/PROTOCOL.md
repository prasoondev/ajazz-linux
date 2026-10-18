# AJAZZ AK820 Max Plus — configuration protocol

Reconstructed from static analysis of the vendor software
(`DeviceDriver.exe`, "AJAZZ AK820 Max Plus 三模RGB版" v1.0.4.6) and checked
against a physical keyboard (firmware bcdDevice 0x0030) over wired USB.

Confidence levels:

* **Verified**: observed working on the hardware (see `hw-test-log.jsonl`).
* **Static**: read directly from the vendor code, not yet exercised on hardware.
* **Inferred**: a reasonable interpretation that is not proven.

Addresses refer to `DeviceDriver.exe` (image base 0x400000).

## 1. Transport

| Item | Value | Evidence | Confidence |
|---|---|---|---|
| Wired keyboard | `1a2c:a036`, "Shinetek Technology AK820" | `lsusb`, `config.xml` mode 0 | Verified |
| 2.4 GHz receiver | `1a2c:8fff`, "2.4 Wireless Device" | `lsusb`, `config.xml` mode 2 | Verified present; protocol not yet tested |
| Bluetooth | not supported by vendor software (no BT mode in `config.xml`) | — | — |
| Config interface | USB interface 0, HID usage page `0xFF02`, usage `0x02` | filter at `0x43fea3` (`UP==0xFF02 && Usage==2`) | Verified |
| Reports | 64-byte input + 64-byte output, **no report IDs** | report descriptor of interface 0 | Verified |
| Host → device | HID output report (Windows `WriteFile`, 65 bytes incl. report-ID 0) | `0x441250`, wrappers `0x43f5e0`/`0x43f900` | Verified |
| Device → host | HID input report (`ReadFile`), app strips report-ID 0 | `0x441330`/`0x441410` | Verified |
| Timing | sleep 100 ms after a write that expects a reply; 500 ms read timeout | `0x43f9d4` | Static |

`HidD_SetFeature`/`IOCTL_HID_GET_FEATURE` paths (`0x43f560`, `0x43f6c0`,
`0x43f740`) exist but are used only for other device families
(`device_type` < 300). This keyboard is `device_type` 301.

Interface map of the wired keyboard:

| Interface | Usage | Purpose |
|---|---|---|
| 0 | `FF02:0002` vendor, 64 B in/out | configuration (this protocol) |
| 1 | `0001:0006` boot keyboard | typing (6KRO) |
| 2 | `0001:0006` keyboard (ID 1, 4), system control (ID 2), consumer (ID 3), vendor `FF01` (ID 6, 3 B in) | NKRO typing, media keys |

The receiver has the same interface 0, plus a mouse collection on interface 2
and the keyboard collections on interface 3.

## 2. Framing

Every packet in both directions:

```
offset 0..3   AA 55 CC 33     magic
offset 4      command
offset 5..63  payload (zero padded)
```

Replies echo the command byte (verified for `0x0E`).

## 3. Commands

| Cmd | Name | Payload | Reply | Evidence | Confidence |
|---|---|---|---|---|---|
| `0x00`–`0x02` | macro data chunk *n* | 54 bytes of a 0x200-byte macro buffer | — | `0x4106b0` | Static |
| `0x04` | key assign | `[5]` layer+1 (1 = base, 2 = Fn), `[6]` source key HID usage, `[7]` target HID usage (0 = default) | — | `0x410590` | Static, test pending |
| `0x07` | set lighting | `[5]` mode−1, `[6]` brightness−1 (0–4), `[7]` speed−1 (0–4), `[8]` direction, `[9]` colour index | — | `0x411130` | **Verified** |
| `0x08` | restore defaults (destructive) | — | — | `0x411270` (followed by full UI refresh) | Static, deliberately not exposed |
| `0x09` | begin RGB stream | — | none observed (vendor waits anyway) | `0x427ad4`, `0x42a052` | Verified (no reply) |
| `0x0A` | unknown | — | — | sent via `0x43f820` from UI control `0x6A` | Unknown, not used |
| `0x0B` | prepare custom mode | — | — | `0x4111fd` | Verified as part of the custom sequence |
| `0x0C` | sleep time | `[5]` 0 = 5 min, 1 = 15 min, 2 = 30 min, 3 = never | — | `0x411d10`, ini key `sleeptime` | Static |
| `0x0D` | key response time | `[5]` gear 0–2 | — | `0x411e50`, ini key `key_responsetime` | Static |
| `0x0E` | status | — | `[5]` battery % (≤100), `[6]` power state | `0x428790`, `0x4100e8` | **Verified** |
| `0x0F` | begin keymap batch | — | — | `0x410140`, sent before a full key upload | Static |
| `0x10` | Fn switch | `[5]` 0/1 | — | `0x418c70`, ini key `fn_switch` | Sent; **no visible effect** in test |
| `0xF0`–`0xF5` | live RGB frame chunk | 54 bytes = 18 LEDs × RGB | — | `0x427b02` (music/screen sync) | **Verified** |
| `0xF6`–`0xFB` | custom-mode RGB chunk (stored) | 54 bytes = 18 LEDs × RGB | — | `0x42a080` | **Verified** |

### 3.1 Lighting (`0x07`)

* Mode numbers and per-mode capabilities come from `layouts/kb-k600t.xml`
  `<info mode= attribute=>`. Attribute bits: `0x01` brightness, `0x02` speed,
  `0x04` direction, `0x40` colour, `0x100` custom, `0x200` music, `0x400`
  screen. **Verified**: all 16 enabled effects (1–9, 11, 12, 15–19) animate as named.
* Brightness 1–5 → byte 0–4. Level 1 is dim, not off. **Verified**
* Speed 1–5 → byte 0–4, higher is faster. **Verified**
* Direction: `1` = right→left ("left" button), `0` = left→right. Up/down
  buttons exist in the skin but are not handled for this device type. **Verified**
* Colour index = vendor button id − 0x58: 0 red, 1 green, 2 blue, 3 yellow,
  4 magenta, 5 cyan, 6 white, 7 rainbow. **Verified**
* The record's `colorful` and `color_value` fields are **not** sent, so
  arbitrary RGB is only possible in per-key custom mode.
* There is no read-back command; the vendor app keeps state in its own
  SQLite DB.

### 3.2 Per-key custom colours (mode 24)

Sequence (`0x411130` → `0x429ed0`), **verified**:

1. `0x07` with mode byte `0x17` (24−1) and the brightness.
2. `0x0B`.
3. *(vendor: `0x09` the first time after a mode change; not required in our tests)*
4. Six packets `0xF6`…`0xFB`, each carrying 54 bytes. Together they form a
   324-byte buffer = 108 LEDs × (R, G, B). The LED index is the layout's
   `key_index`. There is a 3 ms gap between chunks.

### 3.3 Live frames (music / screen sync)

`0x07` mode 22 (`0x15`), then `0x09`, then repeated frames of six chunks
`0xF0`…`0xF5` with the same layout as 3.2. Frames are not stored. When
they stop, the keyboard returns to its stored effect by itself.
**Verified**: 20 fps for 120 s, smooth.

### 3.4 Status (`0x0E`)

Reply `AA 55 CC 33 0E <battery> <state> 00…`. Battery values above 100 are
ignored by the vendor app. State: 0 = no data, 1 = charging, 2 = on battery
(inferred), 3 = fully charged. The vendor app treats 1 and 3 as "charger
connected". At open, the app treats state > 0 as "keyboard online", which
matters for the receiver when the keyboard is off. **Verified** on wired:
`64 03` (100 %, full).

The keyboard may send an additional copy of the status reply a moment later,
so readers should drain stale input before a request.

### 3.5 Key assignment (`0x04`), static analysis

The UI's key-function types (`macro_type` in `t_key_macro_data`) are
indexes of the type list: 2 = key function (HID usage + modifier mask
Ctrl 1 / Shift 2 / Alt 4 / Win 8 in `macro_value2`), 3 = macro, 5–7 = list
selections, 8–11 = launch app / website / text / file. Only the single-byte
`macro_value` is sent in `[7]`, for types other than 0/3/7. Modifier combos
and launch actions are emulated on the host by the vendor's virtual HID
driver (`vhidev`/`vhidflt`). Types 3 and 7 go through the macro path
(`0x4106b0`): three chunks `0x00`–`0x02` of a buffer starting with
`[layer+1, key, …]`. The event encoders are at `0x410c10` and `0x410d80` and
are not yet decoded.

## 4. Assets

| File | Format | Content |
|---|---|---|
| `config.xml` | XML | VID/PID per connection mode, MI_02/MI_03 hints, update URLs |
| `layouts/kb-k600t.xml` | XML | effect list + attributes, 82 keys with HID code, LED index, row/col, UI rect |
| `db/lightlayer_v1.data` | SQLite 3 | `t_light_frames` (371 076 rows): pre-rendered animation frames for the on-screen preview only |
| `language/*.lan` | UTF-16 INI | UI strings (effect names 501–522 etc.) |
| `firmware/700N(0X3B4F)defineV9_20230316.exe` | PE32 | separate firmware updater; **not executed or analysed for flashing** |
| `DeviceDriver.lib`, `XYUI.lib` | `ar` import libraries | link stubs, no code |
| `XYUI.dll` | PE32 DLL | UI toolkit (skinning, sliders, colour buttons) |
