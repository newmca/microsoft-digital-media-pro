"""Where we run: native package, AppImage or Flatpak; and how to reach the host."""
from __future__ import annotations

import os
import shutil
import subprocess
from enum import Enum
from pathlib import Path


class Packaging(str, Enum):
    NATIVE = "native"      # RPM/DEB/pip: our files are on the host
    APPIMAGE = "appimage"  # host OS, but our files live in a FUSE mount root can't read
    FLATPAK = "flatpak"    # sandboxed: host commands via flatpak-spawn --host


def packaging() -> Packaging:
    if Path("/.flatpak-info").exists():
        return Packaging.FLATPAK
    if os.environ.get("APPIMAGE"):
        return Packaging.APPIMAGE
    return Packaging.NATIVE


def host_argv(argv: list[str]) -> list[str]:
    """Prefix a command so it runs on the host rather than in the sandbox."""
    if packaging() == Packaging.FLATPAK:
        return ["flatpak-spawn", "--host", *argv]
    return list(argv)


UNSET = "__unset__"


def host_env() -> dict[str, str]:
    """Environment for host programs: undo what the AppImage's AppRun changed, so
    e.g. kbuildsycoca6 doesn't load the bundled libraries."""
    env = dict(os.environ)
    if packaging() == Packaging.APPIMAGE:
        original = env.pop("DMPKEYS_ORIG_LD_LIBRARY_PATH", UNSET)
        if original == UNSET:
            env.pop("LD_LIBRARY_PATH", None)
        else:
            env["LD_LIBRARY_PATH"] = original
        env.pop("PYTHONNOUSERSITE", None)
    return env


def run(argv: list[str], *, input: str | None = None, timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(host_argv(argv), input=input, capture_output=True, text=True,
                          timeout=timeout, env=host_env())


def which(name: str) -> bool:
    if packaging() == Packaging.FLATPAK:
        return run(["sh", "-c", f'command -v "{name}" >/dev/null']).returncode == 0
    return shutil.which(name) is not None


def host_root() -> Path:
    """Prefix for reading host OS files (/usr/share/...) from inside a Flatpak."""
    return Path("/run/host") if packaging() == Packaging.FLATPAK else Path("/")


def host_path(path: str | Path) -> Path:
    """A host filesystem path as readable from here (/etc/x -> /run/host/etc/x in a Flatpak;
    needs --filesystem=host-etc:ro / host-os:ro)."""
    path = Path(path)
    return host_root() / path.relative_to("/") if path.is_absolute() else path


def current_desktop() -> list[str]:
    return [d.upper() for d in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":") if d]
