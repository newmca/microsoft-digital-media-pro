# Technical notes

The hardware and desktop facts the code relies on, and how each was established.
Measured on Fedora 44, kernel 7.3.4, KDE Plasma 6.8.3 (Wayland), Qt 6.11, with a
real keyboard (USB 045E:00B0), unless marked otherwise.

## The keyboard

- Two USB HID interfaces. Interface 0 is the boot keyboard (typing). Interface 1
  carries a Consumer Control collection (report 1) and a System Control
  collection (report 3). Every special key is on interface 1.
- Report 1 also holds vendor usages on page `0xff00`. `0xff05` is a 5-bit field,
  one bit per My Favorites key 1-5 (read from the HID report descriptor in
  `/sys/bus/hid/devices/0003:045E:00B0.*/report_descriptor`).
- Scancodes for the keys marked `verified` in `src/dmpkeys/core/keys.py` were read
  as `MSC_SCAN` events. The rest are the standard HID usages for those functions
  and are unconfirmed; the app's Detect dialog confirms them.

## Favorites 1-5 need hid-microsoft

`hid-generic` has no mapping for `0xff00:0xff05` and drops it, so keys 1-5 send
nothing. `hid-microsoft`'s MS_ERGONOMY quirk decodes the field into KEY_F14..F18.
Its device table (read out of the installed module's `ms_devices` symbol) lists
the sibling Digital Media keyboard 045E:00B4 with `driver_data 0x2`
(MS_ERGONOMY), but not 00B0.

Fix, applied at runtime by a udev rule: write `0003 045E 00B0 2` to
`/sys/bus/hid/drivers/microsoft/new_id` (dynamic id with that driver_data), then
move interface 1 from hid-generic to hid-microsoft. Notes:

- `hid-generic` is usually built in (`CONFIG_HID_GENERIC=y`), so it claims the
  keyboard before the root filesystem's rules exist. The rule has to fire on the
  coldplug replay (`ACTION=="add"` with `DRIVER=="hid-generic"`) as well as on
  `bind`.
- Writing `new_id` itself attaches matching *unbound* devices. If the id is
  already registered, nothing auto-attaches and an explicit `bind` is needed.
- A first version rebound both interfaces from two concurrent udev runs. One of
  them failed (exit 1) and left interface 0 on hid-generic. The shipped rule
  matches only interface 1 (`ENV{HID_PHYS}=="*/input1"`) and serializes with
  `flock`, so a failure can never take typing down.
- Expected but not verified on hardware: with the dynamic id registered,
  hid-generic stops matching the device (`hid_generic_match` defers to any
  other driver that matches), so after a replug both interfaces go straight to
  hid-microsoft. Typing on interface 0 under hid-microsoft was verified.
- The proper fix is a one-line kernel patch adding 0x00b0 with MS_ERGONOMY to
  `drivers/hid/hid-microsoft.c`.

## Keys the desktop can't see

X11/XKB keycodes are evdev codes + 8 and stop at 255, so kernel keys above 247
have no keysym, and no desktop can bind them, on Wayland too (XKB keymaps).
On this keyboard that covers the zoom slider (KEY_ZOOMIN/OUT, 418/419), My
Pictures (KEY_IMAGES, 442), My Music (KEY_AUDIO, 392), Spell (KEY_SPELLCHECK,
432) and Log Off (KEY_LOGOFF, 433). The app remaps those scancodes with a udev
hwdb file onto spare kernel keys that have a free keysym (`SPARE_KEYS` in
`plan.py`).

Applying an hwdb change took `systemd-hwdb update`, `udevadm control --reload`
*and* `udevadm trigger --action=change` on the event node. A plain trigger left
the old keymap in place.

## KDE Plasma 6

- Global shortcuts go through `org.kde.kglobalaccel` on the session bus. On
  Plasma 6 Wayland that service lives inside `kwin_wayland`, so it can't be
  restarted to reread `kglobalshortcutsrc`; edits must go through D-Bus.
- Shortcuts are Qt key codes. The kernel name doesn't matter, and neither does
  the keysym's spelling. KEY_F14 becomes the keysym XF86Launch5
  (xkeyboard-config `inet(evdev)`: `<FK14>` to `<FK18>` map to XF86Launch5-9), which
  Qt maps to Key_Launch5. Binding "F14" silently never fires.
  `data/keycodes.json` is generated from the real keymap and Qt's compiled
  keysym table (`tools/gen_keycodes.py`).
- `setForeignShortcutKeys` stores keys for a newly registered `.desktop`
  launcher but leaves it inactive, so KWin never grabs the key and pressing it
  does nothing until the next login. `setShortcutKeys` with
  `SetPresent|NoAutoloading` (flags 6) makes it active immediately.
- Launching a folder or a command needs a `.desktop` file. System Settings
  creates `net.local.*.desktop` files for command shortcuts; the app creates
  `net.local.dmpkeys-<key>.desktop` the same way, then runs `kbuildsycoca6`.
- `globalShortcutsByKey` also returns each action's default keys. Import skips
  bindings that are KDE's own defaults (e.g. Calculator → KCalc) so Reset never
  removes them.

## GNOME (untested)

Bindings are custom keybindings under
`org.gnome.settings-daemon.plugins.media-keys`, bound to the bare keysym name.
An earlier GNOME setup on the same keyboard found that bindings on
XF86Launch1-4 were accepted but never fired. The favorites arrive as
XF86Launch5-9 and may be affected the same way.

## Brightness on external monitors (related)

The slider preset "Brightness" sends KEY_BRIGHTNESSUP/DOWN. On Plasma 6, those
step every display KWin can dim. That's DDC/CI monitors, plus any monitor with
DDC/CI disallowed (`kscreen-doctor output.<name>.ddcCi.disallow`), which KWin
then dims in software. A monitor that advertises DDC/CI but doesn't answer
shows as "Brightness control: unsupported" until disallowed.
