"""Runs backend calls on one background thread, strictly one at a time.

The backend does D-Bus calls (jeepney connections are not thread-safe) and runs
pkexec, which blocks until the user answers the password prompt. Every backend
call the UI makes goes through a single BackendWorker so calls never overlap
and the window stays responsive.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot

log = logging.getLogger(__name__)

Done = Callable[[Any], None]
Failed = Callable[[BaseException], None]


@dataclass
class _Job:
    fn: Callable[[], Any]
    on_done: Done | None
    on_error: Failed | None
    result: Any = None
    error: BaseException | None = None


class _Runner(QObject):
    """Lives on the worker thread and executes queued jobs in order."""

    finished = Signal(object)

    @Slot(object)
    def run(self, job: _Job) -> None:
        try:
            job.result = job.fn()
        except Exception as e:  # reported to the submitter, never swallowed
            job.error = e
        self.finished.emit(job)


class BackendWorker(QObject):
    """Queue of backend calls. Callbacks run on the GUI thread.

    With ``threaded=False`` jobs run immediately on the calling thread; tests and
    the screenshot tool use that to get deterministic, synchronous behaviour.
    """

    failed = Signal(str)        # an error no caller handled
    _submit = Signal(object)

    def __init__(self, parent: QObject | None = None, *, threaded: bool = True):
        super().__init__(parent)
        self._pending = 0
        self._thread: QThread | None = None
        if threaded:
            self._thread = QThread(self)
            self._thread.setObjectName("dmpkeys-backend")
            self._runner = _Runner()
            self._runner.moveToThread(self._thread)
            self._submit.connect(self._runner.run)
            self._runner.finished.connect(self._finish)
            self._thread.finished.connect(self._runner.deleteLater)
            self._thread.start()

    @property
    def threaded(self) -> bool:
        return self._thread is not None

    @property
    def busy(self) -> bool:
        return self._pending > 0

    def submit(self, fn: Callable[[], Any], on_done: Done | None = None,
               on_error: Failed | None = None) -> None:
        """Queue ``fn``; afterwards call ``on_done(result)`` or ``on_error(exception)``."""
        job = _Job(fn, on_done, on_error)
        self._pending += 1
        if self._thread is None:
            try:
                job.result = fn()
            except Exception as e:
                job.error = e
            self._finish(job)
        else:
            self._submit.emit(job)

    @Slot(object)
    def _finish(self, job: _Job) -> None:
        self._pending -= 1
        if job.error is not None:
            if job.on_error is not None:
                job.on_error(job.error)
            else:
                log.error("backend call failed", exc_info=job.error)
                self.failed.emit(str(job.error) or type(job.error).__name__)
        elif job.on_done is not None:
            job.on_done(job.result)

    def shutdown(self, timeout_ms: int = 15000) -> bool:
        """Stop the thread after the queued jobs finish. False if it didn't stop in time."""
        if self._thread is None:
            return True
        self._thread.quit()
        return self._thread.wait(timeout_ms)
