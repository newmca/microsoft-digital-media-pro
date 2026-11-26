"""GNOME custom keybindings (org.gnome.settings-daemon.plugins.media-keys).

Each bound key gets its own relocatable entry at
/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/dmpkeys-<key>/
whose binding is the bare keysym name (e.g. 'XF86Mail').

Caveat carried over from testing on GNOME (Shell 4x): bindings on
XF86Launch1-4 were accepted but never fired. The favorites keys arrive as
XF86Launch5-9, so they may not be bindable on GNOME; untested.
"""
from __future__ import annotations

import ast
import re

from . import host

MEDIA_KEYS = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_SCHEMA = MEDIA_KEYS + ".custom-keybinding"
BASE_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"
OUR_PREFIX = BASE_PATH + "dmpkeys-"
KEYBINDING_SCHEMAS = (MEDIA_KEYS, "org.gnome.desktop.wm.keybindings", "org.gnome.shell.keybindings",
                      "org.gnome.mutter.keybindings", "org.gnome.mutter.wayland.keybindings")


def _gsettings(*args: str) -> str:
    proc = host.run(["gsettings", *args])
    if proc.returncode != 0:
        raise RuntimeError(f"gsettings {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _parse_strv(value: str) -> list[str]:
    value = value.strip()
    if value.startswith("@as "):
        value = value[4:]
    try:
        parsed = ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return []
    if isinstance(parsed, str):
        return [parsed]
    return [str(v) for v in parsed]


def path_for(key_id: str) -> str:
    return f"{OUR_PREFIX}{key_id.replace('_', '-')}/"


class GnomeShortcuts:
    def available(self) -> bool:
        if "GNOME" not in host.current_desktop() or not host.which("gsettings"):
            return False
        try:
            return MEDIA_KEYS in _gsettings("list-schemas").split()
        except Exception:
            return False

    def owners(self, keysym: str) -> list[str]:
        """Names of bindings (built-in or other custom ones) using exactly this keysym."""
        found = []
        for schema in KEYBINDING_SCHEMAS:
            try:
                listing = _gsettings("list-recursively", schema)
            except RuntimeError:
                continue
            for line in listing.splitlines():
                parts = line.split(" ", 2)
                if len(parts) == 3 and keysym in _parse_strv(parts[2]):
                    found.append(f"{schema.rsplit('.', 1)[-1]}: {parts[1]}")
        for path in self._custom_paths():
            if path.startswith(OUR_PREFIX):
                continue
            spec = f"{CUSTOM_SCHEMA}:{path}"
            try:
                if _parse_strv(_gsettings("get", spec, "binding")) == [keysym]:
                    found.append(_parse_strv(_gsettings("get", spec, "name"))[0] or path)
            except (RuntimeError, IndexError):
                continue
        return found

    def _custom_paths(self) -> list[str]:
        return _parse_strv(_gsettings("get", MEDIA_KEYS, "custom-keybindings"))

    def apply(self, wanted: dict[str, tuple[str, str, str]], previous: list[str]) -> list[str]:
        """wanted: key id -> (name, command, keysym). Returns our paths now in use."""
        ours = {path_for(k): v for k, v in wanted.items()}
        for path in previous:
            if path not in ours and path.startswith(OUR_PREFIX):
                for key in ("name", "command", "binding"):
                    _gsettings("reset", f"{CUSTOM_SCHEMA}:{path}", key)
        for path, (name, command, keysym) in ours.items():
            spec = f"{CUSTOM_SCHEMA}:{path}"
            _gsettings("set", spec, "name", gvariant_str(name))
            _gsettings("set", spec, "command", gvariant_str(command))
            _gsettings("set", spec, "binding", gvariant_str(keysym))
        others = [p for p in self._custom_paths() if not p.startswith(OUR_PREFIX)]
        paths = others + sorted(ours)
        value = "[" + ", ".join(gvariant_str(p) for p in paths) + "]" if paths else "@as []"
        _gsettings("set", MEDIA_KEYS, "custom-keybindings", value)
        return sorted(ours)


def gvariant_str(value: str) -> str:
    """A GVariant text-format string literal (gsettings parses values as GVariant)."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


_ACCEL_RE = re.compile(r"^[A-Za-z0-9_]+$")


def valid_keysym(keysym: str) -> bool:
    return bool(_ACCEL_RE.match(keysym))
