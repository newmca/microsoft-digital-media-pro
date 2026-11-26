"""Human names and picker categories for kernel key names (``brightnessup`` -> "Brightness up")."""
from __future__ import annotations

from functools import lru_cache

from ..core import keycodes

ALL_KEYS = "All keys"

# Shown in this order in the "Send another key" picker. Names missing from the
# kernel table are skipped, so the lists can be generous.
CATEGORIES: dict[str, tuple[str, ...]] = {
    "Brightness": ("brightnessup", "brightnessdown", "brightness_cycle", "brightness_auto",
                   "brightness_min", "brightness_max", "display_off", "switchvideomode",
                   "kbdillumup", "kbdillumdown", "kbdillumtoggle"),
    "Volume": ("volumeup", "volumedown", "mute", "micmute"),
    "Media": ("playpause", "play", "pausecd", "stopcd", "previoussong", "nextsong", "rewind",
              "fastforward", "record", "shuffle", "media_repeat", "ejectcd"),
    "Zoom": ("zoomin", "zoomout", "zoomreset"),
    "Navigation": ("up", "down", "left", "right", "pageup", "pagedown", "home", "end", "back",
                   "forward", "refresh", "scrollup", "scrolldown", "tab", "esc", "enter", "space"),
    "Editing": ("undo", "redo", "cut", "copy", "paste", "find", "delete", "backspace", "insert",
                "new", "open", "close", "save", "print", "spellcheck", "help"),
    "F13–F24": tuple(f"f{n}" for n in range(13, 25)),
    "Apps": ("www", "homepage", "mail", "calc", "computer", "file", "documents", "images",
             "audio", "video", "chat", "messenger", "search", "bookmarks", "config",
             "controlpanel", "calendar", "addressbook", "camera", "media", "all_applications",
             "taskmanager", "wordprocessor", "spreadsheet", "presentation", "editor",
             "prog1", "prog2", "prog3", "prog4"),
    "System": ("power", "sleep", "suspend", "wakeup", "logoff", "coffee", "screensaver",
               "sysrq", "selective_screenshot", "notification_center", "emoji_picker",
               "kbd_layout_next", "wlan", "bluetooth", "rfkill", "touchpad_toggle"),
}

_NAMES: dict[str, str] = {
    # Brightness
    "brightnessup": "Brightness up", "brightnessdown": "Brightness down",
    "brightness_cycle": "Cycle brightness", "brightness_auto": "Auto brightness",
    "brightness_min": "Minimum brightness", "brightness_max": "Maximum brightness",
    "display_off": "Turn display off", "switchvideomode": "Switch display mode",
    "kbdillumup": "Keyboard backlight up", "kbdillumdown": "Keyboard backlight down",
    "kbdillumtoggle": "Keyboard backlight on/off",
    # Volume
    "volumeup": "Volume up", "volumedown": "Volume down", "mute": "Mute",
    "micmute": "Mute microphone",
    # Media
    "playpause": "Play/Pause", "play": "Play", "pausecd": "Pause", "stopcd": "Stop playback",
    "previoussong": "Previous track", "nextsong": "Next track", "rewind": "Rewind",
    "fastforward": "Fast forward", "record": "Record", "shuffle": "Shuffle",
    "media_repeat": "Repeat", "ejectcd": "Eject",
    # Zoom
    "zoomin": "Zoom in", "zoomout": "Zoom out", "zoomreset": "Reset zoom",
    # Navigation
    "up": "Up arrow", "down": "Down arrow", "left": "Left arrow", "right": "Right arrow",
    "pageup": "Page Up", "pagedown": "Page Down", "home": "Home", "end": "End",
    "back": "Back", "forward": "Forward", "refresh": "Refresh", "scrollup": "Scroll up",
    "scrolldown": "Scroll down", "tab": "Tab", "esc": "Escape", "enter": "Enter",
    "space": "Space",
    # Editing
    "undo": "Undo", "redo": "Redo", "cut": "Cut", "copy": "Copy", "paste": "Paste",
    "find": "Find", "delete": "Delete", "backspace": "Backspace", "insert": "Insert",
    "new": "New", "open": "Open", "close": "Close", "save": "Save", "print": "Print",
    "spellcheck": "Spell check", "help": "Help", "again": "Again",
    "reply": "Reply", "forwardmail": "Forward mail", "send": "Send",
    # Apps
    "www": "Web browser", "homepage": "Home page", "mail": "Mail", "email": "Email",
    "calc": "Calculator", "computer": "My Computer", "file": "File manager",
    "documents": "Documents", "images": "Pictures", "audio": "Music", "video": "Videos",
    "chat": "Chat", "messenger": "Messenger", "search": "Search", "bookmarks": "Bookmarks",
    "config": "Settings", "controlpanel": "Control panel", "calendar": "Calendar",
    "addressbook": "Address book", "camera": "Camera", "media": "Media player",
    "all_applications": "Show all apps", "taskmanager": "Task manager",
    "wordprocessor": "Word processor", "spreadsheet": "Spreadsheet",
    "presentation": "Presentation", "editor": "Text editor",
    "prog1": "Program 1", "prog2": "Program 2", "prog3": "Program 3", "prog4": "Program 4",
    # System
    "power": "Power", "sleep": "Sleep", "suspend": "Suspend", "wakeup": "Wake up",
    "logoff": "Log off", "coffee": "Lock screen", "screensaver": "Screensaver",
    "sysrq": "Print Screen", "selective_screenshot": "Screenshot of an area",
    "notification_center": "Notifications", "emoji_picker": "Emoji picker",
    "kbd_layout_next": "Next keyboard layout", "wlan": "Wi-Fi on/off",
    "bluetooth": "Bluetooth on/off", "rfkill": "Airplane mode",
    "touchpad_toggle": "Touchpad on/off",
    # Misc keys this keyboard sends natively
    "reserved": "Nothing",
}


def human_name(name: str) -> str:
    """'brightnessup' -> 'Brightness up'; unknown names are tidied ('kp_7' -> 'Kp 7')."""
    if name in _NAMES:
        return _NAMES[name]
    if len(name) >= 2 and name[0] == "f" and name[1:].isdigit():
        return name.upper()
    if len(name) == 1:
        return name.upper()
    return name.replace("_", " ").capitalize()


@lru_cache(maxsize=1)
def categories() -> dict[str, tuple[str, ...]]:
    """CATEGORIES restricted to names the kernel table knows, plus ALL_KEYS."""
    known = {k.name for k in keycodes.all_keys()}
    out = {cat: tuple(n for n in names if n in known) for cat, names in CATEGORIES.items()}
    out[ALL_KEYS] = tuple(k.name for k in keycodes.all_keys() if k.name != "reserved")
    return out


def category_of(name: str) -> str | None:
    for cat, names in CATEGORIES.items():
        if name in names:
            return cat
    return None


def reaches_desktop(name: str) -> bool:
    """Whether apps and the desktop can see this key at all (it has a keysym)."""
    key = keycodes.lookup(name)
    return key is not None and key.keysym is not None
