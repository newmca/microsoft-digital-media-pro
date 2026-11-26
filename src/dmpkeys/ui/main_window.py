"""The main window: status header, banners, keyboard diagram, key editor and apply bar."""
from __future__ import annotations

import html

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QAction, QCloseEvent, QFont, QIcon, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QMainWindow, QMessageBox, QPushButton, QScrollArea, QSplitter,
                               QStyle, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from .. import APP_NAME
from ..core.config import Kind
from ..core.keys import DEVICE_NAME
from .dialogs import AboutDialog, ApplyDialog, MessageListDialog, confirm_reset
from .detect import DetectDialog
from .editor import EditorPanel
from .icons import AppIcons, app_icon
from .keyboard_view import KeyboardView, Legend
from .session import Effect, Session
from .text import describe, plural, target_text
from .theme import Colors, app_colors, apply_css, mix
from .widgets import Card

DEFAULT_SIZE = QSize(1200, 760)
MINIMUM_SIZE = QSize(1000, 680)


def _bold(label: QLabel, scale: float = 1.0) -> QLabel:
    font = QFont(label.font())
    font.setBold(True)
    font.setPointSizeF(font.pointSizeF() * scale)
    label.setFont(font)
    return label


def _muted(label: QLabel) -> QLabel:
    label.setProperty("muted", True)
    return label


class StatusDot(QLabel):
    """A small colored dot (connected / not connected)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self._ok = False

    def set_ok(self, ok: bool) -> None:
        self._ok = ok
        self._restyle()

    def _restyle(self) -> None:
        c = app_colors()
        color = c.ok if self._ok else c.muted
        apply_css(self, f"background: {color.name()}; border-radius: 6px;")

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.PaletteChange:
            self._restyle()
        super().changeEvent(event)


class Header(QFrame):
    """Keyboard connection, desktop, the favorites fix toggle and Detect."""

    def __init__(self, session: Session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.setObjectName("header")
        grid = QGridLayout(self)
        grid.setContentsMargins(18, 12, 18, 12)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)

        self.dot = StatusDot()
        self.connection = _bold(QLabel(), 1.1)
        self.device = _muted(QLabel())
        grid.addWidget(self.dot, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(self.connection, 0, 1)
        grid.addWidget(self.device, 1, 1)
        grid.setColumnStretch(2, 1)
        grid.setRowStretch(2, 1)

        self.fix = QCheckBox("Make Favorites 1–5 work")
        self.fix.setToolTip("Favorites 1–5 only send keys with the hid-microsoft driver. The app "
                            "installs a small fix for that once, with your admin password.")
        self.fix.toggled.connect(self._fix_toggled)
        # One short line, aligned with the checkbox text; the full story is in the tooltip.
        self.fix_note = _muted(QLabel())
        self.fix_note.setToolTip(self.fix.toolTip())
        style = self.fix.style()
        indent = (style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth)
                  + style.pixelMetric(QStyle.PixelMetric.PM_CheckBoxLabelSpacing))
        self.fix_note.setContentsMargins(indent, 0, 0, 0)
        grid.addWidget(self.fix, 0, 3)
        grid.addWidget(self.fix_note, 1, 3)

        self.detect = QPushButton(QIcon.fromTheme("input-keyboard"), "Detect keys…")
        self.detect.setToolTip("Press keys to check which ones this app recognizes.")
        grid.addWidget(self.detect, 0, 4, 2, 1, Qt.AlignmentFlag.AlignVCenter)

        session.statusChanged.connect(self.refresh)
        session.changed.connect(self.refresh)
        self.refresh()

    def _fix_toggled(self, on: bool) -> None:
        if on != self.session.favorites_fix:
            self.session.set_favorites_fix(on)

    def refresh(self) -> None:
        status = self.session.status
        connected = bool(status and status.connected)
        self.dot.set_ok(connected)
        if status is None:
            self.connection.setText("Checking for the keyboard…")
        else:
            self.connection.setText("Keyboard connected" if connected else "Keyboard not connected")
        where = self.session.desktop_name
        self.device.setText(f"{DEVICE_NAME.removeprefix('Microsoft ')} · {where}"
                            if connected else f"You can still set up keys. · {where}")
        self.fix.blockSignals(True)
        self.fix.setChecked(self.session.favorites_fix)
        self.fix.blockSignals(False)
        self.fix_note.setText(self._fix_text())

    def _fix_text(self) -> str:
        status = self.session.status
        installed = bool(status and status.favorites_fix_installed)
        if not self.session.favorites_fix:
            return "Off. Apply removes the fix." if installed else "Off: Favorites 1–5 send nothing."
        if not installed:
            return "Installed when you apply (admin password, once)."
        if status and status.connected and not status.favorites_active:
            return "Installed. Replug the keyboard to start it."
        return "Installed and working."


class Banner(Card):
    """A message strip under the header with optional buttons and a close button."""

    def __init__(self, tone: str, icon: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.set_tone(tone)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 8, 8)
        row.setSpacing(10)
        self.icon = QLabel()
        self.icon.setPixmap(QIcon.fromTheme(icon).pixmap(QSize(22, 22)))
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self.text, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(6)
        row.addLayout(self.actions)
        self.close_button = QToolButton()
        self.close_button.setIcon(QIcon.fromTheme("window-close"))
        self.close_button.setAutoRaise(True)
        self.close_button.setToolTip("Dismiss")
        self.close_button.clicked.connect(self.hide)
        row.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)


class ChangesList(QTreeWidget):
    """Every key that doesn't do its default, with its status. Click to select."""

    def __init__(self, session: Session, icons: AppIcons, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.icons = icons
        self.setColumnCount(3)
        self.setHeaderLabels(["Key", "Does", "Status"])
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setIconSize(QSize(18, 18))
        self.setAlternatingRowColors(True)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.setAccessibleName("Changes")

    def refresh(self) -> None:
        c = Colors.from_palette(self.palette())
        selected = self.currentItem().data(0, Qt.ItemDataRole.UserRole) if self.currentItem() else None
        self.blockSignals(True)
        self.clear()
        if self.session.favorites_fix_pending:
            # Not a key, but a pending change all the same; counted in the apply bar.
            item = QTreeWidgetItem(["Favorites fix", self.session.favorites_fix_change,
                                    "Not applied"])
            item.setForeground(2, c.pending)
            item.setToolTip(0, "Favorites 1–5 need the hid-microsoft driver. Turn the fix on or "
                               "off at the top of the window.")
            self.addTopLevelItem(item)
        for view in self.session.views().values():
            if view.effect == Effect.DEFAULT and not view.pending and not view.error:
                continue
            does = describe(view.action, view.key)
            item = QTreeWidgetItem([view.key.label, does, ""])
            item.setData(0, Qt.ItemDataRole.UserRole, view.id)
            item.setToolTip(1, does)
            if view.action.kind == Kind.APP:
                item.setIcon(1, self.icons.icon(view.action.target))
                item.setText(1, f"Opens {target_text(view.action)}")
            if view.error:
                item.setText(2, "Problem")
                item.setForeground(2, c.error)
                item.setToolTip(2, view.error)
            elif view.pending:
                item.setText(2, "Not applied")
                item.setForeground(2, c.pending)
            else:
                item.setText(2, "Applied")
                item.setForeground(2, c.muted)
            self.addTopLevelItem(item)
            if view.id == selected:
                self.setCurrentItem(item)
        self.blockSignals(False)

    def select_key(self, key_id: str) -> None:
        self.blockSignals(True)
        self.setCurrentItem(None)
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == key_id:
                self.setCurrentItem(item)
        self.blockSignals(False)


class ApplyBar(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("applybar")
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 10, 18, 10)
        self.icon = QLabel()
        self.text = QLabel()
        self.checking = _muted(QLabel("Checking…"))
        self.apply = QPushButton(QIcon.fromTheme("dialog-ok-apply"), "Apply…")
        self.apply.setMinimumWidth(120)
        row.addWidget(self.icon)
        row.addWidget(self.text)
        row.addWidget(self.checking)
        row.addStretch()
        row.addWidget(self.apply)


class MainWindow(QMainWindow):
    def __init__(self, session: Session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.icons = AppIcons()
        self._long_task = False   # apply, reset or import running
        self.apply_dialog: ApplyDialog | None = None
        self.detect_dialog: DetectDialog | None = None
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(DEFAULT_SIZE)
        self.setMinimumSize(MINIMUM_SIZE)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        self.header = Header(session)
        self.header.detect.clicked.connect(self.detect_keys)
        root.addWidget(self.header)
        root.addWidget(self._line())

        # Banners.
        banners = QVBoxLayout()
        banners.setContentsMargins(16, 10, 16, 0)
        banners.setSpacing(8)
        self.error_banner = Banner("error", "dialog-error")
        self.import_banner = Banner("info", "document-import")
        self.import_banner.text.setText(
            "<b>This keyboard was set up before, outside this app.</b> Import that setup to manage "
            "it here.")
        import_button = QPushButton("Import current setup")
        import_button.clicked.connect(self.import_setup)
        self.import_banner.actions.addWidget(import_button)
        self.legacy_banner = Banner("pending", "dialog-warning")
        self.legacy_banner.close_button.hide()
        self.keep_legacy = QCheckBox("Keep them")
        self.keep_legacy.setToolTip("Leave those files in place. They may override this app's "
                                    "settings for the same keys.")
        self.keep_legacy.toggled.connect(self._keep_legacy_toggled)
        self.legacy_banner.actions.addWidget(self.keep_legacy)
        for banner in (self.error_banner, self.import_banner, self.legacy_banner):
            banner.hide()
            banners.addWidget(banner)
        self._import_dismissed = False
        self.import_banner.close_button.clicked.connect(self._dismiss_import)
        root.addLayout(banners)

        # Diagram and changes on the left, editor on the right.
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(16, 12, 8, 8)
        lv.setSpacing(10)
        self.keyboard = KeyboardView(self.icons)
        self.keyboard.keySelected.connect(self.select_key)
        lv.addWidget(self.keyboard)
        self.legend = Legend()
        lv.addWidget(self.legend)
        changes_head = QHBoxLayout()
        self.changes_title = _bold(QLabel("Changes"))
        changes_head.addWidget(self.changes_title)
        changes_head.addStretch()
        lv.addSpacing(4)
        lv.addLayout(changes_head)
        self.changes = ChangesList(session, self.icons)
        self.changes.currentItemChanged.connect(self._change_clicked)
        self.changes_empty = _muted(QLabel("No changes yet. Click a key on the keyboard to "
                                           "change what it does."))
        self.changes_empty.setWordWrap(True)
        lv.addWidget(self.changes, 1)
        lv.addWidget(self.changes_empty)
        lv.addStretch(0)
        split.addWidget(left)

        self.editor = EditorPanel(session, self.icons)
        scroll = QScrollArea()
        scroll.setWidget(self.editor)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(360)
        self.editor_scroll = scroll
        editor_box = QWidget()
        ev = QHBoxLayout(editor_box)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.setSpacing(0)
        ev.addWidget(self._line(vertical=True))
        ev.addWidget(scroll)
        split.addWidget(editor_box)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([800, 400])
        root.addWidget(split, 1)

        root.addWidget(self._line())
        self.apply_bar = ApplyBar()
        self.apply_bar.apply.clicked.connect(self.apply_changes)
        root.addWidget(self.apply_bar)

        self._build_menus()
        self._restyle()

        session.changed.connect(self._refresh)
        session.planChanged.connect(self._refresh_apply_bar)
        session.statusChanged.connect(self._refresh_banners)
        session.errorOccurred.connect(self.show_error)
        self._refresh()
        self._refresh_banners()
        session.apps(self._apps_loaded)

    # --- building -----------------------------------------------------------------------
    def _line(self, vertical: bool = False) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine if vertical else QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        line.setObjectName("separator")
        return line

    def _build_menus(self) -> None:
        menu = self.menuBar().addMenu("&Keyboard")
        self.detect_action = QAction(QIcon.fromTheme("input-keyboard"), "&Detect Keys…", self)
        self.detect_action.triggered.connect(self.detect_keys)
        self.apply_action = QAction(QIcon.fromTheme("dialog-ok-apply"), "&Apply Changes…", self)
        self.apply_action.setShortcut(QKeySequence("Ctrl+Return"))
        self.apply_action.triggered.connect(self.apply_changes)
        self.import_action = QAction(QIcon.fromTheme("document-import"), "&Import Current Setup…",
                                     self)
        self.import_action.triggered.connect(self.import_setup)
        self.reset_action = QAction(QIcon.fromTheme("edit-delete"),
                                    "&Remove All Changes Made by This App…", self)
        self.reset_action.triggered.connect(self.reset_all)
        quit_action = QAction(QIcon.fromTheme("application-exit"), "&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        for action in (self.detect_action, self.apply_action, None, self.import_action,
                       self.reset_action, None, quit_action):
            if action is None:
                menu.addSeparator()
            else:
                menu.addAction(action)
        help_menu = self.menuBar().addMenu("&Help")
        about = QAction(app_icon(), f"&About {APP_NAME}", self)
        about.triggered.connect(lambda: AboutDialog(self).exec())
        help_menu.addAction(about)

    def _restyle(self) -> None:
        c = app_colors()
        header_bg = mix(c.window, c.key, 0.5)
        apply_css(self, 
            f"QLabel[muted=\"true\"] {{ color: {c.muted.name()}; }}"
            f"QFrame#header, QFrame#applybar {{ background: {header_bg.name()}; }}"
            f"QFrame#separator {{ color: {mix(c.window, c.text, 0.14).name()}; }}")

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.PaletteChange:
            self._restyle()
        super().changeEvent(event)

    # --- refreshing ---------------------------------------------------------------------
    def _refresh(self) -> None:
        self.keyboard.set_views(self.session.views())
        self.changes.refresh()
        has_changes = self.changes.topLevelItemCount() > 0
        self.changes.setVisible(has_changes)
        self.changes_empty.setVisible(not has_changes)
        self.changes_title.setText(f"Changes ({self.changes.topLevelItemCount()})"
                                   if has_changes else "Changes")
        self._refresh_apply_bar()

    def _refresh_apply_bar(self) -> None:
        bar = self.apply_bar
        n = self.session.pending_count
        c = Colors.from_palette(self.palette())
        legacy = bool(self.session.legacy_files) and not self.session.keep_legacy
        icon = QIcon.fromTheme("emblem-warning")
        if n == 1 and self.session.favorites_fix_pending:
            bar.text.setText("Favorites fix not installed yet" if self.session.favorites_fix
                             else "Favorites fix not removed yet")
        elif n:
            bar.text.setText(f"{plural(n, 'change')} not applied")
        elif legacy:
            bar.text.setText("Apply to turn off the old settings")
        else:
            bar.text.setText("All changes applied")
            icon = QIcon.fromTheme("emblem-ok-symbolic", QIcon.fromTheme("dialog-ok"))
        bar.icon.setPixmap(icon.pixmap(QSize(18, 18)))
        bar.text.setStyleSheet("" if n or legacy else f"color: {c.muted.name()};")
        errors = len(self.session.plan.errors) if self.session.plan else 0
        if errors:
            bar.text.setText(bar.text.text() + f" · {plural(errors, 'key')} with a problem")
        bar.checking.setVisible(self.session.plan_loading)
        can_apply = (n > 0 or legacy) and not self._long_task
        bar.apply.setEnabled(can_apply)
        bar.apply.setDefault(can_apply)
        self.apply_action.setEnabled(can_apply)

    def _refresh_banners(self) -> None:
        files = self.session.legacy_files
        if files:
            listed = "<br>".join(f"<tt>{html.escape(f)}</tt>" for f in files)
            self.legacy_banner.text.setText(
                "<b>Found settings for this keyboard made outside this app.</b> They'll be turned "
                "off when you apply (renamed to <tt>*.disabled-by-dmpkeys</tt>) so they don't "
                f"clash with this app.<br>{listed}")
        self.legacy_banner.setVisible(bool(files))
        self.import_banner.setVisible(self.session.offer_import and not self._import_dismissed)
        self.import_action.setEnabled(bool(files) or self.session.first_run)
        self._refresh_apply_bar()

    def _apps_loaded(self, apps: list) -> None:
        self.icons.update(apps)
        self._refresh()

    # --- selection ----------------------------------------------------------------------
    def select_key(self, key_id: str) -> None:
        if self.keyboard.selected != key_id:
            self.keyboard.select(key_id, notify=False)
        self.changes.select_key(key_id)
        self.editor.show_key(key_id)
        self.editor_scroll.verticalScrollBar().setValue(0)

    def _change_clicked(self, item: QTreeWidgetItem | None, _prev: QTreeWidgetItem | None) -> None:
        key_id = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        if key_id:
            self.select_key(key_id)
        elif item is not None:   # the favorites fix row: its switch is in the header
            self.header.fix.setFocus(Qt.FocusReason.OtherFocusReason)

    # --- actions ------------------------------------------------------------------------
    def _keep_legacy_toggled(self, keep: bool) -> None:
        self.session.keep_legacy = keep
        self._refresh_apply_bar()

    def _dismiss_import(self) -> None:
        self._import_dismissed = True

    def show_error(self, message: str) -> None:
        self.error_banner.text.setText(html.escape(message))
        self.error_banner.show()

    def apply_changes(self) -> None:
        if self._long_task:
            return
        dialog = ApplyDialog(self.session, self)
        self._long_task = True
        self._refresh_apply_bar()
        dialog.finished.connect(lambda _r: self._task_done())
        dialog.open()
        self.apply_dialog = dialog

    def _task_done(self) -> None:
        self._long_task = False
        self._refresh_apply_bar()

    def detect_keys(self) -> None:
        dialog = DetectDialog(self.session, self)
        dialog.keySeen.connect(self._detected)
        dialog.keyAdded.connect(self._detected)
        dialog.open()
        self.detect_dialog = dialog

    def _detected(self, key_id: str) -> None:
        self.select_key(key_id)
        self.keyboard.flash(key_id)

    def import_setup(self) -> None:
        if self._long_task:
            return
        self._long_task = True
        self.import_banner.hide()
        self._import_dismissed = True
        self.session.import_existing(self._imported, self._import_failed)

    def _imported(self, notes: list[str]) -> None:
        self._task_done()
        text = ("These keys now show what they did before. Press Apply to let this app manage "
                "them." if notes else "Nothing to import: no keys were customized.")
        MessageListDialog("Import current setup", "Setup imported", text, notes, self).open()

    def _import_failed(self, error: BaseException) -> None:
        self._task_done()
        self.show_error(f"Import failed: {error}")

    def reset_all(self) -> None:
        if self._long_task or not confirm_reset(self):
            return
        self._long_task = True
        self._refresh_apply_bar()
        self.session.reset_all(self._reset_done, self._reset_failed)

    def _reset_done(self, report) -> None:
        self._task_done()
        heading = "Changes removed" if report.ok else "Couldn't remove everything"
        MessageListDialog("Remove all changes", heading,
                          "Press Apply to set your keys up again." if report.ok else "",
                          report.messages, self, error_items=report.errors).open()

    def _reset_failed(self, error: BaseException) -> None:
        self._task_done()
        self.show_error(f"Removing changes failed: {error}")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._long_task and self.session.worker.busy:
            QMessageBox.information(self, APP_NAME, "Please wait until the current task "
                                                    "finishes.")
            event.ignore()
            return
        self.session.shutdown()
        super().closeEvent(event)
