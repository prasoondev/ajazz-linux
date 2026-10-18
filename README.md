# ajazzctl

An unofficial Linux tool for the **AJAZZ AK820 Max Plus** tri-mode RGB keyboard, with a
command-line interface and a GTK4 GUI. It replaces the Windows-only vendor driver. The
protocol was reverse-engineered from that driver (see [docs/PROTOCOL.md](docs/PROTOCOL.md)).

Typing is untouched: Linux's normal HID driver keeps handling the keyboard, and
ajazzctl only talks to the separate vendor configuration interface.

## Feature status

| Feature | CLI | GUI | Status |
|---|---|---|---|
| Detect keyboard / receiver | `detect` | ✓ | verified |
| Battery and charge state | `info` | ✓ | verified (wired) |
| 16 lighting effects | `lighting set/effect` | ✓ | verified |
| Brightness, speed, direction, 8 colours | `lighting …` | ✓ | verified |
| Per-key RGB (custom mode, stored on the keyboard) | `lighting custom` | ✓ painter | verified |
| Music sync (spectrum / pulse / wave) | `music` | ✓ | live streaming verified; audio-reactive styles being tested |
| Key remap (single key → key) | `keymap set/reset` | — | **experimental**, hardware test pending |
| Sleep timeout, key response time | `settings sleep/response` | ✓ | sent, effect not verified |
| Fn switch | `settings fn-switch` | ✓ | sent, **no visible effect observed** |
| Macros, modifier combos, launch actions | — | — | not implemented (see below) |
| 2.4 GHz receiver | auto | auto | detected; to be tested |
| Bluetooth | — | — | not supported (the vendor software doesn't support it either) |
| Firmware update | — | — | intentionally not supported |

The keyboard cannot report its lighting or settings back. ajazzctl remembers
the last values it sent in `~/.config/ajazzctl/state.json`. If you change things
with Fn shortcuts on the keyboard, that file will be out of date.

## Install (Arch / CachyOS)

```sh
cd packaging
makepkg -si          # builds, runs the unit tests, installs ajazzctl + udev rule + desktop entry
sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=hidraw
```

Optional dependencies: `python-gobject gtk4 libadwaita` for the GUI, and
`python-numpy libpulse` for music sync.

To run from the source tree without installing, install the udev rule yourself:

```sh
sudo install -m644 udev/70-ajazz-ak820.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=hidraw
python3 -m ajazzctl --help
python3 -m ajazzctl.gui
```

### About the udev rule

It gives the logged-in user (`uaccess`) access to **USB interface 0 only**,
the vendor configuration interface of `1a2c:a036` and `1a2c:8fff`. The
keyboard's typing interfaces stay root-only, so no program can read your
keystrokes through this rule. You don't need to run anything as root.

## CLI examples

```sh
ajazzctl detect                         # list interfaces, mark the config one
ajazzctl info                           # battery / charge state
ajazzctl lighting effects               # effects and the options each supports
ajazzctl lighting set -e breathing -c cyan -b 4 -s 2
ajazzctl lighting effect galloping
ajazzctl lighting brightness 3
ajazzctl lighting custom --all 101010 -k esc=ff0000 -k w=00ff00 -k a=00ff00 -k s=00ff00 -k d=00ff00
ajazzctl keys                           # key names for `custom` and `keymap`
ajazzctl music --style spectrum         # Ctrl-C restores the previous lighting
ajazzctl music --style pulse --color ff0080 --sensitivity 1.5
ajazzctl keymap set capslock esc        # experimental
ajazzctl keymap reset capslock
ajazzctl --json info                    # machine-readable output
ajazzctl -v lighting effect static      # print raw packets
```

`--device /dev/hidrawN` picks a specific interface. By default the wired
keyboard is used if present, otherwise the receiver.

## GUI

`ajazzctl-gui` (or **AJAZZ Keyboard** in the app menu) is a GTK4 / libadwaita app:

* **Lighting**: a gallery of all 16 effects with animated previews, a live preview of
  the whole board, and controls for brightness, speed, direction and colour. Changes
  apply immediately.
* **Per-key RGB**: paint keys on a drawing of the board with paint, erase and
  eyedropper tools, a palette plus recent colours, presets (rainbow, gradient,
  gaming) and undo/redo. *Live preview on keyboard* mirrors your edits on the
  real keyboard as you paint; *Save to Keyboard* stores them.
* **Music Sync**: audio-reactive lighting (spectrum, pulse, wave) with an
  on-screen mirror of the keyboard and a level meter.
* **Key Remap**: click a key, then pick a target in a searchable popover. Base
  and Fn layers are supported. (experimental)
* **Settings**: sleep and response time, device info, theme (System / Light /
  Dark), launch at login, keep running in the tray, and start music sync on login.

**Tray**: closing the window keeps the app running in the system tray, where
music sync keeps going. Left-click the tray icon to show or hide the window;
right-click for *Open*, *Music sync* and *Quit*. The tray uses
StatusNotifierItem, which works natively on KDE Plasma and on GNOME with the
AppIndicator extension. Without a tray host, closing the window quits the app.

**Autostart**: *Settings → Launch at login* writes
`~/.config/autostart/io.github.ajazzctl.desktop`, which starts the app hidden in
the tray (`ajazzctl-gui --hidden`).

When run from a source checkout, the app installs a per-user launcher and icon
(`~/.local/share/applications`, `~/.local/share/icons`). Wayland compositors need
these to show the right taskbar icon.

Keyboard shortcuts: `Ctrl+1`…`Ctrl+5` switch pages, `Ctrl+Z` / `Ctrl+Shift+Z`
undo and redo in the per-key painter, `Ctrl+Q` quits.

**Development**: `AJAZZCTL_FAKE=1` runs the CLI and GUI against a simulated
keyboard, so no hardware is touched.

## Not implemented, and why

* **Macros**: the upload path is known (three 54-byte chunks), but the event
  encoding (`0x410c10`/`0x410d80` in the vendor binary) is not decoded yet.
  Sending a wrong encoding would write garbage to the keyboard.
* **Modifier combos, launch app/website/text**: the vendor app does these in
  software through its own Windows virtual-HID driver, not in the keyboard.
  On Linux, use your desktop's shortcut settings or a remapper such as `keyd`.
* **Restore factory defaults** (`0x08`): identified, but left out because it
  is destructive and unnecessary. The keyboard's own reset shortcut still works.

## Tests

```sh
python3 -m unittest discover -s tests -t .     # protocol/parsing/discovery, no hardware needed
python3 tools/hwtest.py --only brightness,color # interactive hardware checks, logged to docs/hw-test-log.jsonl
```

## Files

```
ajazzctl/protocol.py   packet building/parsing (pure, unit-tested)
ajazzctl/device.py     sysfs discovery, hidraw transport, Keyboard API
ajazzctl/layout.py     82-key layout: HID codes, LED indices, geometry
ajazzctl/music.py      audio capture, FFT, frame renderers
ajazzctl/state.py      ~/.config/ajazzctl/state.json
ajazzctl/cli.py        `ajazzctl`
ajazzctl/preview.py    on-screen effect previews
ajazzctl/desktop.py    launcher entry, icon, autostart
ajazzctl/gui/          `ajazzctl-gui` (GTK4 + libadwaita): window, keyboard widget, tray, worker
docs/PROTOCOL.md       protocol specification with evidence
docs/REPORT.md         reverse-engineering report, inventory, test results
udev/                  access rule
packaging/             PKGBUILD, desktop entry
tools/                 hardware test scripts
```

Not affiliated with AJAZZ. Use at your own risk.
