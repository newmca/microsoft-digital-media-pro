"""Small vector symbols for key caps and status badges, drawn in any color at any size.

Painted with QPainterPath rather than icon-theme icons or emoji so the diagram
looks the same on every system and follows the palette.
"""
from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF


def _square(rect: QRectF) -> QRectF:
    s = min(rect.width(), rect.height())
    return QRectF(rect.center().x() - s / 2, rect.center().y() - s / 2, s, s)


def _pen(p: QPainter, color: QColor, width: float) -> None:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _fill(p: QPainter, color: QColor) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)


def _pt(r: QRectF, fx: float, fy: float) -> QPointF:
    """A point at fractions of the glyph square."""
    return QPointF(r.x() + r.width() * fx, r.y() + r.height() * fy)


def _poly(r: QRectF, *pts: tuple[float, float]) -> QPolygonF:
    return QPolygonF([_pt(r, x, y) for x, y in pts])


def _magnifier(p: QPainter, r: QRectF, c: QColor, plus: bool) -> None:
    w = r.width() * 0.1
    _pen(p, c, w)
    lens = QRectF(_pt(r, 0.12, 0.12), _pt(r, 0.68, 0.68))
    p.drawEllipse(lens)
    p.drawLine(_pt(r, 0.64, 0.64), _pt(r, 0.88, 0.88))
    cx, cy = lens.center().x(), lens.center().y()
    arm = lens.width() * 0.24
    p.drawLine(QPointF(cx - arm, cy), QPointF(cx + arm, cy))
    if plus:
        p.drawLine(QPointF(cx, cy - arm), QPointF(cx, cy + arm))


def _speaker(p: QPainter, r: QRectF, c: QColor) -> None:
    _fill(p, c)
    p.drawPolygon(_poly(r, (0.1, 0.38), (0.28, 0.38), (0.5, 0.18), (0.5, 0.82), (0.28, 0.62),
                        (0.1, 0.62)))


def _mute(p: QPainter, r: QRectF, c: QColor) -> None:
    _speaker(p, r, c)
    _pen(p, c, r.width() * 0.09)
    p.drawLine(_pt(r, 0.62, 0.36), _pt(r, 0.9, 0.64))
    p.drawLine(_pt(r, 0.62, 0.64), _pt(r, 0.9, 0.36))


def _volume(p: QPainter, r: QRectF, c: QColor, up: bool) -> None:
    _speaker(p, r, c)
    _pen(p, c, r.width() * 0.09)
    p.drawLine(_pt(r, 0.62, 0.5), _pt(r, 0.92, 0.5))
    if up:
        p.drawLine(_pt(r, 0.77, 0.35), _pt(r, 0.77, 0.65))


def _play_pause(p: QPainter, r: QRectF, c: QColor) -> None:
    _fill(p, c)
    p.drawPolygon(_poly(r, (0.1, 0.24), (0.5, 0.5), (0.1, 0.76)))
    p.drawRect(QRectF(_pt(r, 0.6, 0.26), _pt(r, 0.7, 0.74)))
    p.drawRect(QRectF(_pt(r, 0.8, 0.26), _pt(r, 0.9, 0.74)))


def _stop(p: QPainter, r: QRectF, c: QColor) -> None:
    _fill(p, c)
    p.drawRoundedRect(QRectF(_pt(r, 0.26, 0.26), _pt(r, 0.74, 0.74)), r.width() * 0.04,
                      r.width() * 0.04)


def _skip(p: QPainter, r: QRectF, c: QColor, forward: bool) -> None:
    _fill(p, c)
    if forward:
        p.drawPolygon(_poly(r, (0.12, 0.26), (0.46, 0.5), (0.12, 0.74)))
        p.drawPolygon(_poly(r, (0.44, 0.26), (0.78, 0.5), (0.44, 0.74)))
        p.drawRect(QRectF(_pt(r, 0.78, 0.26), _pt(r, 0.88, 0.74)))
    else:
        p.drawPolygon(_poly(r, (0.88, 0.26), (0.54, 0.5), (0.88, 0.74)))
        p.drawPolygon(_poly(r, (0.56, 0.26), (0.22, 0.5), (0.56, 0.74)))
        p.drawRect(QRectF(_pt(r, 0.12, 0.26), _pt(r, 0.22, 0.74)))


def _star(p: QPainter, r: QRectF, c: QColor) -> None:
    _fill(p, c)
    cx, cy = r.center().x(), r.center().y() + r.height() * 0.04
    outer, inner = r.width() * 0.44, r.width() * 0.18
    pts = []
    for i in range(10):
        radius = outer if i % 2 == 0 else inner
        a = -math.pi / 2 + i * math.pi / 5
        pts.append(QPointF(cx + radius * math.cos(a), cy + radius * math.sin(a)))
    p.drawPolygon(QPolygonF(pts))


def _log_off(p: QPainter, r: QRectF, c: QColor) -> None:
    _pen(p, c, r.width() * 0.09)
    door = QPainterPath(_pt(r, 0.5, 0.2))
    door.lineTo(_pt(r, 0.18, 0.2))
    door.lineTo(_pt(r, 0.18, 0.8))
    door.lineTo(_pt(r, 0.5, 0.8))
    p.drawPath(door)
    p.drawLine(_pt(r, 0.4, 0.5), _pt(r, 0.86, 0.5))
    p.drawPolyline(_poly(r, (0.7, 0.34), (0.86, 0.5), (0.7, 0.66)))


def _sleep(p: QPainter, r: QRectF, c: QColor) -> None:
    _fill(p, c)
    moon = QPainterPath()
    moon.addEllipse(QRectF(_pt(r, 0.16, 0.16), _pt(r, 0.84, 0.84)))
    bite = QPainterPath()
    bite.addEllipse(QRectF(_pt(r, 0.36, 0.04), _pt(r, 0.96, 0.64)))
    p.drawPath(moon.subtracted(bite))


# --- badges -----------------------------------------------------------------------------
def _arrow(p: QPainter, r: QRectF, c: QColor) -> None:
    _pen(p, c, r.width() * 0.13)
    p.drawLine(_pt(r, 0.18, 0.5), _pt(r, 0.8, 0.5))
    p.drawPolyline(_poly(r, (0.56, 0.26), (0.8, 0.5), (0.56, 0.74)))


def _launch(p: QPainter, r: QRectF, c: QColor) -> None:
    _pen(p, c, r.width() * 0.12)
    p.drawLine(_pt(r, 0.3, 0.7), _pt(r, 0.76, 0.24))
    p.drawPolyline(_poly(r, (0.4, 0.24), (0.76, 0.24), (0.76, 0.6)))


def _disabled(p: QPainter, r: QRectF, c: QColor) -> None:
    _pen(p, c, r.width() * 0.12)
    p.drawEllipse(QRectF(_pt(r, 0.16, 0.16), _pt(r, 0.84, 0.84)))
    p.drawLine(_pt(r, 0.28, 0.72), _pt(r, 0.72, 0.28))


def _check(p: QPainter, r: QRectF, c: QColor) -> None:
    _pen(p, c, r.width() * 0.14)
    p.drawPolyline(_poly(r, (0.2, 0.52), (0.42, 0.74), (0.8, 0.3)))


Glyph = Callable[[QPainter, QRectF, QColor], None]

GLYPHS: dict[str, Glyph] = {
    "zoom_in": lambda p, r, c: _magnifier(p, r, c, True),
    "zoom_out": lambda p, r, c: _magnifier(p, r, c, False),
    "star": _star,
    "mute": _mute,
    "volume_down": lambda p, r, c: _volume(p, r, c, False),
    "volume_up": lambda p, r, c: _volume(p, r, c, True),
    "previous": lambda p, r, c: _skip(p, r, c, False),
    "next": lambda p, r, c: _skip(p, r, c, True),
    "play_pause": _play_pause,
    "stop": _stop,
    "log_off": _log_off,
    "sleep": _sleep,
    "arrow": _arrow,
    "launch": _launch,
    "disabled": _disabled,
    "check": _check,
}


def draw(p: QPainter, name: str, rect: QRectF, color: QColor) -> None:
    """Draw glyph ``name`` centered in ``rect``, scaled to its shorter side."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    GLYPHS[name](p, _square(rect), color)
    p.restore()
