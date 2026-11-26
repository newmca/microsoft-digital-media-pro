"""An in-memory Backend for UI tests and screenshots: no D-Bus, no pkexec, no system files.

FakeBackend subclasses the real Backend so config handling, pending changes and
planning are the real code; only the parts that read or change the system are
replaced.
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

from dmpkeys.core import hwdb, keycodes
from dmpkeys.core.apps import App
from dmpkeys.core.backend import ApplyReport, Backend, SystemChange
from dmpkeys.core.config import Action, Kind
from dmpkeys.core.device import Interface, Status
from dmpkeys.core.host import Packaging
from dmpkeys.core.kde import Owner

APPS = [
    App("org.mozilla.firefox.desktop", "Firefox", "firefox", Path("/x"), "firefox"),
    App("herdr-app.desktop", "Herdr", "herdr-app", Path("/x"), "herdr"),
    App("org.kde.konsole.desktop", "Konsole", "utilities-terminal", Path("/x"), "konsole"),
    App("steam.desktop", "Steam", "steam", Path("/x"), "steam"),
    App("rocks.spotifast.Spotifast.desktop", "Spotifast", "rocks.spotifast.Spotifast", Path("/x"),
        "spotifast"),
    App("systemsettings.desktop", "System Settings", "systemsettings", Path("/x"),
        "systemsettings"),
    App("org.telegram.desktop.desktop", "Telegram", "org.telegram.desktop", Path("/x"),
        "telegram-desktop"),
    App("net.thunderbird.Thunderbird.desktop", "Thunderbird", "net.thunderbird.Thunderbird",
        Path("/x"), "thunderbird"),
    App("unityhub.desktop", "Unity Hub", "unityhub", Path("/x"), "unityhub"),
    App("com.microsoft.VSCode.desktop", "Visual Studio Code", "vscode", Path("/x"), "code"),
]

CONNECTED = Status(
    connected=True,
    interfaces=[Interface("0003:045E:00B0.0005", "usb-0000:00:14.0-5.3/input0", "microsoft",
                          ("event10",)),
                Interface("0003:045E:00B0.0006", "usb-0000:00:14.0-5.3/input1", "microsoft",
                          ("event11",))],
)
LEGACY = [Path("/etc/udev/hwdb.d/61-ms-digital-media-pro.hwdb"),
          Path("/etc/udev/rules.d/61-ms-digital-media-pro.rules")]

# A stand-in for the root capture helper: prints the given JSON lines, then waits
# for stdin to close (like the real helper does when stopped early).
_CAPTURE_SCRIPT = """
import json, sys, time
for line in json.loads(sys.argv[1]):
    print(line, flush=True)
    time.sleep(0.02)
if json.loads(sys.argv[2]):
    sys.stdin.read()
"""


class FakeKde:
    def __init__(self) -> None:
        self.owners_by_qt: dict[int, list] = {}

    def available(self) -> bool:
        return True

    def owners(self, qt: int) -> list:
        return list(self.owners_by_qt.get(qt, []))


class FakeBackend(Backend):
    def __init__(self, tmp: Path, *, desktop: str | None = "kde", status: Status = CONNECTED,
                 apps: list[App] | None = None):
        super().__init__(config_path=tmp / "config.json", state_path=tmp / "state.json",
                         kde=FakeKde(), desktop=desktop)
        self._status = status
        self._apps = list(APPS if apps is None else apps)
        self.installed_hwdb: str | None = None
        self.apply_calls: list[bool] = []
        self.reset_calls = 0
        self.apply_errors: list[str] = []
        self.import_notes = ["Read 4 remaps from /etc/udev/hwdb.d/61-ms-digital-media-pro.hwdb.",
                             "Web/Home: Launches Firefox"]
        self.capture_lines: list[str] = []
        self.capture_waits = False

    # --- system reads ----------------------------------------------------------------
    def status(self) -> Status:
        return self._status

    def set_status(self, status: Status) -> None:
        self._status = status

    def apps(self) -> list[App]:
        return list(self._apps)

    def packaging(self) -> Packaging:
        return Packaging.NATIVE

    def current_remaps(self) -> dict[int, str]:
        return hwdb.parse(self.installed_hwdb) if self.installed_hwdb else {}

    def system_change(self, plan, disable_legacy: bool = True) -> SystemChange:
        text = hwdb.render(plan.remaps, plan.remap_notes) if plan.remaps else None
        disable = ([str(p) for p in self._status.legacy_hwdb + self._status.legacy_rules]
                   if disable_legacy else [])
        needed = (text != self.installed_hwdb
                  or self._status.favorites_fix_installed != plan.favorites_fix or bool(disable))
        return SystemChange(text, plan.favorites_fix, disable, needed)

    # --- system changes ----------------------------------------------------------------
    def apply(self, disable_legacy: bool = True) -> ApplyReport:
        self.apply_calls.append(disable_legacy)
        plan = self.plan()
        change = self.system_change(plan, disable_legacy)
        report = ApplyReport(ok=True, key_errors=dict(plan.errors))
        if self.apply_errors:
            return ApplyReport(False, errors=list(self.apply_errors))
        if change.needed:
            report.messages.append("Updated system key mapping.")
            report.messages += [f"Disabled old config {p}." for p in change.disable]
        self.installed_hwdb = change.hwdb_text
        self._status = replace(self._status, favorites_fix_installed=plan.favorites_fix,
                               hwdb_installed=change.hwdb_text is not None,
                               legacy_hwdb=[] if disable_legacy else self._status.legacy_hwdb,
                               legacy_rules=[] if disable_legacy else self._status.legacy_rules)
        report.messages.append(f"KDE: {len(plan.bindings)} shortcuts active.")
        self.state.applied_config = self.config.to_json()
        report.ok = not report.key_errors
        return report

    def reset_all(self) -> ApplyReport:
        self.reset_calls += 1
        self.installed_hwdb = None
        self._status = replace(self._status, favorites_fix_installed=False, hwdb_installed=False)
        self.state.applied_config = None
        return ApplyReport(True, ["Removed system key mapping and favorites fix.",
                                  "Removed desktop shortcuts."])

    def import_existing(self) -> list[str]:
        self.config.set_action("web_home", Action(Kind.APP, "org.mozilla.firefox.desktop",
                                                  "Firefox"))
        self.save_config()
        self.first_run = False
        return list(self.import_notes)

    def capture_argv(self, seconds: int = 15) -> list[str]:
        return [sys.executable, "-c", _CAPTURE_SCRIPT, json.dumps(self.capture_lines),
                json.dumps(self.capture_waits)]


def owner_setup(backend: FakeBackend) -> None:
    """The setup the app was built around, plus one unapplied change and one problem."""
    home = str(Path.home())
    actions = {
        "slider_up": Action(Kind.KEY, "brightnessup"),
        "slider_down": Action(Kind.KEY, "brightnessdown"),
        "fav_star": Action(Kind.APP, "systemsettings.desktop", "System Settings"),
        "fav1": Action(Kind.APP, "org.kde.konsole.desktop", "Konsole"),
        "fav2": Action(Kind.APP, "herdr-app.desktop", "Herdr"),
        "fav3": Action(Kind.APP, "unityhub.desktop", "Unity Hub"),
        "fav4": Action(Kind.APP, "com.microsoft.VSCode.desktop", "Visual Studio Code"),
        "fav5": Action(Kind.APP, "steam.desktop", "Steam"),
        "my_documents": Action(Kind.FOLDER, f"{home}/Documents", "Documents"),
        "my_pictures": Action(Kind.FOLDER, f"{home}/Pictures", "Pictures"),
        "my_music": Action(Kind.APP, "rocks.spotifast.Spotifast.desktop", "Spotifast"),
        "mail": Action(Kind.APP, "net.thunderbird.Thunderbird.desktop", "Thunderbird"),
        "web_home": Action(Kind.APP, "org.mozilla.firefox.desktop", "Firefox"),
        "messenger": Action(Kind.APP, "org.telegram.desktop.desktop", "Telegram"),
    }
    for key_id, action in actions.items():
        backend.set_action(key_id, action)
    backend.installed_hwdb = backend.system_change(backend.plan(), False).hwdb_text
    backend.state.applied_config = backend.config.to_json()
    backend.set_status(replace(backend.status(), favorites_fix_installed=True, hwdb_installed=True))
    # Not applied yet: Calculator now opens a web page.
    backend.set_action("calculator", Action(Kind.URL, "https://www.desmos.com/scientific"))
    # A problem: another program grabbed the key Favorite 5 sends, and favorites
    # can't be moved to a spare key.
    f18 = keycodes.require("f18")
    backend.kde.owners_by_qt[f18.qt] = [Owner("org.kde.spectacle.desktop", "RegionScreenShot",
                                              "Spectacle")]
