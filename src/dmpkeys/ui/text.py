"""User-facing wording for actions and keys (plain language; technical names go in secondary text)."""
from __future__ import annotations

import os

from ..core.config import Action, Kind
from ..core.keys import KeyDef
from .keynames import human_name

KIND_LABELS: dict[Kind, str] = {
    Kind.DEFAULT: "Default",
    Kind.KEY: "Send another key",
    Kind.DISABLE: "Do nothing",
    Kind.APP: "Launch an app",
    Kind.FOLDER: "Open a folder",
    Kind.URL: "Open a web page",
    Kind.COMMAND: "Run a command",
}


def short_path(path: str) -> str:
    """'/home/me/Documents' -> '~/Documents'."""
    home = os.path.expanduser("~")
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


def describe(action: Action, key: KeyDef | None = None) -> str:
    """One short sentence for what a key does, e.g. 'Opens Firefox'."""
    kind = action.kind
    if kind == Kind.DEFAULT:
        return f"Sends {human_name(key.native)} (default)" if key is not None else "Default"
    if kind == Kind.DISABLE:
        return "Does nothing"
    if kind == Kind.KEY:
        return f"Sends {human_name(action.target)}"
    if kind == Kind.APP:
        return f"Opens {action.label or action.target.removesuffix('.desktop')}"
    if kind == Kind.FOLDER:
        return f"Opens {short_path(action.target)}"
    if kind == Kind.URL:
        return f"Opens {action.target}"
    return f"Runs {action.label or action.target}"


def target_text(action: Action) -> str:
    """Just the 'what' of an action, for compact lists: 'Firefox', '~/Pictures'."""
    if action.kind == Kind.KEY:
        return human_name(action.target)
    if action.kind == Kind.APP:
        return action.label or action.target.removesuffix(".desktop")
    if action.kind == Kind.FOLDER:
        return short_path(action.target)
    if action.kind == Kind.COMMAND:
        return action.label or action.target
    if action.kind == Kind.URL:
        return action.target
    return describe(action)


def scancode_text(key: KeyDef) -> str:
    return f"0x{key.scancode:x}" if key.scancode is not None else "none"


def plural(n: int, word: str, words: str | None = None) -> str:
    return f"{n} {word if n == 1 else (words or word + 's')}"
