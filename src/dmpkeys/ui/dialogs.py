"""Apply preview/progress/result, About, and small list dialogs."""
from __future__ import annotations

import html
from typing import TYPE_CHECKING, Iterable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QLayout,
                               QProgressBar, QPushButton, QScrollArea, QStackedWidget, QToolButton,
                               QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from .icons import app_icon
from .session import ApplyPreview, Session
from .theme import Colors

if TYPE_CHECKING:
    from ..core.backend import ApplyReport

PROJECT_URL = "https://github.com/newmca/microsoft-digital-media-pro"


def _rich(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    label.setOpenExternalLinks(True)
    label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    return label


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    font = QFont(label.font())
    font.setPointSizeF(font.pointSizeF() * 1.25)
    font.setBold(True)
    label.setFont(font)
    label.setWordWrap(True)
    return label


def _busy_page(text: str) -> tuple[QWidget, QLabel]:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.addStretch()
    label = QLabel(text)
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    bar = QProgressBar()
    bar.setRange(0, 0)
    bar.setTextVisible(False)
    bar.setMaximumWidth(320)
    layout.addWidget(label)
    layout.addWidget(bar, 0, Qt.AlignmentFlag.AlignHCenter)
    layout.addStretch()
    return page, label


def _list_html(rows: Iterable[tuple[str, str]], color: str | None = None) -> str:
    style = f' style="color:{color}"' if color else ""
    items = "".join(f"<li><b>{html.escape(a)}</b>: <span{style}>{html.escape(b)}</span></li>"
                    for a, b in rows)
    return f"<ul style='margin-left:-20px'>{items}</ul>"


NOT_IMPORTED = ("Your current setup hasn't been imported. Applying turns off the old settings, so "
                "those keys go back to their defaults. To keep them, cancel and choose Import "
                "Current Setup first.")


def preview_html(preview: ApplyPreview, desktop_name: str, colors: Colors,
                 not_imported: bool = False) -> str:
    """The preview as rich text; every value is escaped."""
    parts = []
    if not_imported and preview.disable_files:
        parts.append(f"<p style='color:{colors.pending.name()}'><b>{html.escape(NOT_IMPORTED)}</b></p>")

    def section(title: str, body: str) -> None:
        parts.append(f"<p style='margin-top:10px; margin-bottom:2px'><b>{html.escape(title)}</b></p>"
                     f"{body}")

    if preview.problems:
        section("These keys won't work yet",
                _list_html(preview.problems, colors.error.name()))
    if preview.key_changes:
        section("Keys that send something else", _list_html(preview.key_changes))
    if preview.shortcuts:
        section(f"Shortcuts in {desktop_name}", _list_html(preview.shortcuts))
    if preview.favorites_fix:
        section("Favorites 1–5", f"<p>{html.escape(preview.favorites_fix)}</p>")
    if preview.disable_files:
        files = "".join(f"<li><tt>{html.escape(f)}</tt></li>" for f in preview.disable_files)
        section("Old settings to turn off",
                f"<ul style='margin-left:-20px'>{files}</ul><p style='color:{colors.muted.name()}'>"
                "Each file is renamed to <tt>…disabled-by-dmpkeys</tt>, so you can restore it "
                "later.</p>")
    for warning in preview.warnings:
        parts.append(f"<p style='color:{colors.pending.name()}'>{html.escape(warning)}</p>")
    if not parts:
        parts.append("<p>All keys use their default behavior. Applying removes anything this app "
                     "set up before.</p>")
    return "".join(parts)


class ApplyDialog(QDialog):
    """Preview, then apply in the background, then show the outcome."""

    def __init__(self, session: Session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.setWindowTitle("Apply changes")
        self.setMinimumSize(520, 420)
        self.resize(560, 520)
        self.running = False
        self.report: ApplyReport | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 14)
        layout.setSpacing(10)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.loading, _ = _busy_page("Checking what needs to change…")
        self.stack.addWidget(self.loading)

        # Preview page.
        self.preview_page = QWidget()
        pv = QVBoxLayout(self.preview_page)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.addWidget(_heading("Ready to apply"))
        self.preview_text = _rich()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        iv = QVBoxLayout(inner)
        iv.setContentsMargins(0, 0, 8, 0)
        iv.addWidget(self.preview_text)
        self.details_toggle = QToolButton(text="Technical details", checkable=True)
        self.details_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.details_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.details_toggle.setAutoRaise(True)
        self.details_toggle.toggled.connect(self._toggle_details)
        self.details = _rich()
        self.details.hide()
        iv.addWidget(self.details_toggle)
        iv.addWidget(self.details)
        iv.addStretch()
        scroll.setWidget(inner)
        pv.addWidget(scroll, 1)
        self.password = QLabel()
        self.password.setWordWrap(True)
        pw_row = QHBoxLayout()
        self.password_icon = QLabel()
        pw_row.addWidget(self.password_icon, 0, Qt.AlignmentFlag.AlignTop)
        pw_row.addWidget(self.password, 1)
        pv.addLayout(pw_row)
        self.stack.addWidget(self.preview_page)

        self.working, self.working_label = _busy_page(
            "Applying…\nIf a password prompt appears, enter your admin password.")
        self.stack.addWidget(self.working)

        # Result page.
        self.result_page = QWidget()
        rv = QVBoxLayout(self.result_page)
        rv.setContentsMargins(0, 0, 0, 0)
        self.result_title = _heading("")
        self.result_icon = QLabel()
        self.result_text = _rich()
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_row.addWidget(self.result_icon)
        title_row.addWidget(self.result_title, 1)
        rv.addLayout(title_row)
        rv.addWidget(self.result_text)
        rv.addStretch()
        self.stack.addWidget(self.result_page)

        self.buttons = QDialogButtonBox()
        self.apply_button = self.buttons.addButton("Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_button.setIcon(QIcon.fromTheme("dialog-ok-apply"))
        self.cancel_button = self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.close_button = self.buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self.apply_button.clicked.connect(self._apply)
        self.cancel_button.clicked.connect(self.reject)
        self.close_button.clicked.connect(self.accept)
        layout.addWidget(self.buttons)
        self._set_buttons(apply=False, cancel=True, close=False)

        session.prepare_apply(self._show_preview, self._preview_failed)

    def _set_buttons(self, *, apply: bool, cancel: bool, close: bool) -> None:
        self.apply_button.setVisible(apply)
        self.cancel_button.setVisible(cancel)
        self.close_button.setVisible(close)
        (self.apply_button if apply else self.close_button if close else self.cancel_button).setDefault(True)

    def _show_preview(self, preview: ApplyPreview) -> None:
        colors = Colors.from_palette(self.palette())
        self.preview_text.setText(preview_html(preview, self.session.desktop_name, colors,
                                               not_imported=self.session.offer_import))
        remaps = "".join(f"<li><tt>{html.escape(scan)} → {html.escape(name)}</tt></li>"
                         for scan, name in preview.remaps) or "<li>No scancode remaps.</li>"
        self.details.setText(f"<p>Key mapping file (udev hwdb) entries:</p>"
                             f"<ul style='margin-left:-20px'>{remaps}</ul>")
        if preview.needs_password:
            icon, text = "dialog-password", ("You'll be asked for your admin password, because "
                                             "this changes system files.")
        else:
            icon, text = "dialog-information", "No password needed: only your desktop shortcuts change."
        self.password_icon.setPixmap(QIcon.fromTheme(icon).pixmap(QSize(22, 22)))
        self.password.setText(text)
        self.stack.setCurrentWidget(self.preview_page)
        self._set_buttons(apply=True, cancel=True, close=False)
        self.apply_button.setFocus()

    def _preview_failed(self, error: BaseException) -> None:
        self._show_result(False, "Couldn't prepare the changes", [], [str(error)])

    def _toggle_details(self, on: bool) -> None:
        self.details.setVisible(on)
        self.details_toggle.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)

    def _apply(self) -> None:
        self.running = True
        self.stack.setCurrentWidget(self.working)
        self._set_buttons(apply=False, cancel=False, close=False)
        self.session.apply(self._applied, self._apply_failed)

    def _applied(self, report: ApplyReport) -> None:
        self.running = False
        self.report = report
        errors = list(report.errors)
        for key_id, message in report.key_errors.items():
            key = self.session.key(key_id)
            errors.append(f"{key.label if key else key_id}: {message}")
        title = "Your keys are ready" if report.ok else "Some changes didn't work"
        self._show_result(report.ok, title, report.messages, errors)

    def _apply_failed(self, error: BaseException) -> None:
        self.running = False
        self._show_result(False, "Applying failed", [], [str(error)])

    def _show_result(self, ok: bool, title: str, messages: list[str], errors: list[str]) -> None:
        colors = Colors.from_palette(self.palette())
        self.result_title.setText(title)
        icon = "dialog-positive" if ok and not errors else "dialog-warning"
        self.result_icon.setPixmap(QIcon.fromTheme(icon, QIcon.fromTheme("dialog-information"))
                                   .pixmap(QSize(32, 32)))
        body = ""
        if errors:
            body += "<ul style='margin-left:-20px'>" + "".join(
                f"<li style='color:{colors.error.name()}'>{html.escape(e)}</li>" for e in errors) + "</ul>"
        if messages:
            body += f"<p style='color:{colors.muted.name()}'>" + "<br>".join(
                html.escape(m) for m in messages) + "</p>"
        if ok and not errors:
            body = ("<p>Everything is set up. Your settings stay in place after restarts.</p>"
                    + body)
        self.result_text.setText(body)
        self.stack.setCurrentWidget(self.result_page)
        self._set_buttons(apply=False, cancel=False, close=True)

    def reject(self) -> None:
        if not self.running:   # can't cancel once the password prompt may be up
            super().reject()

    def closeEvent(self, event) -> None:
        if self.running:
            event.ignore()
        else:
            super().closeEvent(event)


class MessageListDialog(QDialog):
    """A heading, a short text and a list (import notes, reset results)."""

    def __init__(self, title: str, heading: str, text: str, items: list[str],
                 parent: QWidget | None = None, *, error_items: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 14)
        layout.addWidget(_heading(heading))
        layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        colors = Colors.from_palette(self.palette())
        body = f"<p>{html.escape(text)}</p>" if text else ""
        if error_items:
            body += "<ul style='margin-left:-20px'>" + "".join(
                f"<li style='color:{colors.error.name()}'>{html.escape(e)}</li>"
                for e in error_items) + "</ul>"
        if items:
            body += "<ul style='margin-left:-20px'>" + "".join(
                f"<li>{html.escape(i)}</li>" for i in items) + "</ul>"
        self.body = _rich(body)
        self.body.setMinimumWidth(420)
        layout.addWidget(self.body)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 16)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        layout.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(QSize(80, 80)))
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignHCenter)
        name = _heading(APP_NAME)
        name.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(name)
        colors = Colors.from_palette(self.palette())
        text = _rich(
            f"<p align='center' style='color:{colors.muted.name()}'>Version {__version__}</p>"
            "<p align='center'>Remap the zoom slider and the special keys of the Microsoft "
            "Digital Media Pro Keyboard on Linux.</p>"
            f"<p align='center'><a href='{PROJECT_URL}'>{PROJECT_URL.removeprefix('https://')}</a></p>"
            f"<p align='center' style='color:{colors.muted.name()}'>Released under the MIT License."
            "<br>Not affiliated with or endorsed by Microsoft.</p>")
        text.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ResetDialog(QDialog):
    """Confirmation before removing everything the app installed."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Remove all changes")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 14)
        layout.addWidget(_heading("Remove all changes made by this app?"))
        layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        text = _rich(
            "<p>This removes the key mapping file, the favorites driver fix and every desktop "
            "shortcut this app created. Your keys go back to how they worked before.</p>"
            "<p>Your choices in this app are kept, so you can apply them again later. "
            "You'll be asked for your admin password.</p>")
        text.setMinimumWidth(420)
        layout.addWidget(text)
        buttons = QDialogButtonBox()
        self.remove_button = QPushButton(QIcon.fromTheme("edit-delete"), "Remove")
        buttons.addButton(self.remove_button, QDialogButtonBox.ButtonRole.DestructiveRole)
        cancel = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        cancel.setDefault(True)
        self.remove_button.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        layout.addWidget(buttons)


def confirm_reset(parent: QWidget) -> bool:
    return ResetDialog(parent).exec() == QDialog.DialogCode.Accepted
