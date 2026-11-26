"""The clickable keyboard diagram and its legend."""
from __future__ import annotations

import html
import math
from dataclasses import dataclass

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QIcon, QKeyEvent, QLinearGradient,
                           QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen)
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from ..core.config import Kind
from . import glyphs, layout as layout_mod
from .icons import AppIcons
from .layout import DiagramLayout, Shape, Spot
from .session import Effect, KeyView
from .text import describe
from .theme import Colors, mix, with_alpha

UNVERIFIED_TIP = "Standard code, not yet confirmed on this keyboard — press Detect to check"
MARGIN = 6.0
MAX_UNIT = 58.0
FLASH_MS = 1400


@dataclass(frozen=True)
class CapState:
    """How a key cap looks; KeyView plus interaction state, or a legend sample."""
    effect: Effect = Effect.DEFAULT
    pending: bool = False
    error: bool = False
    unverified: bool = False
    selected: bool = False
    hovered: bool = False
    focused: bool = False
    flash: float = 0.0           # 0..1, fades after Detect saw the key
    icon: QIcon | None = None    # app icon for keys that launch an app


def cap_path(rect: QRectF, shape: Shape, unit: float) -> QPainterPath:
    path = QPainterPath()
    if shape in (Shape.SLIDER_UP, Shape.SLIDER_DOWN):
        big, small = rect.width() / 2, unit * 0.08
        top, bottom = (big, small) if shape == Shape.SLIDER_UP else (small, big)
        path.moveTo(rect.left(), rect.top() + top)
        path.arcTo(QRectF(rect.left(), rect.top(), 2 * top, 2 * top), 180, -90)
        path.arcTo(QRectF(rect.right() - 2 * top, rect.top(), 2 * top, 2 * top), 90, -90)
        path.arcTo(QRectF(rect.right() - 2 * bottom, rect.bottom() - 2 * bottom, 2 * bottom,
                          2 * bottom), 0, -90)
        path.arcTo(QRectF(rect.left(), rect.bottom() - 2 * bottom, 2 * bottom, 2 * bottom), 270,
                   -90)
        path.closeSubpath()
    else:
        r = min(rect.width(), rect.height()) * (0.2 if shape == Shape.BAR else 0.16)
        path.addRoundedRect(rect, r, r)
    return path


def _font(base: QFont, px: float, bold: bool = False) -> QFont:
    f = QFont(base)
    f.setPixelSize(max(8, round(px)))
    f.setBold(bold)
    return f


def badge_size(rect: QRectF, unit: float) -> float:
    return max(9.0, min(unit * 0.3, rect.height() * 0.4))


def paint_cap(p: QPainter, c: Colors, spot: Spot, rect: QRectF, unit: float, state: CapState,
              base_font: QFont, title_px: float | None = None) -> None:
    """Draw one key cap with its label and status badges.

    ``title_px`` sets the label size, so a row of keys can share one size.
    """
    silver = spot.shape in (Shape.BAR, Shape.SLIDER_UP, Shape.SLIDER_DOWN)
    path = cap_path(rect, spot.shape, unit)
    changed = state.effect in (Effect.KEY, Effect.ACTION)

    # Selection ring and the flash after a detected press sit outside the cap.
    if state.selected or state.flash > 0:
        ring = cap_path(rect.adjusted(-3, -3, 3, 3), spot.shape, unit)
        color = c.accent if state.selected else with_alpha(c.ok, state.flash)
        p.setPen(QPen(color, 2.2 if state.selected else 3.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(ring)
        if state.selected and state.focused:
            halo = cap_path(rect.adjusted(-5.5, -5.5, 5.5, 5.5), spot.shape, unit)
            p.setPen(QPen(with_alpha(c.accent, 0.35), 2.0))
            p.drawPath(halo)

    # Cap: a darker lip underneath, then the face.
    if not silver:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c.key_edge)
        p.drawPath(path.translated(0, max(1.0, unit * 0.05)))
    if silver:
        grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        top, bottom = c.silver_top, c.silver_bottom
        if changed:
            top, bottom = mix(top, c.accent, 0.28), mix(bottom, c.accent, 0.28)
        grad.setColorAt(0, top)
        grad.setColorAt(1, bottom)
        face = grad
    elif changed:
        face = c.changed
    elif state.effect == Effect.DISABLED:
        face = mix(c.key, c.body, 0.55)
    else:
        face = c.key
    p.setBrush(face)
    edge = c.error if state.error else (mix(c.key_edge, c.accent, 0.5) if changed else c.key_edge)
    pen = QPen(edge, 2.0 if state.error else 1.0)
    if state.unverified and not state.error:
        # Not yet confirmed on this keyboard: a dashed outline, subtle on purpose.
        pen = QPen(mix(edge, c.text, 0.25), 1.2)
        pen.setDashPattern([2.5, 2.0])
    p.setPen(pen)
    p.drawPath(path)
    if state.hovered and not state.selected:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(with_alpha(c.accent, 0.16))
        p.drawPath(path)

    text_color = c.muted if state.effect == Effect.DISABLED else c.key_text
    inner = label_inner(rect, unit)
    b = badge_size(rect, unit)
    pad = max(2.0, unit * 0.06)
    has_badge = state.effect != Effect.DEFAULT
    if spot.title and has_badge:
        inner.setRight(inner.right() - badge_room(spot, rect, unit))
    _paint_label(p, c, spot, inner, title_px or label_px(spot, rect, unit, base_font), text_color, silver,
                 base_font)

    # What the key does, bottom right: an app icon or a small symbol.
    def corner(size: float, inset: float) -> QRectF:
        return QRectF(rect.right() - size - inset, rect.bottom() - size - inset, size, size)

    if state.effect == Effect.ACTION and state.icon is not None and not state.icon.isNull():
        state.icon.paint(p, corner(icon_size(rect, unit), pad * 0.6).toRect())
    elif has_badge:
        name = {Effect.KEY: "arrow", Effect.ACTION: "launch", Effect.DISABLED: "disabled"}[state.effect]
        glyphs.draw(p, name, corner(b, pad),
                    c.muted if state.effect == Effect.DISABLED else c.accent)

    # Status, top right: a problem outranks "not applied yet".
    dot = max(3.5, unit * 0.1)
    if state.error:
        r = dot * 1.6
        center = QPointF(rect.right() - r + pad * 0.2, rect.top() + r - pad * 0.2)
        p.setPen(QPen(c.window, 1.5))
        p.setBrush(c.error)
        p.drawEllipse(center, r, r)
        p.setPen(QPen(QColor("white"), max(1.5, r * 0.28), Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.drawLine(center + QPointF(0, -r * 0.48), center + QPointF(0, r * 0.1))
        p.drawPoint(center + QPointF(0, r * 0.48))
    elif state.pending:
        p.setPen(QPen(c.window, 1.5))
        p.setBrush(c.pending)
        p.drawEllipse(QPointF(rect.right() - dot - pad * 0.4, rect.top() + dot + pad * 0.4), dot, dot)


def label_inner(rect: QRectF, unit: float) -> QRectF:
    return rect.adjusted(unit * 0.07, unit * 0.04, -unit * 0.07, -unit * 0.04)


def icon_size(rect: QRectF, unit: float) -> int:
    """App icons are drawn a bit larger than the symbol badges."""
    return round(badge_size(rect, unit) * 1.3)


def badge_room(spot: Spot, rect: QRectF, unit: float) -> float:
    """Width kept free right of a one-row title for the badge or app icon, so they never
    overlap (two-row keys carry the badge in the lower row)."""
    if spot.two_rows:
        return 0.0
    return icon_size(rect, unit) + max(2.0, unit * 0.06)


def label_px(spot: Spot, rect: QRectF, unit: float, base_font: QFont) -> float:
    """Largest label size (8 px at least) that fits the cap, leaving room for a badge."""
    inner = label_inner(rect, unit)
    px = min(unit * 0.3, inner.height() * 0.5)
    if not spot.title:
        return px
    room = inner.width() - badge_room(spot, rect, unit) - (px * 1.6 if spot.glyph else 0)
    while px > 8 and QFontMetricsF(_font(base_font, px, spot.shape == Shape.BAR)).horizontalAdvance(
            spot.title) > room:
        px -= 0.5
    return px


def _paint_label(p: QPainter, c: Colors, spot: Spot, inner: QRectF, px: float,
                 color: QColor, silver: bool, base_font: QFont) -> None:
    if spot.glyph and not spot.title:
        g = min(inner.width(), inner.height()) * (0.62 if silver else 0.7)
        glyphs.draw(p, spot.glyph, QRectF(inner.center().x() - g / 2, inner.center().y() - g / 2,
                                          g, g), color)
        return
    title_rect = QRectF(inner)
    if spot.two_rows:
        title_rect.setBottom(inner.top() + inner.height() * 0.6)
    glyph_w = px * 1.25 if spot.glyph else 0.0
    font = _font(base_font, px, bold=spot.shape == Shape.BAR)
    fm = QFontMetricsF(font)
    text = fm.elidedText(spot.title, Qt.TextElideMode.ElideRight, title_rect.width() - glyph_w)
    if spot.glyph:
        # Symbol and text side by side, centered as a group.
        gap = px * 0.35
        total = glyph_w + gap + fm.horizontalAdvance(text)
        x = title_rect.center().x() - total / 2
        glyphs.draw(p, spot.glyph, QRectF(x, title_rect.center().y() - glyph_w / 2, glyph_w,
                                          glyph_w), color)
        title_rect.setLeft(x + glyph_w + gap)
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    else:
        align = Qt.AlignmentFlag.AlignCenter
    p.setFont(font)
    p.setPen(color)
    p.drawText(title_rect, align, text)
    if spot.subtitle:
        p.setFont(_font(base_font, px * 0.78))
        p.setPen(c.muted)
        sub_rect = QRectF(inner.left(), title_rect.bottom() - inner.height() * 0.04,
                          inner.width(), inner.height() * 0.42)
        p.drawText(sub_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                   spot.subtitle)


def paint_deco(p: QPainter, c: Colors, deco: layout_mod.Deco, rect: QRectF, unit: float,
               base_font: QFont) -> None:
    if deco.kind == "body":
        p.setPen(QPen(c.body_edge, 1.0))
        p.setBrush(c.body)
        p.drawRoundedRect(rect, unit * 0.45, unit * 0.45)
    elif deco.kind == "slider_track":
        p.setPen(QPen(mix(c.body_edge, c.text, 0.1), 1.0))
        p.setBrush(mix(c.body, QColor(0, 0, 0), 0.12 if c.dark else 0.08))
        p.drawRoundedRect(rect, rect.width() / 2, rect.width() / 2)
    elif deco.kind == "fav_bar":
        grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        grad.setColorAt(0, mix(c.silver_bottom, c.body, 0.3))
        grad.setColorAt(1, mix(c.silver_bottom, QColor(0, 0, 0), 0.08))
        p.setPen(QPen(mix(c.body_edge, c.text, 0.1), 1.0))
        p.setBrush(grad)
        p.drawRoundedRect(rect, rect.height() * 0.3, rect.height() * 0.3)
    elif deco.kind == "ghost":
        p.setPen(QPen(with_alpha(mix(c.ghost, c.text, 0.12), 0.6 * deco.fade), 1.0))
        p.setBrush(with_alpha(c.ghost, deco.fade))
        r = min(rect.width(), rect.height()) * 0.16
        p.drawRoundedRect(rect, r, r)
        if deco.text:
            p.setFont(_font(base_font, unit * 0.26))
            p.setPen(with_alpha(c.muted, 0.7 * deco.fade))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, deco.text)
    elif deco.kind.startswith("caption"):
        align = {"caption": Qt.AlignmentFlag.AlignCenter,
                 "caption_right": Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                 "caption_left": Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter}[deco.kind]
        font = _font(base_font, unit * 0.27, bold=deco.kind == "caption_left")
        p.setFont(font)
        p.setPen(c.text if deco.kind == "caption_left" else c.muted)
        p.drawText(rect, align, deco.text)


class KeyboardView(QWidget):
    """Custom-painted diagram. Click or use the arrow keys to select a key."""

    keySelected = Signal(str)

    def __init__(self, icons: AppIcons, parent: QWidget | None = None):
        super().__init__(parent)
        self._icons = icons
        self._layout: DiagramLayout = layout_mod.build([])
        self._views: dict[str, KeyView] = {}
        self._selected: str | None = None
        self._hovered: str | None = None
        self._flashes: dict[str, QElapsedTimer] = {}
        self._flash_timer = QTimer(self, interval=33)
        self._flash_timer.timeout.connect(self._tick_flash)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setAccessibleName("Keyboard diagram")

    # --- data --------------------------------------------------------------------------
    def set_views(self, views: dict[str, KeyView]) -> None:
        if [v.key for v in views.values()] != [v.key for v in self._views.values()]:
            self._layout = layout_mod.build(v.key for v in views.values())
            self.updateGeometry()
        self._views = views
        if self._selected not in views:
            self._selected = None
        self._update_accessible()
        self.update()

    @property
    def selected(self) -> str | None:
        return self._selected

    def select(self, key_id: str | None, *, notify: bool = True) -> None:
        if key_id == self._selected or (key_id is not None and key_id not in self._views):
            return
        self._selected = key_id
        self._update_accessible()
        self.update()
        if notify and key_id is not None:
            self.keySelected.emit(key_id)

    def flash(self, key_id: str) -> None:
        """Briefly highlight a key (Detect saw it pressed)."""
        timer = QElapsedTimer()
        timer.start()
        self._flashes[key_id] = timer
        self._flash_timer.start()
        self.update()

    def spot_rect(self, key_id: str) -> QRectF | None:
        """Pixel rectangle of a key; used by tests and tooltips."""
        spot = self._layout.spot(key_id)
        return self._to_px(spot.rect) if spot else None

    # --- geometry ----------------------------------------------------------------------
    def _unit(self) -> float:
        size = self._layout.size
        avail_w = self.width() - 2 * MARGIN
        avail_h = self.height() - 2 * MARGIN
        return max(4.0, min(avail_w / size.width(), avail_h / size.height(), MAX_UNIT))

    def _origin(self) -> QPointF:
        unit = self._unit()
        w = self._layout.size.width() * unit
        return QPointF((self.width() - w) / 2, MARGIN)

    def _to_px(self, r: QRectF) -> QRectF:
        u, o = self._unit(), self._origin()
        return QRectF(o.x() + r.x() * u, o.y() + r.y() * u, r.width() * u, r.height() * u)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        size = self._layout.size
        unit = min((width - 2 * MARGIN) / size.width(), MAX_UNIT)
        return math.ceil(size.height() * unit + 2 * MARGIN + 4)

    def sizeHint(self) -> QSize:
        return QSize(760, self.heightForWidth(760))

    def minimumSizeHint(self) -> QSize:
        return QSize(520, self.heightForWidth(520))

    def _spot_at(self, pos: QPointF) -> Spot | None:
        for spot in self._layout.spots:
            rect = self._to_px(spot.rect)
            if cap_path(rect, spot.shape, self._unit()).contains(pos):
                return spot
        return None

    # --- painting ----------------------------------------------------------------------
    def paintEvent(self, _event: QPaintEvent) -> None:
        c = Colors.from_palette(self.palette())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        unit = self._unit()
        font = self.font()
        for deco in self._layout.decos:
            paint_deco(p, c, deco, self._to_px(deco.rect), unit, font)
        # Keys of one group share a label size, so rows look even.
        sizes: dict[str, float] = {}
        for spot in self._layout.spots:
            px = label_px(spot, self._to_px(spot.rect), unit, font)
            sizes[spot.group] = min(px, sizes.get(spot.group, px))
        # Paint the selected key last so its ring isn't covered by neighbours.
        spots = sorted(self._layout.spots, key=lambda s: s.key_id == self._selected)
        for spot in spots:
            view = self._views.get(spot.key_id)
            if view is not None:
                paint_cap(p, c, spot, self._to_px(spot.rect), unit, self._cap_state(view), font,
                          sizes[spot.group])
        p.end()

    def _cap_state(self, view: KeyView) -> CapState:
        flash = 0.0
        if view.id in self._flashes:
            flash = max(0.0, 1.0 - self._flashes[view.id].elapsed() / FLASH_MS)
        icon = self._icons.icon(view.action.target) if view.action.kind == Kind.APP else None
        return CapState(effect=view.effect, pending=view.pending, error=view.error is not None,
                        unverified=not view.confirmed, selected=view.id == self._selected,
                        hovered=view.id == self._hovered, focused=self.hasFocus(), flash=flash,
                        icon=icon)

    def _tick_flash(self) -> None:
        self._flashes = {k: t for k, t in self._flashes.items() if t.elapsed() < FLASH_MS}
        if not self._flashes:
            self._flash_timer.stop()
        self.update()

    # --- interaction -------------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            spot = self._spot_at(event.position())
            if spot is not None:
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                self.select(spot.key_id)
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        spot = self._spot_at(event.position())
        key_id = spot.key_id if spot else None
        if key_id != self._hovered:
            self._hovered = key_id
            self.setCursor(Qt.CursorShape.PointingHandCursor if key_id
                           else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, event) -> None:
        self._hovered = None
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:
        if self._selected is None and self._layout.spots:
            self.select(self._layout.spots[0].key_id)
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self.update()
        super().focusOutEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        directions = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
                      Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        key = Qt.Key(event.key())
        spots = self._layout.spots
        if key in directions:
            target = self._neighbour(*directions[key])
            if target is not None:
                self.select(target)
            return
        if key == Qt.Key.Key_Home and spots:
            self.select(spots[0].key_id)
            return
        if key == Qt.Key.Key_End and spots:
            self.select(spots[-1].key_id)
            return
        super().keyPressEvent(event)

    def _neighbour(self, dx: int, dy: int) -> str | None:
        """The nearest key in a direction, preferring keys roughly in line."""
        current = self._layout.spot(self._selected) if self._selected else None
        if current is None:
            return self._layout.spots[0].key_id if self._layout.spots else None
        here = current.rect.center()
        best, best_score = None, math.inf
        for spot in self._layout.spots:
            if spot.key_id == current.key_id:
                continue
            d = spot.rect.center() - here
            along = d.x() * dx + d.y() * dy
            if along <= 0.05:
                continue
            across = abs(d.x() * dy) + abs(d.y() * dx)
            score = along + across * 2.5
            if score < best_score:
                best, best_score = spot.key_id, score
        return best

    def event(self, event) -> bool:
        if event.type() == event.Type.ToolTip:
            spot = self._spot_at(QPointF(event.pos()))
            view = self._views.get(spot.key_id) if spot is not None else None
            if spot is not None and view is not None:
                QToolTip.showText(event.globalPos(), tooltip(view), self,
                                  self._to_px(spot.rect).toRect())
            else:
                QToolTip.hideText()
                event.ignore()
            return True
        return super().event(event)

    def _update_accessible(self) -> None:
        view = self._views.get(self._selected) if self._selected else None
        self.setAccessibleDescription(
            f"Selected: {view.key.label}. {describe(view.action, view.key)}" if view
            else "No key selected. Use the arrow keys to choose one.")


def tooltip(view: KeyView) -> str:
    lines = [f"<b>{html.escape(view.key.label)}</b>",
             html.escape(describe(view.action, view.key))]
    if view.error:
        lines.append(f"Problem: {html.escape(view.error)}")
    elif view.pending:
        lines.append("Changed — not applied yet")
    if not view.confirmed:
        lines.append(f"<i>{UNVERIFIED_TIP}</i>")
    return "<br>".join(lines)


class Legend(QWidget):
    """Sample caps explaining the diagram's colors and badges."""

    ITEMS = (
        ("Default", CapState()),
        ("Sends another key", CapState(effect=Effect.KEY)),
        ("Launches something", CapState(effect=Effect.ACTION)),
        ("Does nothing", CapState(effect=Effect.DISABLED)),
        ("Not applied yet", CapState(pending=True)),
        ("Problem", CapState(error=True)),
        ("Not yet confirmed", CapState(unverified=True)),
    )

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._rows = 1

    def _metrics(self) -> tuple[float, float, list[float]]:
        fm = QFontMetricsF(self.font())
        cap = fm.height() * 1.55
        widths = [cap + 6 + fm.horizontalAdvance(text) + 18 for text, _ in self.ITEMS]
        return cap, fm.height(), widths

    def _positions(self, width: float) -> list[QPointF]:
        cap, _h, widths = self._metrics()
        out, x, y = [], 0.0, 0.0
        for w in widths:
            if x > 0 and x + w > width:
                x, y = 0.0, y + cap + 8
            out.append(QPointF(x, y))
            x += w
        return out

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        cap, _h, _w = self._metrics()
        return math.ceil(self._positions(width)[-1].y() + cap + 4)

    def sizeHint(self) -> QSize:
        return QSize(600, self.heightForWidth(600))

    def resizeEvent(self, event) -> None:
        self.setFixedHeight(self.heightForWidth(self.width()))
        super().resizeEvent(event)

    def paintEvent(self, _event: QPaintEvent) -> None:
        c = Colors.from_palette(self.palette())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cap, text_h, _w = self._metrics()
        unit = cap * 1.25
        for (text, state), pos in zip(self.ITEMS, self._positions(self.width())):
            rect = QRectF(pos.x() + 1, pos.y() + 1, cap, cap - 2)
            paint_cap(p, c, Spot("", rect, Shape.KEY), rect, unit, state, self.font())
            p.setFont(self.font())
            p.setPen(c.muted)
            p.drawText(QRectF(rect.right() + 6, pos.y(), 400, cap),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        p.end()
