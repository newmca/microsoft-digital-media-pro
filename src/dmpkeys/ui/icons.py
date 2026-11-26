"""Icons: the app's own icon and icons of installed apps."""
from __future__ import annotations

import os
from importlib import resources
from typing import Iterable

from PySide6.QtGui import QIcon

from .. import APP_ID
from ..core.apps import App


def app_icon() -> QIcon:
    """The copy shipped inside the package, so it always matches the running version
    (a theme lookup can find a stale icon from another install); the theme icon
    only if the bundled file is missing."""
    bundled = resources.files("dmpkeys.ui").joinpath(f"resources/{APP_ID}.svg")
    if bundled.is_file():
        return QIcon(str(bundled))
    return QIcon.fromTheme(APP_ID)


def icon_from_name(name: str, fallback: str = "application-x-executable") -> QIcon:
    """A desktop entry's Icon= value (a theme name or an absolute path), else ``fallback``."""
    icon = QIcon()
    if os.path.isabs(name):
        icon = QIcon(name) if os.path.exists(name) else QIcon()
    elif name:
        icon = QIcon.fromTheme(name)
    return icon if not icon.isNull() or not fallback else QIcon.fromTheme(fallback)


class AppIcons:
    """Icons for desktop ids, filled in once the installed app list has loaded."""

    def __init__(self) -> None:
        self._names: dict[str, str] = {}
        self._cache: dict[str, QIcon] = {}

    def update(self, apps: Iterable[App]) -> None:
        self._names = {a.desktop_id: a.icon for a in apps}
        self._cache.clear()

    def icon(self, desktop_id: str) -> QIcon:
        if desktop_id not in self._cache:
            self._cache[desktop_id] = icon_from_name(self._names.get(desktop_id, ""))
        return self._cache[desktop_id]
