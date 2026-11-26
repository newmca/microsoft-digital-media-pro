"""Command lines and launcher .desktop files for folder/URL/command actions.

KDE binds global shortcuts to .desktop files, so non-app actions get a hidden
launcher in ~/.local/share/applications named like the ones System Settings
creates for command shortcuts (net.local.*). GNOME binds command lines.
"""
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

from . import apps
from .config import Action, Kind

PREFIX = "net.local.dmpkeys-"
# Characters that force quoting in Exec= (Desktop Entry Spec, "The Exec key").
_EXEC_RESERVED = re.compile(r'[\s"\'\\><~|&;$*?#()`]')


def applications_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "applications"


def desktop_id_for(key_id: str) -> str:
    return f"{PREFIX}{key_id}.desktop"


def argv_for(action: Action) -> list[str]:
    """The program and arguments an action runs (APP is handled by the desktop)."""
    if action.kind == Kind.FOLDER:
        return ["xdg-open", os.path.expanduser(action.target)]
    if action.kind == Kind.URL:
        return ["xdg-open", action.target]
    if action.kind == Kind.COMMAND:
        return ["sh", "-c", action.target]
    if action.kind == Kind.APP:
        app = apps.lookup(action.target)
        if app is None:
            raise LookupError(f"application {action.target} is not installed")
        return ["gio", "launch", str(app.path)]
    raise ValueError(f"{action.kind} has no command line")


def shell_command(action: Action) -> str:
    """For GNOME custom keybindings (parsed with g_shell_parse_argv)."""
    return shlex.join(argv_for(action))


def exec_quote(arg: str) -> str:
    """Quote one argument for a .desktop Exec= value (Desktop Entry Spec, 'The Exec key')."""
    arg = arg.replace("%", "%%")
    if not _EXEC_RESERVED.search(arg):
        return arg
    inner = re.sub(r'(["`$\\])', r"\\\1", arg)
    return f'"{inner}"'


def desktop_value_escape(value: str) -> str:
    """String-level escaping of a .desktop value (applied after Exec quoting)."""
    return value.replace("\\", "\\\\").replace("\n", "\\n")


def render_launcher(key_label: str, action: Action) -> str:
    exec_line = " ".join(exec_quote(a) for a in argv_for(action))
    name = action.label or action.describe()
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={desktop_value_escape(name)}\n"
        f"Comment={desktop_value_escape('Digital Media Pro key: ' + key_label)}\n"
        f"Exec={desktop_value_escape(exec_line)}\n"
        "NoDisplay=true\n"
        "StartupNotify=false\n"
        "X-KDE-GlobalAccel-CommandShortcut=true\n"
        "X-DmpKeys-Managed=true\n"
    )


def write_launcher(key_id: str, key_label: str, action: Action) -> str:
    """Write (or rewrite) the launcher for a key; returns its desktop id."""
    directory = applications_dir()
    directory.mkdir(parents=True, exist_ok=True)
    did = desktop_id_for(key_id)
    path = directory / did
    content = render_launcher(key_label, action)
    if not path.exists() or path.read_text() != content:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(content)
        tmp.replace(path)
    return did


def remove_launcher(desktop_id: str) -> None:
    if not desktop_id.startswith(PREFIX):
        return  # never delete files we didn't create
    path = applications_dir() / desktop_id
    try:
        if "X-DmpKeys-Managed=true" in path.read_text():
            path.unlink()
    except FileNotFoundError:
        pass
