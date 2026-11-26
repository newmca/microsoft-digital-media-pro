"""Fixtures for UI tests: an offscreen QApplication, a fake backend and a synchronous session."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace  # noqa: E402
from typing import Callable  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QElapsedTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from dmpkeys.ui.main_window import MainWindow  # noqa: E402
from dmpkeys.ui.session import Session  # noqa: E402
from dmpkeys.ui.worker import BackendWorker  # noqa: E402

from .fakes import CONNECTED, LEGACY, FakeBackend  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def backend(tmp_path) -> FakeBackend:
    return FakeBackend(tmp_path)


@pytest.fixture
def legacy_backend(tmp_path) -> FakeBackend:
    status = replace(CONNECTED, legacy_hwdb=LEGACY[:1], legacy_rules=LEGACY[1:])
    return FakeBackend(tmp_path, status=status)


def make_session(backend: FakeBackend) -> Session:
    session = Session(backend, BackendWorker(threaded=False), poll_status=False)
    session.load()
    return session


@pytest.fixture
def session(qapp, backend) -> Session:
    return make_session(backend)


@pytest.fixture
def window(session):
    win = MainWindow(session)
    yield win
    win.close()


def wait_until(condition: Callable[[], bool], timeout_ms: int = 5000) -> bool:
    """Run the event loop until ``condition()`` holds or the timeout passes."""
    timer = QElapsedTimer()
    timer.start()
    while not condition():
        if timer.elapsed() > timeout_ms:
            return False
        QApplication.processEvents()
    return True
