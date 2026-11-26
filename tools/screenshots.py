#!/usr/bin/env python3
"""Render every screen and dialog offscreen into docs/screenshots/, in light and dark.

Uses the fake backend from tests/ui/fakes.py (no D-Bus, no pkexec, nothing on the
system is read or changed), populated like the setup the app was built around.

    python3 tools/screenshots.py [--only NAME]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Never touch the real user's config or state, whatever the code under test does.
_tmp = Path(tempfile.mkdtemp(prefix="dmpkeys-shots-"))
for var in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME"):
    os.environ[var] = str(_tmp / var.lower())

from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtGui import QColor, QFont, QIcon, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication, QStyleFactory, QWidget  # noqa: E402

from dmpkeys.ui.detect import DetectDialog  # noqa: E402
from dmpkeys.ui.dialogs import AboutDialog, ApplyDialog, ResetDialog  # noqa: E402
from dmpkeys.ui.main_window import DEFAULT_SIZE, MINIMUM_SIZE, MainWindow  # noqa: E402
from dmpkeys.ui.session import Session  # noqa: E402
from dmpkeys.ui.worker import BackendWorker  # noqa: E402
from tests.ui.fakes import CONNECTED, LEGACY, FakeBackend, owner_setup  # noqa: E402

OUT = ROOT / "docs" / "screenshots"

# KDE Breeze color schemes (the ones the owner uses), as Qt palettes.
BREEZE = {
    "light": dict(Window="#eff0f1", WindowText="#232629", Base="#fcfcfc", AlternateBase="#eff0f1",
                  Button="#fcfcfc", ButtonText="#232629", Text="#232629", Highlight="#3daee9",
                  HighlightedText="#fcfcfc", ToolTipBase="#f7f7f7", ToolTipText="#232629",
                  PlaceholderText="#707d8a", Link="#2980b9", Light="#ffffff", Midlight="#f5f6f7",
                  Mid="#c7cbd0", Dark="#b0b6bc", Shadow="#474a4c"),
    "dark": dict(Window="#202326", WindowText="#fcfcfc", Base="#141618", AlternateBase="#1d1f22",
                 Button="#292c30", ButtonText="#fcfcfc", Text="#fcfcfc", Highlight="#3daee9",
                 HighlightedText="#fcfcfc", ToolTipBase="#292c30", ToolTipText="#fcfcfc",
                 PlaceholderText="#a1a9b1", Link="#1d99f3", Light="#40464c", Midlight="#33373b",
                 Mid="#1d2023", Dark="#131517", Shadow="#0d0e0f"),
}
DISABLED_TEXT = {"light": "#a0a2a4", "dark": "#6e7175"}
COLOR_SCHEMES = {"light": "BreezeLight", "dark": "BreezeDark"}


def palette(theme: str) -> QPalette:
    pal = QPalette()
    for role, color in BREEZE[theme].items():
        pal.setColor(getattr(QPalette.ColorRole, role), QColor(color))
    for role in ("WindowText", "Text", "ButtonText"):
        pal.setColor(QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, role),
                     QColor(DISABLED_TEXT[theme]))
    return pal


def set_theme(app: QApplication, theme: str) -> None:
    app.setPalette(palette(theme))
    QIcon.setThemeName("breeze-dark" if theme == "dark" else "breeze")


def make_session(*, setup: bool = True, legacy: bool = False, first_run: bool = False) -> Session:
    status = replace(CONNECTED, legacy_hwdb=LEGACY[:1] if legacy else [],
                     legacy_rules=LEGACY[1:] if legacy else [])
    backend = FakeBackend(Path(tempfile.mkdtemp(dir=_tmp)), status=status)
    if setup:
        owner_setup(backend)
    backend.first_run = first_run
    session = Session(backend, BackendWorker(threaded=False), poll_status=False)
    session.load()
    return session


def save(widget: QWidget, name: str, theme: str) -> None:
    widget.show()
    for _ in range(3):
        QApplication.processEvents()
    path = OUT / f"{name}-{theme}.png"
    widget.grab().save(str(path))
    print(path.relative_to(ROOT))


def window(session: Session, key: str | None, size: QSize = DEFAULT_SIZE) -> MainWindow:
    win = MainWindow(session)
    win.resize(size)
    if key:
        win.select_key(key)
    return win


def shots(theme: str) -> dict[str, Callable[[], None]]:
    def main_slider():
        save(window(make_session(), "slider_up"), "main-slider", theme)

    def main_favorite():
        save(window(make_session(), "fav5"), "main-favorite-problem", theme)

    def main_pending():
        session = make_session()
        session.add_custom_key(0x0C0233, "presentation", "Presentation")   # found with Detect
        save(window(session, "calculator"), "main-unapplied-change", theme)

    def main_detected_key():
        session = make_session()
        session.add_custom_key(0x0C0233, "presentation", "Presentation")
        save(window(session, "scan_c0233"), "main-detected-key", theme)

    def main_small():
        save(window(make_session(), "fav2", MINIMUM_SIZE), "main-small", theme)

    def first_run():
        save(window(make_session(setup=False, legacy=True, first_run=True), None),
             "first-run", theme)

    def apply_preview():
        session = make_session(legacy=True)
        dialog = ApplyDialog(session)
        save(dialog, "apply-preview", theme)

    def apply_result():
        session = make_session()
        dialog = ApplyDialog(session)
        dialog.apply_button.click()
        save(dialog, "apply-result", theme)

    def detect():
        session = make_session()
        dialog = DetectDialog(session)
        dialog.start_button.hide()
        dialog.stop_button.show()
        for event in ({"event": "ready", "nodes": ["event10", "event11"], "seconds": 15},
                      {"event": "key", "node": "event11", "code": 113, "pressed": True,
                       "scancode": 0x0C00E2},
                      {"event": "key", "node": "event11", "code": 186, "pressed": True,
                       "scancode": None},
                      {"event": "key", "node": "event11", "code": 425, "pressed": True,
                       "scancode": 0x0C0233},
                      {"event": "key", "node": "event10", "code": 30, "pressed": True,
                       "scancode": 0x070004}):
            dialog.handle_event(event)
        dialog._left = 11
        dialog._tick(advance=False)
        save(dialog, "detect-keys", theme)

    def about():
        save(AboutDialog(), "about", theme)

    def reset():
        save(ResetDialog(), "reset-confirm", theme)

    return {f.__name__: f for f in (main_slider, main_favorite, main_pending, main_detected_key, main_small,
                                    first_run, apply_preview, apply_result, detect, about, reset)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", help="render just this shot (e.g. main_slider)")
    parser.add_argument("--theme", choices=sorted(BREEZE), help="render just this theme")
    args = parser.parse_args()
    if args.theme is None:
        # One process per theme: the Breeze style reads the KDE color scheme once per process.
        for theme in sorted(BREEZE, reverse=True):
            argv = [sys.executable, __file__, "--theme", theme]
            if args.only:
                argv += ["--only", args.only]
            if subprocess.run(argv).returncode:
                return 1
        return 0
    # The Breeze style takes menu bar and header colors from kdeglobals, not the palette.
    scheme = Path(f"/usr/share/color-schemes/{COLOR_SCHEMES[args.theme]}.colors")
    if scheme.exists():
        kdeglobals = Path(os.environ["XDG_CONFIG_HOME"]) / "kdeglobals"
        kdeglobals.parent.mkdir(parents=True, exist_ok=True)
        kdeglobals.write_text(scheme.read_text())
    app = QApplication(sys.argv)
    app.setStyle("Breeze" if "Breeze" in QStyleFactory.keys() else "Fusion")
    app.setFont(QFont("Noto Sans", 10))
    QIcon.setThemeSearchPaths(["/usr/share/icons", "/var/lib/flatpak/exports/share/icons",
                               str(Path.home() / ".local/share/icons")])
    QIcon.setFallbackSearchPaths(["/usr/share/pixmaps"])
    OUT.mkdir(parents=True, exist_ok=True)
    set_theme(app, args.theme)
    for name, shot in shots(args.theme).items():
        if args.only in (None, name):
            shot()
    return 0


if __name__ == "__main__":
    sys.exit(main())
