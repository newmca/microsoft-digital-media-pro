"""Kernel key names -> evdev code, XKB keysym and Qt key (see data/keycodes.json)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

# A name usable on the right-hand side of a hwdb KEYBOARD_KEY_<scan>=<name> line.
KEY_NAME_RE = re.compile(r"^[a-z0-9_]+$")


@dataclass(frozen=True)
class KernelKey:
    name: str          # "brightnessup" (KEY_BRIGHTNESSUP)
    code: int          # evdev code
    keysym: str | None  # level-1 keysym in the default keymap, None if code > 247 or unmapped
    qt: int | None     # Qt::Key for that keysym, None if Qt has no key for it

    @property
    def bindable(self) -> bool:
        """A desktop can bind it as a global shortcut (needs a keysym and a Qt key)."""
        return self.keysym is not None and self.qt is not None


@lru_cache(maxsize=1)
def _table() -> dict[str, KernelKey]:
    raw = json.loads(resources.files("dmpkeys.data").joinpath("keycodes.json").read_text())
    return {
        name: KernelKey(name, v["code"], v["keysym"], v["qt"])
        for name, v in raw["keys"].items()
    }


def lookup(name: str) -> KernelKey | None:
    return _table().get(name)


def require(name: str) -> KernelKey:
    key = lookup(name)
    if key is None:
        raise KeyError(f"unknown kernel key name: {name!r}")
    return key


def by_code(code: int) -> KernelKey | None:
    for key in _table().values():
        if key.code == code:
            return key
    return None


def all_keys() -> list[KernelKey]:
    return sorted(_table().values(), key=lambda k: k.code)


def is_valid_target(name: str) -> bool:
    """True if `name` can be written as a hwdb remap target."""
    return bool(KEY_NAME_RE.match(name)) and (name == "reserved" or name in _table())
