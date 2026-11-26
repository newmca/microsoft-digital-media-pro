"""KDE Plasma 6 global shortcuts through kglobalaccel's D-Bus API.

Lessons this module encodes (see docs/NOTES.md):
* Shortcuts are Qt key codes (Qt::Key), not keysym or kernel names. F14
  reaches Qt as Key_Launch5 because XKB maps <FK14> to XF86Launch5.
* setShortcutKeys with SetPresent|NoAutoloading. setForeignShortcutKeys stores
  keys for a newly registered launcher but leaves it inactive, so KWin never
  grabs the key until the next login.
* On Plasma 6 Wayland kglobalaccel lives inside kwin_wayland: it can't be
  restarted to reread kglobalshortcutsrc, so everything goes through D-Bus.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from jeepney import DBusAddress, new_method_call
from jeepney.io.blocking import open_dbus_connection

SERVICE = "org.kde.kglobalaccel"
ROOT = DBusAddress("/kglobalaccel", bus_name=SERVICE, interface="org.kde.KGlobalAccel")
LAUNCH_ACTION = "_launch"

# KGlobalAccel::SetShortcutFlag
SET_PRESENT = 2
NO_AUTOLOADING = 4


@dataclass(frozen=True)
class Owner:
    component: str      # e.g. org.mozilla.firefox.desktop
    action: str         # e.g. _launch
    friendly: str       # e.g. Firefox
    defaults: tuple[int, ...] = ()  # Qt keys of the action's default (shipped) shortcut

    def is_default_for(self, qt: int) -> bool:
        return qt in self.defaults

    def describe(self) -> str:
        return self.friendly or f"{self.component} / {self.action}"


def _seq(qt: int) -> tuple[list[int]]:
    """A single-key QKeySequence as marshalled over D-Bus: (ai) with 4 ints."""
    return ([qt, 0, 0, 0],)


class KdeShortcuts:
    def __init__(self, connection=None):
        self._conn = connection

    @property
    def conn(self):
        if self._conn is None:
            self._conn = open_dbus_connection(bus="SESSION")
        return self._conn

    def _call(self, method: str, signature: str | None = None, *args):
        msg = new_method_call(ROOT, method, signature, args) if signature else new_method_call(ROOT, method)
        reply = self.conn.send_and_get_reply(msg, timeout=10)
        if reply.header.message_type.name == "error":
            raise RuntimeError(f"kglobalaccel {method} failed: {reply.body}")
        return reply.body

    # --- queries -----------------------------------------------------------------
    def available(self) -> bool:
        try:
            dbus = DBusAddress("/org/freedesktop/DBus", bus_name="org.freedesktop.DBus",
                               interface="org.freedesktop.DBus")
            reply = self.conn.send_and_get_reply(new_method_call(dbus, "NameHasOwner", "s", (SERVICE,)),
                                                 timeout=5)
            return bool(reply.body[0])
        except Exception:
            return False

    def owners(self, qt: int) -> list[Owner]:
        """Every action bound to exactly this key (single-key sequence)."""
        (rows,) = self._call("globalShortcutsByKey", "(ai)(i)", _seq(qt), (0,))
        # a(ssssssaiai): action, actionFriendly, component, componentFriendly, context, contextFriendly, keys, defaults
        return [Owner(r[2], r[0], r[1] or r[3], tuple(r[7])) for r in rows]

    def keys(self, desktop_id: str) -> list[list[int]]:
        (seqs,) = self._call("shortcutKeys", "as", [desktop_id, LAUNCH_ACTION, "", ""])
        return [list(s[0]) for s in seqs]

    # --- changes -----------------------------------------------------------------
    def set_launch_keys(self, desktop_id: str, name: str, keep: list[list[int]], ours: list[int]) -> list[list[int]]:
        """Set the launcher's keys to `keep` (other people's sequences) + our single keys."""
        action_id = [desktop_id, LAUNCH_ACTION, name, name]
        self._call("doRegister", "as", action_id)
        seqs = [(s,) for s in keep] + [_seq(q) for q in ours]
        (result,) = self._call("setShortcutKeys", "asa(ai)u", action_id, seqs,
                               SET_PRESENT | NO_AUTOLOADING)
        return [list(s[0]) for s in result]

    def unregister(self, desktop_id: str) -> None:
        self._call("unRegister", "as", [desktop_id, LAUNCH_ACTION, "", ""])

    # --- high level --------------------------------------------------------------
    def apply(self, wanted: dict[str, tuple[str, list[int]]], previous: dict[str, list[int]],
              ours_created: set[str]) -> dict[str, list[int]]:
        """wanted: desktop id -> (display name, our Qt keys). previous: what we set last time.

        Keys other programs or the user bound on the same launcher are preserved.
        Returns the new `previous` to store.
        """
        applied: dict[str, list[int]] = {}
        for did in sorted(set(wanted) | set(previous)):
            name, ours = wanted.get(did, ("", []))
            old_ours = previous.get(did, [])
            current = self.keys(did) if did in previous or did in wanted else []
            keep = [s for s in current if not (s[1:] == [0, 0, 0] and s[0] in old_ours + ours)]
            if not ours and not keep and did in ours_created:
                self.set_launch_keys(did, name or did, [], [])
                self.unregister(did)
                continue
            result = self.set_launch_keys(did, name or did, keep, ours)
            got = {s[0] for s in result if s[1:] == [0, 0, 0]}
            taken = [q for q in ours if q in got]
            if taken:
                applied[did] = taken
        return applied


def launcher_exec(desktop_text: str) -> str | None:
    m = re.search(r"^Exec=(.*)$", desktop_text, re.M)
    return m.group(1) if m else None
