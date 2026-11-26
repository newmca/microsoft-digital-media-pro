"""Installed applications (.desktop files) the user can bind a key to."""
from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path

from . import host


@dataclass(frozen=True)
class App:
    desktop_id: str    # org.mozilla.firefox.desktop
    name: str
    icon: str
    path: Path
    exec: str


def data_dirs() -> list[Path]:
    """XDG data dirs, highest priority first, mapped to host paths when sandboxed."""
    home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    dirs = [home, home / "flatpak/exports/share"]
    if host.packaging() == host.Packaging.FLATPAK:
        # The sandbox's XDG_DATA_DIRS point at the runtime; read the host's instead.
        root = host.host_root()
        dirs += [root / "usr/local/share", root / "usr/share", Path("/var/lib/flatpak/exports/share")]
    else:
        system = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
        dirs += [Path(d) for d in system.split(":") if d]
        dirs.append(Path("/var/lib/flatpak/exports/share"))
    seen, out = set(), []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


class _CaseSensitiveParser(configparser.RawConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr   # .desktop keys are case-sensitive (Name vs name)


def parse_desktop(path: Path) -> dict[str, str] | None:
    parser = _CaseSensitiveParser(interpolation=None, strict=False)
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError, OSError):
        return None
    if not parser.has_section("Desktop Entry"):
        return None
    return dict(parser["Desktop Entry"])


def desktop_id(path: Path, applications_dir: Path) -> str:
    """Per the spec, subdirectory separators become '-'."""
    return str(path.relative_to(applications_dir)).replace(os.sep, "-")


def find(desktop_id_: str) -> Path | None:
    # Desktop ids from subdirectories (vendor/foo.desktop -> vendor-foo.desktop) are
    # rare and ambiguous to reverse; only top-level files are looked up directly.
    for d in data_dirs():
        candidate = d / "applications" / desktop_id_
        if candidate.exists():
            return candidate
    return None


def installed() -> list[App]:
    """Visible applications, de-duplicated by desktop id (user dirs win), sorted by name."""
    apps: dict[str, App] = {}
    for d in data_dirs():
        appdir = d / "applications"
        if not appdir.is_dir():
            continue
        for path in appdir.rglob("*.desktop"):
            did = desktop_id(path, appdir)
            if did in apps:
                continue
            entry = parse_desktop(path)
            if entry is None:
                continue
            hidden = entry.get("NoDisplay") == "true" or entry.get("Hidden") == "true"
            if entry.get("Type") != "Application" or "Exec" not in entry:
                continue
            apps[did] = App(did, entry.get("Name", did), entry.get("Icon", ""), path,
                            entry["Exec"])
            if hidden:
                # Keep hidden entries out of the picker but remember them as shadowing.
                apps[did] = App(did, "", "", path, entry["Exec"])
    return sorted((a for a in apps.values() if a.name), key=lambda a: a.name.casefold())


def lookup(desktop_id_: str) -> App | None:
    path = find(desktop_id_)
    if path is None:
        return None
    entry = parse_desktop(path) or {}
    return App(desktop_id_, entry.get("Name", desktop_id_), entry.get("Icon", ""), path,
               entry.get("Exec", ""))
