"""What dmpkeys last applied, so the next Apply can undo exactly its own changes."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class State:
    kde: dict[str, list[int]] = field(default_factory=dict)   # desktop id -> our Qt keys
    kde_created: list[str] = field(default_factory=list)      # launcher desktop ids we created
    gnome: list[str] = field(default_factory=list)            # our custom-keybinding paths
    applied_config: dict | None = None                        # config JSON at last successful apply

    def to_json(self) -> dict:
        return {"kde": self.kde, "kde_created": self.kde_created, "gnome": self.gnome,
                "applied_config": self.applied_config}

    @classmethod
    def from_json(cls, d: dict) -> "State":
        return cls(d.get("kde", {}), d.get("kde_created", []), d.get("gnome", []),
                   d.get("applied_config"))


def state_path() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "dmpkeys" / "state.json"


def load(path: Path | None = None) -> State:
    path = path or state_path()
    try:
        return State.from_json(json.loads(path.read_text()))
    except FileNotFoundError:
        return State()


def save(state: State, path: Path | None = None) -> None:
    path = path or state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state.to_json(), indent=2) + "\n")
    tmp.replace(path)
