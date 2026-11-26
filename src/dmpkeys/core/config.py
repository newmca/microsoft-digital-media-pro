"""What the user wants each key to do, persisted as JSON.

~/.config/dmpkeys/config.json   desired mapping (this module)
~/.local/state/dmpkeys/state.json  what was actually applied (see state.py)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from . import keycodes, keys

CONFIG_VERSION = 1


class Kind(str, Enum):
    DEFAULT = "default"   # whatever the kernel/driver sends; nothing touched
    KEY = "key"           # remap to another kernel key (hwdb)
    DISABLE = "disable"   # remap to KEY_RESERVED (hwdb)
    APP = "app"           # launch a .desktop application
    FOLDER = "folder"     # open a folder in the file manager
    URL = "url"           # open a URL in the browser
    COMMAND = "command"   # run a shell command


ACTION_KINDS = (Kind.APP, Kind.FOLDER, Kind.URL, Kind.COMMAND)


@dataclass(frozen=True)
class Action:
    kind: Kind = Kind.DEFAULT
    target: str = ""      # KEY: kernel key name; APP: desktop id; FOLDER: path; URL: url; COMMAND: command
    label: str = ""       # display name, e.g. the app's Name=

    @property
    def is_desktop_action(self) -> bool:
        return self.kind in ACTION_KINDS

    def validate(self, key: keys.KeyDef) -> str | None:
        """Return an error message, or None if the action fits the key."""
        if self.kind in (Kind.KEY, Kind.DISABLE) and not key.hwdb_remappable:
            return f"{key.label} has no scancode, so it can't be remapped to another key."
        if self.kind == Kind.KEY and not keycodes.is_valid_target(self.target):
            return f"Unknown key: {self.target!r}"
        if self.kind in ACTION_KINDS and not self.target.strip():
            return "Nothing to launch: the action is empty."
        if self.kind == Kind.FOLDER and not os.path.isabs(os.path.expanduser(self.target)):
            return "Folder must be an absolute path."
        return None

    def describe(self) -> str:
        if self.kind == Kind.DEFAULT:
            return "Default"
        if self.kind == Kind.DISABLE:
            return "Disabled"
        if self.kind == Kind.KEY:
            return f"Sends {self.target}"
        if self.kind == Kind.APP:
            return f"Launches {self.label or self.target}"
        if self.kind == Kind.FOLDER:
            return f"Opens {self.target}"
        if self.kind == Kind.URL:
            return f"Opens {self.target}"
        return f"Runs {self.label or self.target}"

    def to_json(self) -> dict:
        d = {"kind": self.kind.value}
        if self.target:
            d["target"] = self.target
        if self.label:
            d["label"] = self.label
        return d

    @classmethod
    def from_json(cls, d: dict) -> "Action":
        return cls(Kind(d.get("kind", "default")), d.get("target", ""), d.get("label", ""))


@dataclass
class CustomKey:
    scancode: int
    native: str
    label: str

    def keydef(self) -> keys.KeyDef:
        return keys.custom_key(self.scancode, self.native, self.label)


@dataclass
class Config:
    actions: dict[str, Action] = field(default_factory=dict)   # key id -> action
    favorites_fix: bool = True
    custom_keys: list[CustomKey] = field(default_factory=list)

    def action(self, key_id: str) -> Action:
        return self.actions.get(key_id, Action())

    def set_action(self, key_id: str, action: Action) -> None:
        if action.kind == Kind.DEFAULT:
            self.actions.pop(key_id, None)
        else:
            self.actions[key_id] = action

    def all_keys(self) -> list[keys.KeyDef]:
        return list(keys.KEYS) + [c.keydef() for c in self.custom_keys]

    def key(self, key_id: str) -> keys.KeyDef | None:
        return keys.get(key_id) or next((k for k in self.all_keys() if k.id == key_id), None)

    def to_json(self) -> dict:
        return {
            "version": CONFIG_VERSION,
            "favorites_fix": self.favorites_fix,
            "actions": {k: a.to_json() for k, a in sorted(self.actions.items())},
            "custom_keys": [
                {"scancode": f"{c.scancode:x}", "native": c.native, "label": c.label}
                for c in self.custom_keys
            ],
        }

    @classmethod
    def from_json(cls, d: dict) -> "Config":
        return cls(
            actions={k: Action.from_json(v) for k, v in d.get("actions", {}).items()},
            favorites_fix=d.get("favorites_fix", True),
            custom_keys=[
                CustomKey(int(c["scancode"], 16), c["native"], c["label"])
                for c in d.get("custom_keys", [])
            ],
        )


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "dmpkeys"


def config_path() -> Path:
    return config_dir() / "config.json"


def load(path: Path | None = None) -> Config | None:
    """None if no config exists yet (first run)."""
    path = path or config_path()
    if not path.exists():
        return None
    return Config.from_json(json.loads(path.read_text()))


def save(config: Config, path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(config.to_json(), indent=2) + "\n")
    tmp.replace(path)
