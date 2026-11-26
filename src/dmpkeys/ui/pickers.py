"""Searchable lists for choosing a key to send or an app to launch."""
from __future__ import annotations

from typing import Callable, TypeAlias

from PySide6.QtCore import (QModelIndex, QPersistentModelIndex, QSize, QSortFilterProxyModel, Qt,
                            Signal)
from PySide6.QtGui import QPainter, QPalette, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLineEdit, QListView, QStyle,
                               QStyledItemDelegate, QStyleOptionViewItem, QVBoxLayout, QWidget)

from ..core import keycodes
from ..core.apps import App
from . import keynames
from .icons import icon_from_name
from .theme import mix

VALUE_ROLE = Qt.ItemDataRole.UserRole + 1        # what gets picked (kernel name / desktop id)
SECONDARY_ROLE = Qt.ItemDataRole.UserRole + 2    # right-aligned muted text
SEARCH_ROLE = Qt.ItemDataRole.UserRole + 3       # extra text the search matches

Index: TypeAlias = "QModelIndex | QPersistentModelIndex"


class SecondaryTextDelegate(QStyledItemDelegate):
    """Draws SECONDARY_ROLE right-aligned in a muted color after the item's text."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: Index) -> None:
        secondary = index.data(SECONDARY_ROLE) or ""
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        fm = opt.fontMetrics
        sec_w = fm.horizontalAdvance(secondary) + 12 if secondary else 0
        text_rect = opt.rect.adjusted(0, 0, -sec_w, 0)
        style = opt.widget.style() if opt.widget else QStyle()
        avail = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget)
        opt.text = fm.elidedText(opt.text, Qt.TextElideMode.ElideRight,
                                 max(0, min(avail.width(), text_rect.right() - avail.left())))
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        if secondary:
            selected = bool(opt.state & QStyle.StateFlag.State_Selected)
            pal = opt.palette
            color = (pal.color(QPalette.ColorRole.HighlightedText) if selected
                     else mix(pal.color(QPalette.ColorRole.Text), pal.color(QPalette.ColorRole.Base),
                              0.45))
            painter.save()
            painter.setPen(color)
            painter.drawText(opt.rect.adjusted(0, 0, -8, 0),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, secondary)
            painter.restore()


class _Filter(QSortFilterProxyModel):
    """Matches the search text against the display and search roles; optional allow-list."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._text = ""
        self._allowed: frozenset[str] | None = None

    def set_text(self, text: str) -> None:
        self._change(lambda: setattr(self, "_text", text.strip().casefold()))

    def set_allowed(self, values: frozenset[str] | None) -> None:
        self._change(lambda: setattr(self, "_allowed", values))

    def _change(self, apply: Callable[[], None]) -> None:
        if hasattr(self, "beginFilterChange"):   # Qt 6.10+
            self.beginFilterChange()
            apply()
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            apply()
            self.invalidateRowsFilter()

    def filterAcceptsRow(self, row: int, parent: Index) -> bool:
        index = self.sourceModel().index(row, 0, parent)
        if self._allowed is not None and index.data(VALUE_ROLE) not in self._allowed:
            return False
        if not self._text:
            return True
        haystack = f"{index.data(Qt.ItemDataRole.DisplayRole)} {index.data(SEARCH_ROLE) or ''}"
        return all(word in haystack.casefold() for word in self._text.split())


class SearchList(QWidget):
    """A search field over a filtered list. Clicking or pressing Enter on a row picks it."""

    picked = Signal(str)

    def __init__(self, placeholder: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.search = QLineEdit(placeholderText=placeholder, clearButtonEnabled=True)
        self.model = QStandardItemModel(self)
        self.proxy = _Filter(self)
        self.proxy.setSourceModel(self.model)
        self.view = QListView(uniformItemSizes=True)
        self.view.setModel(self.proxy)
        self.view.setItemDelegate(SecondaryTextDelegate(self.view))
        self.view.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.view.setMinimumHeight(180)
        self.view.clicked.connect(self._pick)
        self.view.activated.connect(self._pick)
        self.search.textChanged.connect(self._search_changed)
        self.search.returnPressed.connect(self._pick_first)

        self.top = QHBoxLayout()
        self.top.setContentsMargins(0, 0, 0, 0)
        self.top.addWidget(self.search, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.top)
        layout.addWidget(self.view, 1)

    def _search_changed(self, text: str) -> None:
        self.proxy.set_text(text)

    def _pick(self, index: QModelIndex) -> None:
        value = index.data(VALUE_ROLE)
        if value:
            self.picked.emit(value)

    def _pick_first(self) -> None:
        if self.proxy.rowCount() == 1:
            self._pick(self.proxy.index(0, 0))
        elif self.proxy.rowCount():
            self.view.setFocus()
            self.view.setCurrentIndex(self.proxy.index(0, 0))

    def set_current(self, value: str | None) -> None:
        """Highlight the row for ``value`` (without emitting picked)."""
        for row in range(self.proxy.rowCount()):
            index = self.proxy.index(row, 0)
            if index.data(VALUE_ROLE) == value:
                self.view.setCurrentIndex(index)
                self.view.scrollTo(index, QListView.ScrollHint.PositionAtCenter)
                return
        self.view.clearSelection()

    def visible_values(self) -> list[str]:
        return [self.proxy.index(r, 0).data(VALUE_ROLE) for r in range(self.proxy.rowCount())]


class KeyPicker(SearchList):
    """Kernel keys by friendly name, grouped into categories, with an "All keys" search."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Search keys", parent)
        self.category = QComboBox()
        self.category.setAccessibleName("Key category")
        cats = keynames.categories()
        for name in cats:
            self.category.addItem(name)
        self.top.addWidget(self.category)
        self.category.currentTextChanged.connect(self._category_changed)
        for kk in keycodes.all_keys():
            if kk.name == "reserved":
                continue
            item = QStandardItem(keynames.human_name(kk.name))
            item.setData(kk.name, VALUE_ROLE)
            item.setData(kk.name, SECONDARY_ROLE)
            item.setData(kk.name.replace("_", " "), SEARCH_ROLE)
            tip = f"KEY_{kk.name.upper()} (code {kk.code})"
            if kk.keysym is None:
                tip += "\nMost apps and the desktop can't see this key."
            item.setToolTip(tip)
            self.model.appendRow(item)
        self.model.sort(0)
        self._category_changed(self.category.currentText())

    def _category_changed(self, name: str) -> None:
        cats = keynames.categories()
        self.proxy.set_allowed(None if name == keynames.ALL_KEYS else frozenset(cats.get(name, ())))

    def _search_changed(self, text: str) -> None:
        # Searching looks through every key; the category narrows browsing only.
        if text.strip() and self.category.currentText() != keynames.ALL_KEYS:
            self.category.setCurrentText(keynames.ALL_KEYS)
        super()._search_changed(text)

    def set_current(self, value: str | None) -> None:
        if value:
            cat = keynames.category_of(value) or keynames.ALL_KEYS
            if self.category.currentText() not in (cat, keynames.ALL_KEYS):
                self.category.setCurrentText(cat)
        super().set_current(value)


class AppPicker(SearchList):
    """Installed applications with their icons."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Search apps", parent)
        self.view.setIconSize(QSize(24, 24))
        self._names: dict[str, str] = {}
        self._loading = QStandardItem("Loading apps…")
        self._loading.setEnabled(False)
        self.model.appendRow(self._loading)

    def name_of(self, desktop_id: str) -> str:
        return self._names.get(desktop_id, "")

    def set_apps(self, apps: list[App]) -> None:
        self._names = {app.desktop_id: app.name for app in apps}
        self.model.clear()
        if not apps:
            empty = QStandardItem("No apps found")
            empty.setEnabled(False)
            self.model.appendRow(empty)
        for app in apps:
            item = QStandardItem(icon_from_name(app.icon), app.name)
            item.setData(app.desktop_id, VALUE_ROLE)
            item.setData(app.desktop_id, SEARCH_ROLE)
            item.setToolTip(app.desktop_id)
            self.model.appendRow(item)
