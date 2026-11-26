"""Render and parse udev hwdb keymap files for the keyboard."""
from __future__ import annotations

import re
from pathlib import Path

from . import host, keycodes
from .keys import HWDB_MATCH

HWDB_DIR = Path("/etc/udev/hwdb.d")
# 70- sorts after systemd's 60-keyboard.hwdb and after hand-made 61-* files,
# so for any scancode both define, ours wins.
HWDB_FILE = HWDB_DIR / "70-dmpkeys.hwdb"

_ENTRY_RE = re.compile(r"^\s+KEYBOARD_KEY_([0-9a-fA-F]+)=([a-z0-9_]+)\s*$")
_DEVICE_RE = re.compile(r"v045Ep00B0", re.IGNORECASE)

HEADER = """\
# Managed by Digital Media Pro Keys (dmpkeys). Edits are overwritten on Apply.
# Microsoft Digital Media Pro Keyboard (USB 045E:00B0): scancode -> kernel key.
"""


def render(remaps: dict[int, str], comments: dict[int, str] | None = None) -> str:
    """remaps: scancode -> kernel key name. Empty dict renders a header-only file."""
    comments = comments or {}
    for scan, name in remaps.items():
        if not keycodes.is_valid_target(name):
            raise ValueError(f"invalid hwdb target {name!r} for scancode {scan:x}")
    lines = [HEADER, HWDB_MATCH]
    for scan in sorted(remaps):
        note = comments.get(scan)
        if note:
            lines.append(f"# {note}")
        lines.append(f" KEYBOARD_KEY_{scan:x}={remaps[scan]}")
    return "\n".join(lines) + "\n"


def parse(text: str) -> dict[int, str]:
    """Remaps for this keyboard in a hwdb file (entries under a 045E:00B0 match line)."""
    remaps: dict[int, str] = {}
    in_ours = False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():          # a match line starts a new block
            in_ours = bool(_DEVICE_RE.search(line))
            continue
        m = _ENTRY_RE.match(line)
        if in_ours and m:
            remaps[int(m.group(1), 16)] = m.group(2)
    return remaps


def mentions_device(text: str) -> bool:
    return any(_DEVICE_RE.search(line) for line in text.splitlines()
               if line and not line[0].isspace() and not line.startswith("#"))


def installed_text() -> str | None:
    try:
        return host.host_path(HWDB_FILE).read_text()
    except FileNotFoundError:
        return None


def installed() -> dict[int, str] | None:
    """Our installed file's remaps, or None if not installed."""
    text = installed_text()
    return None if text is None else parse(text)


def legacy_files(hwdb_dir: Path | None = None) -> list[Path]:
    """Other hwdb files in /etc that remap this keyboard (e.g. hand-made ones).

    Returned paths are host paths (what the root helper must be given), even
    when read through /run/host inside a Flatpak.
    """
    out = []
    readable_dir = hwdb_dir or host.host_path(HWDB_DIR)
    for readable in sorted(readable_dir.glob("*.hwdb")):
        path = HWDB_DIR / readable.name if hwdb_dir is None else readable
        if path == HWDB_FILE:
            continue
        try:
            if mentions_device(readable.read_text()):
                out.append(path)
        except OSError:
            continue
    return out
