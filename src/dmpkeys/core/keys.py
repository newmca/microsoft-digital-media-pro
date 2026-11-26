"""The keyboard's special keys.

Scancodes are HID usages as the kernel reports them in MSC_SCAN:
0x000c_xxxx = Consumer page (interface 1, "Consumer Control" node),
0x0001_xxxx = Generic Desktop / System Control.

`verified` means the scancode and kernel key were measured on a real 045E:00B0
keyboard. Unverified entries use the standard HID usage for that function and
the kernel's default mapping (drivers/hid/hid-input.c); confirm them with
Detect in the app before relying on them.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

VENDOR_ID = 0x045E
PRODUCT_ID = 0x00B0
DEVICE_NAME = "Microsoft Digital Media Pro Keyboard"
HWDB_MATCH = "evdev:input:b0003v045Ep00B0*"


class Group(str, Enum):
    SLIDER = "slider"
    FAVORITES = "favorites"
    LAUNCH = "launch"
    MEDIA = "media"
    FLOCK = "flock"
    SYSTEM = "system"
    CUSTOM = "custom"


GROUP_LABELS = {
    Group.SLIDER: "Zoom slider",
    Group.FAVORITES: "My Favorites",
    Group.LAUNCH: "Launch keys",
    Group.MEDIA: "Media keys",
    Group.FLOCK: "F Lock keys",
    Group.SYSTEM: "System",
    Group.CUSTOM: "Detected keys",
}


@dataclass(frozen=True)
class KeyDef:
    id: str
    label: str
    group: Group
    scancode: int | None   # None: no scancode, cannot be remapped with hwdb
    native: str            # kernel key name it produces by default
    verified: bool
    needs_hid_microsoft: bool = False
    note: str = ""

    @property
    def hwdb_remappable(self) -> bool:
        return self.scancode is not None

    @property
    def scancode_hex(self) -> str:
        return f"{self.scancode:x}" if self.scancode is not None else ""


def _k(id, label, group, scancode, native, verified, **kw) -> KeyDef:
    return KeyDef(id, label, group, scancode, native, verified, **kw)


_FAV_NOTE = ("Reported through a vendor usage (0xff00:0xff05) that only the hid-microsoft driver "
             "decodes. Needs the favorites fix; the key it sends is fixed (F14-F18) and cannot be "
             "remapped, only bound to an action.")

KEYS: tuple[KeyDef, ...] = (
    _k("slider_up", "Zoom slider up", Group.SLIDER, 0x0C022D, "zoomin", True),
    _k("slider_down", "Zoom slider down", Group.SLIDER, 0x0C022E, "zoomout", True),

    _k("fav_star", "My Favorites ★", Group.FAVORITES, 0x0C0182, "bookmarks", True),
    *(_k(f"fav{n}", f"Favorite {n}", Group.FAVORITES, None, f"f{13 + n}", True,
         needs_hid_microsoft=True, note=_FAV_NOTE) for n in range(1, 6)),

    _k("my_documents", "My Documents", Group.LAUNCH, 0x0C01A7, "documents", True),
    _k("my_pictures", "My Pictures", Group.LAUNCH, 0x0C01B6, "images", True),
    _k("my_music", "My Music", Group.LAUNCH, 0x0C01B7, "audio", True),
    _k("mail", "Mail", Group.LAUNCH, 0x0C018A, "mail", True),
    _k("web_home", "Web/Home", Group.LAUNCH, 0x0C0223, "homepage", True),
    _k("messenger", "Messenger", Group.LAUNCH, 0x0C0199, "chat", True),
    _k("calculator", "Calculator", Group.LAUNCH, 0x0C0192, "calc", False),

    _k("mute", "Mute", Group.MEDIA, 0x0C00E2, "mute", False),
    _k("volume_down", "Volume down", Group.MEDIA, 0x0C00EA, "volumedown", False),
    _k("volume_up", "Volume up", Group.MEDIA, 0x0C00E9, "volumeup", False),
    _k("play_pause", "Play/Pause", Group.MEDIA, 0x0C00CD, "playpause", False),
    _k("stop", "Stop", Group.MEDIA, 0x0C00B7, "stopcd", False),
    _k("previous", "Previous track", Group.MEDIA, 0x0C00B6, "previoussong", False),
    _k("next", "Next track", Group.MEDIA, 0x0C00B5, "nextsong", False),

    _k("help", "Help (F1)", Group.FLOCK, 0x0C0095, "help", False),
    _k("undo", "Undo (F2)", Group.FLOCK, 0x0C021A, "undo", False),
    _k("redo", "Redo (F3)", Group.FLOCK, 0x0C0279, "redo", False),
    _k("new", "New (F4)", Group.FLOCK, 0x0C0201, "new", False),
    _k("open", "Open (F5)", Group.FLOCK, 0x0C0202, "open", False),
    _k("close", "Close (F6)", Group.FLOCK, 0x0C0203, "close", False),
    _k("reply", "Reply (F7)", Group.FLOCK, 0x0C0289, "reply", False),
    _k("forward", "Fwd (F8)", Group.FLOCK, 0x0C028B, "forwardmail", False),
    _k("send", "Send (F9)", Group.FLOCK, 0x0C028C, "send", False),
    _k("spell", "Spell (F10)", Group.FLOCK, 0x0C01AB, "spellcheck", True),
    _k("save", "Save (F11)", Group.FLOCK, 0x0C0207, "save", False),
    _k("print", "Print (F12)", Group.FLOCK, 0x0C0208, "print", False),

    _k("log_off", "Log Off", Group.SYSTEM, 0x0C019C, "logoff", True),
    _k("sleep", "Sleep", Group.SYSTEM, 0x010082, "sleep", False),
)

_BY_ID = {k.id: k for k in KEYS}
_BY_SCAN = {k.scancode: k for k in KEYS if k.scancode is not None}


def get(key_id: str) -> KeyDef | None:
    return _BY_ID.get(key_id)


def by_scancode(scancode: int) -> KeyDef | None:
    return _BY_SCAN.get(scancode)


def custom_key(scancode: int, native: str, label: str) -> KeyDef:
    """A key discovered with Detect that isn't in the built-in catalog."""
    return KeyDef(f"scan_{scancode:x}", label, Group.CUSTOM, scancode, native, True)
