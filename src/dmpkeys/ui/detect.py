"""Detect keys: read raw key presses through the root helper and match them to the catalog.

The helper (``dmpkeys-helper capture SECONDS``, run with pkexec) prints JSON
lines: ``ready``, then ``key`` events, then ``done``. It stops early when its
stdin closes; the process runs as root and can't be killed from the session.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Sequence

from PySide6.QtCore import QCoreApplication, QProcess, QProcessEnvironment, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QInputDialog, QLabel,
                               QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from ..core import host, keycodes
from ..core.keys import KeyDef
from .session import Session
from .theme import Colors

CAPTURE_SECONDS = 15
# Favorites 1-5 have no scancode; through hid-microsoft they send F14-F18.
FAVORITE_CODES = {184 + n: f"fav{n + 1}" for n in range(5)}
TYPING_PAGE = 0x07   # HID keyboard page: the normal typing keys, not ours to remap
AUTH_FAILED_EXIT = (126, 127)


class LineParser:
    """Turns a byte stream into JSON objects, one per complete line; junk lines are skipped."""

    def __init__(self) -> None:
        self._buffer = b""

    def feed(self, data: bytes) -> list[dict]:
        self._buffer += data
        *lines, self._buffer = self._buffer.split(b"\n")
        events = []
        for line in lines:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
        return events


@dataclass(frozen=True)
class Press:
    """A key press from the helper, matched against the known keys."""
    key: KeyDef | None        # None: a special key this app doesn't know yet
    scancode: int | None
    code: int

    @property
    def native(self) -> str | None:
        kk = keycodes.by_code(self.code)
        return kk.name if kk else None

    @property
    def addable(self) -> bool:
        """It can become a custom key: it has a scancode and a known kernel key."""
        return self.scancode is not None and self.native is not None

    @property
    def identity(self) -> str:
        return self.key.id if self.key else f"scan:{self.scancode}"


def identify(event: dict, keys: Sequence[KeyDef]) -> Press | None:
    """The Press for a ``key`` event, or None for releases and ordinary typing keys."""
    if event.get("event") != "key" or not event.get("pressed"):
        return None
    try:
        code = int(event["code"])
    except (KeyError, TypeError, ValueError):
        return None
    scancode = event.get("scancode")
    if isinstance(scancode, int):
        key = next((k for k in keys if k.scancode == scancode), None)
        if key is None and scancode >> 16 == TYPING_PAGE:
            return None
        return Press(key, scancode, code)
    fav = FAVORITE_CODES.get(code)
    if fav is not None:
        key = next((k for k in keys if k.id == fav), None)
        return Press(key, None, code) if key else None
    return None


class DetectDialog(QDialog):
    """Listens for key presses for a few seconds and lists what it saw."""

    keySeen = Signal(str)     # a known key was pressed
    keyAdded = Signal(str)    # the user added an unknown key as a custom key

    def __init__(self, session: Session, parent: QWidget | None = None,
                 seconds: int = CAPTURE_SECONDS):
        super().__init__(parent)
        self.session = session
        self.seconds = seconds
        self.setWindowTitle("Detect keys")
        self.setMinimumSize(500, 440)
        self.process: QProcess | None = None
        self._parser = LineParser()
        self._rows: dict[str, QListWidgetItem] = {}
        self._done_event: dict | None = None
        self._left = 0
        self._countdown = QTimer(self, interval=1000)
        self._countdown.timeout.connect(self._tick)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 14)
        layout.setSpacing(10)
        title = QLabel("Detect keys")
        font = QFont(title.font())
        font.setPointSizeF(font.pointSizeF() * 1.25)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        intro = QLabel("Press the special keys to check which ones this app recognizes. Keys "
                       "that aren't confirmed yet get confirmed, and keys it doesn't know can be "
                       "added. Reading the keyboard directly needs your admin password.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        status_row = QHBoxLayout()
        self.status_icon = QLabel()
        self.status = QLabel("Not listening.")
        self.status.setWordWrap(True)
        status_row.addWidget(self.status_icon)
        status_row.addWidget(self.status, 1)
        layout.addLayout(status_row)

        self.list = QListWidget()
        self.list.setIconSize(QSize(20, 20))
        self.list.setAccessibleName("Detected keys")
        self.placeholder = QListWidgetItem("Pressed keys appear here.")
        self.placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
        self.list.addItem(self.placeholder)
        layout.addWidget(self.list, 1)

        self.buttons = QDialogButtonBox()
        self.start_button = QPushButton(QIcon.fromTheme("media-record"), "Start listening")
        self.stop_button = QPushButton(QIcon.fromTheme("media-playback-stop"), "Stop")
        self.buttons.addButton(self.start_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.buttons.addButton(self.stop_button, QDialogButtonBox.ButtonRole.ActionRole)
        close = self.buttons.addButton(QDialogButtonBox.StandardButton.Close)
        close.clicked.connect(self.close)
        self.start_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.hide()
        self.start_button.setDefault(True)
        layout.addWidget(self.buttons)

    @property
    def running(self) -> bool:
        return self.process is not None

    # --- process ------------------------------------------------------------------------
    def start(self) -> None:
        if self.running:
            return
        argv = self.session.capture_argv(self.seconds)
        self._parser = LineParser()
        self._done_event = None
        self.process = QProcess(self)
        self.process.setProcessEnvironment(_host_environment())
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self._set_status("Waiting for your password…", "dialog-password")
        self.start_button.hide()
        self.stop_button.show()
        self.stop_button.setEnabled(True)
        # stdin stays open: closing it is how we ask the helper to stop.
        self.process.start(argv[0], argv[1:])

    def stop(self) -> None:
        """Ask the helper to stop (it exits when its stdin closes)."""
        if self.process is not None:
            self.process.closeWriteChannel()
            self.stop_button.setEnabled(False)
            self._set_status("Stopping…", None)

    def _read(self) -> None:
        if self.process is None:
            return
        for event in self._parser.feed(bytes(self.process.readAllStandardOutput().data())):
            self.handle_event(event)

    def handle_event(self, event: dict) -> None:
        kind = event.get("event")
        if kind == "ready":
            self._left = int(event.get("seconds") or self.seconds)
            self._countdown.start()
            self._tick(advance=False)
        elif kind == "key":
            press = identify(event, self.session.keys())
            if press is not None:
                self._add_press(press)
        elif kind == "done":
            self._done_event = event

    def _finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        if self.process is not None:
            self._read()
        self._countdown.stop()
        done = self._done_event
        if done is not None and done.get("ok"):
            self._set_status("Finished listening.", "dialog-ok")
        elif done is not None:
            self._set_status(f"Couldn't read the keyboard: {done.get('error') or 'unknown error'}",
                             "dialog-error")
        elif exit_code in AUTH_FAILED_EXIT:
            self._set_status("The password prompt was cancelled.", "dialog-warning")
        else:
            self._set_status("Key detection stopped unexpectedly.", "dialog-error")
        self._reset_buttons()

    def _process_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._countdown.stop()
            self._set_status("Couldn't start key detection (is pkexec installed?).", "dialog-error")
            self._reset_buttons()

    def _reset_buttons(self) -> None:
        if self.process is not None:
            self.process.deleteLater()
        self.process = None
        self.stop_button.hide()
        self.start_button.setText("Listen again")
        self.start_button.show()

    def _tick(self, advance: bool = True) -> None:
        if advance:
            self._left = max(0, self._left - 1)
        self._set_status(f"Listening — press keys now ({self._left} s left).", "input-keyboard")

    def _set_status(self, text: str, icon: str | None) -> None:
        self.status.setText(text)
        pix = QIcon.fromTheme(icon).pixmap(QSize(22, 22)) if icon else None
        if pix is not None and not pix.isNull():
            self.status_icon.setPixmap(pix)
            self.status_icon.show()
        else:
            self.status_icon.hide()

    # --- results ------------------------------------------------------------------------
    def _add_press(self, press: Press) -> None:
        if self.placeholder is not None:
            self.list.takeItem(self.list.row(self.placeholder))
            self.placeholder = None
        first_time = press.identity not in self._rows
        newly_confirmed = False
        if press.key is not None:
            view = self.session.view(press.key.id)
            newly_confirmed = first_time and view is not None and not view.confirmed
            self.session.confirm(press.key.id)
            self.keySeen.emit(press.key.id)
        if not first_time:
            self.list.setCurrentItem(self._rows[press.identity])
            return
        item = QListWidgetItem()
        self._rows[press.identity] = item
        self.list.insertItem(0, item)
        if press.key is not None:
            note = "confirmed on your keyboard" if newly_confirmed else "recognized"
            item.setText(f"{press.key.label} — {note}")
            item.setIcon(QIcon.fromTheme("dialog-ok"))
            item.setToolTip(self._tech(press))
            self.list.setCurrentItem(item)
        else:
            self._unknown_row(item, press)

    def _tech(self, press: Press) -> str:
        code = f"code 0x{press.scancode:x}" if press.scancode is not None else "no scancode"
        return f"{code}, sends {press.native or press.code}"

    def _unknown_row(self, item: QListWidgetItem, press: Press) -> None:
        item.setIcon(QIcon.fromTheme("dialog-question"))
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(self.list.iconSize().width() + 10, 4, 6, 4)
        colors = Colors.from_palette(self.palette())
        label = QLabel(f"A key this app doesn't know<br><small style='color:{colors.muted.name()}'>"
                       f"{self._tech(press)}</small>")
        label.setTextFormat(Qt.TextFormat.RichText)
        h.addWidget(label, 1)
        if press.addable:
            add = QPushButton(QIcon.fromTheme("list-add"), "Add…")
            add.setToolTip("Add it to the keyboard so you can change what it does.")
            add.clicked.connect(lambda: self._add_custom(press, item, add))
            h.addWidget(add)
        item.setSizeHint(row.sizeHint())
        self.list.setItemWidget(item, row)

    def _add_custom(self, press: Press, item: QListWidgetItem, button: QPushButton) -> None:
        label, ok = QInputDialog.getText(self, "Add key", "Name for this key:",
                                         text=f"Key {press.scancode:x}")
        if ok and label.strip():
            self.add_custom(press, label.strip(), item, button)

    def add_custom(self, press: Press, label: str, item: QListWidgetItem | None = None,
                   button: QPushButton | None = None) -> None:
        scancode, native = press.scancode, press.native
        if scancode is None or native is None:
            return   # nothing to remap: the row offers no Add button for such presses

        def added(key: KeyDef) -> None:
            if button is not None:
                button.setEnabled(False)
                button.setText("Added")
            if item is not None:
                item.setIcon(QIcon.fromTheme("dialog-ok"))
            self.keyAdded.emit(key.id)
        self.session.add_custom_key(scancode, native, label, added)

    # --- closing ------------------------------------------------------------------------
    def done(self, result: int) -> None:
        if self.process is not None:
            # The helper is root and can't be killed: ask it to stop and let it finish on
            # its own after this dialog is gone.
            process, self.process = self.process, None
            process.finished.disconnect()
            process.readyReadStandardOutput.disconnect()
            process.errorOccurred.disconnect()
            process.setParent(QCoreApplication.instance())
            process.finished.connect(process.deleteLater)
            process.closeWriteChannel()
        self._countdown.stop()
        super().done(result)


def _host_environment() -> QProcessEnvironment:
    """pkexec runs on the host: give it the host's environment, not the AppImage's."""
    env = QProcessEnvironment()
    for name, value in host.host_env().items():
        env.insert(name, value)
    return env
