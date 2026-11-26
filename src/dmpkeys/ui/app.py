"""GUI entry point: ``dmpkeys`` with no command calls run()."""
from __future__ import annotations

import sys

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from .. import APP_ID, APP_NAME, __version__
from ..core.backend import Backend
from .icons import app_icon
from .main_window import MainWindow
from .session import Session


def run(argv: list[str] | None = None) -> int:
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("dmpkeys")
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    QGuiApplication.setDesktopFileName(APP_ID)
    app.setWindowIcon(app_icon())

    try:
        backend = Backend()
    except Exception as e:  # e.g. an unreadable config file
        QMessageBox.critical(None, APP_NAME, f"{APP_NAME} couldn't start:\n\n{e}")
        return 1
    session = Session(backend)
    window = MainWindow(session)
    window.show()
    session.load()
    return app.exec()
