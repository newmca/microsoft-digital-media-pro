"""The panel that shows the selected key and edits what it does."""
from __future__ import annotations

import html
import os
from urllib.parse import urlparse

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QGridLayout, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton,
                               QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from ..core.config import Action, Kind
from ..core.keys import GROUP_LABELS, Group, KeyDef
from . import presets
from .icons import AppIcons
from .keyboard_view import UNVERIFIED_TIP
from .keynames import human_name
from .pickers import AppPicker, KeyPicker
from .session import KeyView, Session
from .text import KIND_LABELS, describe, scancode_text, short_path
from .theme import app_colors, apply_css, mix
from .widgets import Card

# Radio layout: keyboard-level changes on the left, desktop actions on the right.
LEFT_KINDS = (Kind.DEFAULT, Kind.KEY, Kind.DISABLE)
RIGHT_KINDS = (Kind.APP, Kind.FOLDER, Kind.URL, Kind.COMMAND)
NEEDS_TARGET_HINT = {
    Kind.KEY: "Choose a key below. It's saved as soon as you click it.",
    Kind.APP: "Choose an app below. It's saved as soon as you click it.",
    Kind.FOLDER: "Choose a folder to finish.",
    Kind.URL: "Type the address and press Enter.",
    Kind.COMMAND: "Type the command and press Enter.",
}
NO_SCANCODE = ("Favorites 1–5 can't send another key or be turned off: the keyboard gives them "
               "no code to remap.")
NO_DESKTOP = "Opening apps and other actions needs KDE Plasma or GNOME."
KIND_ICONS = {Kind.FOLDER: "folder", Kind.URL: "internet-web-browser",
              Kind.COMMAND: "utilities-terminal"}


def _label(text: str = "", *, muted: bool = False, wrap: bool = True, bold: bool = False,
           scale: float = 1.0) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(wrap)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if bold or scale != 1.0:
        font = QFont(label.font())
        font.setBold(bold)
        if scale != 1.0:
            font.setPointSizeF(font.pointSizeF() * scale)
        label.setFont(font)
    if muted:
        label.setProperty("muted", True)
    return label


def normalize_url(text: str) -> str:
    """Add https:// to bare addresses like 'example.com'."""
    text = text.strip()
    if text and not urlparse(text).scheme:
        return "https://" + text
    return text


class EditorPanel(QWidget):
    """Shows one key: what it is, what it does now, and controls to change that."""

    def __init__(self, session: Session, icons: AppIcons, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.icons = icons
        self.key_id: str | None = None
        self._shown: Action | None = None     # the saved action the controls reflect
        self._syncing = False
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        # Either the placeholder or the details are visible (hidden widgets take no space).
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.placeholder = self._placeholder()
        self.details = QWidget()
        outer.addWidget(self.placeholder)
        outer.addWidget(self.details)
        root = QVBoxLayout(self.details)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # Header: name, confirmation badge, technical details.
        head = QHBoxLayout()
        self.title = _label(wrap=True, bold=True, scale=1.35)
        self.badge = QLabel()
        self.badge.setObjectName("badge")
        head.addWidget(self.title, 1)
        head.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(head)
        self.meta = _label(muted=True)
        root.addWidget(self.meta)

        # Keys found with Detect can be renamed or removed.
        self.custom_tools = QWidget()
        tools = QHBoxLayout(self.custom_tools)
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(6)
        self.rename_button = QPushButton(QIcon.fromTheme("edit-rename"), "Rename…")
        self.rename_button.clicked.connect(self._rename_custom)
        self.remove_button = QPushButton(QIcon.fromTheme("edit-delete"), "Remove key")
        self.remove_button.setToolTip("Take this detected key off the keyboard diagram. "
                                      "Detect can find it again.")
        self.remove_button.clicked.connect(self._remove_custom)
        tools.addWidget(self.rename_button)
        tools.addWidget(self.remove_button)
        tools.addStretch()
        root.addWidget(self.custom_tools)
        self.note = Card()
        self.note.set_tone("info")
        note_layout = QVBoxLayout(self.note)
        note_layout.setContentsMargins(10, 8, 10, 8)
        self.note_text = _label()
        note_layout.addWidget(self.note_text)
        root.addWidget(self.note)

        # What the key does now.
        self.current = Card()
        cur = QGridLayout(self.current)
        cur.setContentsMargins(12, 10, 12, 10)
        cur.setHorizontalSpacing(10)
        cur.setVerticalSpacing(2)
        self.effect_icon = QLabel()
        self.effect_icon.setFixedSize(32, 32)
        self.effect = _label(bold=True)
        self.state = _label()
        self.state.setTextFormat(Qt.TextFormat.RichText)
        self.state.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.state.linkActivated.connect(self._revert)
        self.detail = _label(muted=True)
        cur.addWidget(self.effect_icon, 0, 0, 3, 1, Qt.AlignmentFlag.AlignTop)
        cur.addWidget(self.effect, 0, 1)
        cur.addWidget(self.state, 1, 1)
        cur.addWidget(self.detail, 2, 1)
        cur.setColumnStretch(1, 1)
        root.addWidget(self.current)

        # Slider presets.
        self.presets = QWidget()
        pv = QVBoxLayout(self.presets)
        pv.setContentsMargins(0, 4, 0, 0)
        pv.setSpacing(6)
        pv.addWidget(_label("Slider presets", bold=True))
        pgrid = QGridLayout()
        pgrid.setSpacing(6)
        self.preset_group = QButtonGroup(self)
        self.preset_group.setExclusive(True)
        self.preset_buttons: dict[str, QPushButton] = {}
        for i, preset in enumerate(presets.PRESETS):
            button = QPushButton(preset.label)
            button.setCheckable(True)
            button.setToolTip(f"Up: {_lower_first(describe(preset.up, session.key(presets.UP)))}. "
                              f"Down: {_lower_first(describe(preset.down, session.key(presets.DOWN)))}.")
            button.clicked.connect(lambda _c=False, p=preset: self._apply_preset(p))
            self.preset_group.addButton(button)
            self.preset_buttons[preset.id] = button
            pgrid.addWidget(button, i // 2, i % 2)
        pv.addLayout(pgrid)
        self.preset_hint = _label(muted=True)
        pv.addWidget(self.preset_hint)
        root.addWidget(self.presets)

        # Choice of action.
        self.choose_title = _label("What should this key do?", bold=True)
        root.addWidget(self.choose_title)
        self.choices = QWidget()
        grid = QGridLayout(self.choices)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)
        self.kind_group = QButtonGroup(self)
        self.radios: dict[Kind, QRadioButton] = {}
        for col, kinds in enumerate((LEFT_KINDS, RIGHT_KINDS)):
            for row, kind in enumerate(kinds):
                radio = QRadioButton(KIND_LABELS[kind])
                self.kind_group.addButton(radio)
                self.radios[kind] = radio
                radio.toggled.connect(lambda on, k=kind: self._radio_toggled(k, on))
                grid.addWidget(radio, row, col)
        grid.setColumnStretch(2, 1)
        root.addWidget(self.choices)
        self.restriction = _label(muted=True)
        root.addWidget(self.restriction)
        self.hint = _label(muted=True)
        root.addWidget(self.hint)

        # One page of controls per kind.
        self.pages = QStackedWidget()
        self.pages.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.page_for: dict[Kind, QWidget] = {}
        self.default_text = _label(muted=True)
        self._add_page(Kind.DEFAULT, self.default_text)
        self.key_picker = KeyPicker()
        self.key_picker.picked.connect(lambda name: self._commit(Action(Kind.KEY, name)))
        self._add_page(Kind.KEY, self.key_picker)
        self._add_page(Kind.DISABLE, _label("The key will do nothing when pressed.", muted=True))
        self.app_picker = AppPicker()
        self.app_picker.picked.connect(self._app_picked)
        self._add_page(Kind.APP, self.app_picker)
        self._add_page(Kind.FOLDER, self._folder_page())
        self._add_page(Kind.URL, self._url_page())
        self._add_page(Kind.COMMAND, self._command_page())
        root.addWidget(self.pages, 1)

        self.error = _label()
        self.error.setObjectName("error")
        root.addWidget(self.error)

        self._apps_requested = False
        session.changed.connect(self._session_changed)
        self._restyle()
        self.show_key(None)

    # --- construction helpers -----------------------------------------------------------
    def _placeholder(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(8)
        layout.addStretch(2)
        icon = QLabel()
        icon.setPixmap(QIcon.fromTheme("input-keyboard").pixmap(QSize(64, 64)))
        icon.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        title = _label("Choose a key", bold=True, scale=1.35)
        text = _label("Click a key on the keyboard, or use the arrow keys, to see what it does "
                      "and change it.", muted=True)
        for label in (title, text):
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addWidget(text)
        layout.addStretch(3)
        return w

    def _add_page(self, kind: Kind, widget: QWidget) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(widget, 1 if kind in (Kind.KEY, Kind.APP) else 0)
        if kind not in (Kind.KEY, Kind.APP):
            layout.addStretch()
        self.page_for[kind] = page
        self.pages.addWidget(page)

    def _folder_page(self) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        self.folder = QLineEdit(placeholderText="/home/you/Documents")
        self.folder.setAccessibleName("Folder")
        self.folder.editingFinished.connect(self._folder_edited)
        browse = QPushButton(QIcon.fromTheme("document-open-folder"), "Browse…")
        browse.clicked.connect(self._browse_folder)
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        return w

    def _url_page(self) -> QWidget:
        self.url = QLineEdit(placeholderText="https://example.com")
        self.url.setAccessibleName("Web address")
        self.url.editingFinished.connect(self._url_edited)
        return self.url

    def _command_page(self) -> QWidget:
        w = QWidget()
        form = QGridLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        self.command = QLineEdit(placeholderText="e.g. spectacle --region")
        self.command.setAccessibleName("Command")
        self.command_name = QLineEdit(placeholderText="Optional, shown in your desktop's shortcuts")
        self.command_name.setAccessibleName("Name")
        form.addWidget(QLabel("Command:"), 0, 0)
        form.addWidget(self.command, 0, 1)
        form.addWidget(QLabel("Name:"), 1, 0)
        form.addWidget(self.command_name, 1, 1)
        self.command.editingFinished.connect(self._command_edited)
        self.command_name.editingFinished.connect(self._command_edited)
        return w

    # --- showing a key ------------------------------------------------------------------
    @property
    def view(self) -> KeyView | None:
        return self.session.view(self.key_id) if self.key_id else None

    def show_key(self, key_id: str | None) -> None:
        self.key_id = key_id
        self._shown = None
        self.error.hide()
        view = self.view
        self.placeholder.setVisible(view is None)
        self.details.setVisible(view is not None)
        if view is not None:
            self._show_header(view)
            self._refresh(view)

    def _show_header(self, view: KeyView) -> None:
        key = view.key
        self.title.setText(key.label)
        parts = ["Detected key" if key.group == Group.CUSTOM else GROUP_LABELS[key.group]]
        if key.scancode is not None:
            parts.append(f"code {scancode_text(key)}")
        parts.append(f"normally sends {human_name(key.native)} ({key.native})")
        self.meta.setText(" · ".join(parts))
        self.note_text.setText(self._note(key))
        self.note.setVisible(bool(self.note_text.text()))
        self.presets.setVisible(key.group == Group.SLIDER)
        self.custom_tools.setVisible(key.group == Group.CUSTOM)
        self.default_text.setText(f"Sends {human_name(key.native)}, as the keyboard normally does.")

        restricted = not key.hwdb_remappable
        no_desktop = self.session.desktop is None
        for kind, radio in self.radios.items():
            allowed = not ((restricted and kind in (Kind.KEY, Kind.DISABLE))
                           or (no_desktop and kind in RIGHT_KINDS))
            radio.setEnabled(allowed)
        notes = [NO_SCANCODE] if restricted else []
        if no_desktop:
            notes.append(NO_DESKTOP)
        self.restriction.setText(" ".join(notes))
        self.restriction.setVisible(bool(notes))

    def _note(self, key: KeyDef) -> str:
        if key.needs_hid_microsoft:
            fix = ("The favorites fix is on, so this key works after you apply."
                   if self.session.favorites_fix else
                   "Turn on “Make Favorites 1–5 work” at the top, or this key sends nothing.")
            return ("Favorites 1–5 only work with the hid-microsoft driver, which this app sets up "
                    f"once with your admin password. {fix}")
        if key.group == Group.CUSTOM:
            return "You added this key with Detect."
        return key.note

    def _refresh(self, view: KeyView) -> None:
        """Update everything that depends on the saved action and the plan."""
        self._show_status(view)
        if view.key.group == Group.SLIDER:
            self._show_presets()
        if view.action != self._shown:
            self._sync_controls(view)

    def _show_status(self, view: KeyView) -> None:
        verified = view.confirmed
        self.badge.setText("Confirmed" if verified else "Not yet confirmed")
        self.badge.setToolTip("Seen on this keyboard." if verified else UNVERIFIED_TIP)
        self.badge.setProperty("confirmed", verified)
        self._restyle_badge()

        action = view.action
        self.effect.setText(describe(action, view.key))
        icon = self._action_icon(action)
        if icon.isNull():
            icon = QIcon.fromTheme("input-keyboard")
        self.effect_icon.setPixmap(icon.pixmap(QSize(32, 32)))
        self.effect_icon.setVisible(not icon.isNull())
        self.state.setToolTip("")
        if view.error:
            self.current.set_tone("error")
            self.state.setText(f"Won't work. {html.escape(view.error)}")
        elif view.pending:
            self.current.set_tone("pending")
            self.state.setText("Changed. Press Apply to start using it.<br>"
                               "<a href='undo'>Undo change</a>")
            self.state.setToolTip("Undo goes back to: "
                                  + describe(self.session.applied_action(view.id), view.key))
        else:
            self.current.set_tone("neutral")
            self.state.setText("" if action.kind == Kind.DEFAULT else "In use.")
        self.state.setVisible(bool(self.state.text()))
        binding = view.binding
        if binding is not None:
            how = (f"Your desktop sees it as {binding.carrier.keysym}"
                   + (f" (remapped to {binding.carrier.name})." if binding.remapped else "."))
            self.detail.setText(how)
        else:
            self.detail.setText("")
        self.detail.setVisible(bool(self.detail.text()))

    def _action_icon(self, action: Action) -> QIcon:
        if action.kind == Kind.APP:
            return self.icons.icon(action.target)
        if action.kind in KIND_ICONS:
            return QIcon.fromTheme(KIND_ICONS[action.kind])
        return QIcon()

    def _show_presets(self) -> None:
        up, down = self.session.action(presets.UP), self.session.action(presets.DOWN)
        match = presets.matching(up, down)
        self.preset_group.setExclusive(False)
        for pid, button in self.preset_buttons.items():
            button.setChecked(match is not None and match.id == pid)
        self.preset_group.setExclusive(True)
        if match is None:
            key_up, key_down = self.session.key(presets.UP), self.session.key(presets.DOWN)
            self.preset_hint.setText(f"Custom: up {_lower_first(describe(up, key_up))}, "
                                     f"down {_lower_first(describe(down, key_down))}.")
        else:
            self.preset_hint.setText("Presets set both directions at once.")

    def _sync_controls(self, view: KeyView) -> None:
        """Make radios and fields show the saved action."""
        self._syncing = True
        try:
            action = view.action
            self._shown = action
            self.radios[action.kind].setChecked(True)
            self.pages.setCurrentWidget(self.page_for[action.kind])
            self.folder.setText(action.target if action.kind == Kind.FOLDER else "")
            self.url.setText(action.target if action.kind == Kind.URL else "")
            self.command.setText(action.target if action.kind == Kind.COMMAND else "")
            self.command_name.setText(action.label if action.kind == Kind.COMMAND else "")
            self.key_picker.search.clear()
            self.key_picker.set_current(action.target if action.kind == Kind.KEY else None)
            self.app_picker.search.clear()
            self.app_picker.set_current(action.target if action.kind == Kind.APP else None)
            if action.kind == Kind.APP:
                self._load_apps()
            self.hint.hide()
            self.error.hide()
        finally:
            self._syncing = False

    def _session_changed(self) -> None:
        view = self.view
        if view is None and self.key_id is not None:
            self.show_key(None)   # the key is gone (a removed detected key)
        elif view is not None:
            self.title.setText(view.key.label)
            self.note_text.setText(self._note(view.key))
            self._refresh(view)

    # --- editing ------------------------------------------------------------------------
    def _radio_toggled(self, kind: Kind, on: bool) -> None:
        if on and not self._syncing and self.view is not None:
            self._kind_chosen(kind)

    def _kind_chosen(self, kind: Kind) -> None:
        self.pages.setCurrentWidget(self.page_for[kind])
        self.error.hide()
        if kind == Kind.APP:
            self._load_apps()
        if kind in (Kind.DEFAULT, Kind.DISABLE):
            self.hint.hide()
            self._commit(Action(kind))
            return
        view = self.view
        self.hint.setText(NEEDS_TARGET_HINT[kind])
        self.hint.setVisible(view is not None and view.action.kind != kind)
        focus = {Kind.FOLDER: self.folder, Kind.URL: self.url, Kind.COMMAND: self.command,
                 Kind.KEY: self.key_picker.search, Kind.APP: self.app_picker.search}[kind]
        focus.setFocus()

    def _load_apps(self) -> None:
        if not self._apps_requested:
            self._apps_requested = True
            self.session.apps(self._apps_loaded)

    def _apps_loaded(self, apps: list) -> None:
        self.app_picker.set_apps(apps)
        view = self.view
        if view is not None and view.action.kind == Kind.APP:
            self.app_picker.set_current(view.action.target)
            self._show_status(view)

    def _app_picked(self, desktop_id: str) -> None:
        self._commit(Action(Kind.APP, desktop_id, self.app_picker.name_of(desktop_id)))

    def _browse_folder(self) -> None:
        start = self.folder.text() or os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(self, "Choose a folder", start)
        if path:
            self.folder.setText(path)
            self._folder_edited()

    def _folder_edited(self) -> None:
        if self._syncing or self.view is None:
            return
        path = os.path.expanduser(self.folder.text().strip())
        if not path:
            return
        if not os.path.isdir(path):
            self._show_error(f"There's no folder at {short_path(path)}.")
            return
        self._commit(Action(Kind.FOLDER, path, os.path.basename(path.rstrip(os.sep)) or path))

    def _url_edited(self) -> None:
        if self._syncing or self.view is None or not self.url.text().strip():
            return
        url = normalize_url(self.url.text())
        self.url.setText(url)
        self._commit(Action(Kind.URL, url))

    def _command_edited(self) -> None:
        if self._syncing or self.view is None or not self.command.text().strip():
            return
        self._commit(Action(Kind.COMMAND, self.command.text().strip(),
                            self.command_name.text().strip()))

    def _commit(self, action: Action) -> None:
        view = self.view
        if self._syncing or view is None:
            return
        error = action.validate(view.key)
        if error:
            self._show_error(error)
            return
        self.error.hide()
        self.hint.hide()
        if action != view.action:
            self._shown = action          # the controls already show it
            self.session.set_action(view.id, action)

    def _apply_preset(self, preset: presets.SliderPreset) -> None:
        self.session.set_actions(preset.actions())

    def _rename_custom(self) -> None:
        view = self.view
        if view is None or view.key.scancode is None:
            return
        label, ok = QInputDialog.getText(self, "Rename key", "Name for this key:",
                                         text=view.key.label)
        if ok and label.strip() and label.strip() != view.key.label:
            self.session.rename_custom_key(view.key.scancode, label.strip())

    def _remove_custom(self) -> None:
        view = self.view
        if view is None or view.key.scancode is None:
            return
        answer = QMessageBox.question(
            self, "Remove key", f"Remove “{view.key.label}” from this app? What it does is "
            "forgotten too. Press Apply afterwards to update your system.")
        if answer == QMessageBox.StandardButton.Yes:
            self.session.remove_custom_key(view.key.scancode)

    def _revert(self, _link: str = "") -> None:
        if self.key_id:
            self.session.revert(self.key_id)

    def _show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()

    # --- styling ------------------------------------------------------------------------
    def _restyle(self) -> None:
        c = app_colors()
        apply_css(self, f"QLabel[muted=\"true\"] {{ color: {c.muted.name()}; }}"
                        f"QLabel#error {{ color: {c.error.name()}; }}")
        self._restyle_badge()

    def _restyle_badge(self) -> None:
        c = app_colors()
        color = c.ok if self.badge.property("confirmed") else c.muted
        apply_css(self.badge, f"QLabel#badge {{ color: {color.name()}; border: 1px solid "
                              f"{mix(color, c.window, 0.4).name()}; border-radius: 9px; "
                              f"padding: 1px 8px; }}")

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.PaletteChange:
            self._restyle()
        super().changeEvent(event)


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]
