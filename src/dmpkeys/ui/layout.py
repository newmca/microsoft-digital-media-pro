"""Geometry of the keyboard diagram, in key units (1.0 = one normal key).

A stylized schematic of the special-key areas, not a to-scale drawing: the zoom
slider on the left edge, launch keys along the top, the silver My Favorites bar
above the F-row (Esc is left out to save room), media keys top right, Log Off and Sleep above the navigation
keys, and the normal typing keys drawn faintly underneath for orientation.
Keys this layout doesn't know (keys found with Detect) go in a strip below.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Sequence

from PySide6.QtCore import QRectF, QSizeF

from ..core.keys import Group, GROUP_LABELS, KeyDef

GAP = 0.12


class Shape(Enum):
    KEY = "key"                  # rounded rectangle
    SLIDER_UP = "slider_up"      # upper half of the zoom slider
    SLIDER_DOWN = "slider_down"  # lower half
    BAR = "bar"                  # a segment of the favorites bar


@dataclass(frozen=True)
class Spot:
    """Where one key is drawn and what is printed on it."""
    key_id: str
    rect: QRectF
    shape: Shape
    title: str = ""
    subtitle: str = ""
    glyph: str | None = None     # a name from glyphs.GLYPHS, drawn instead of / with the title
    group: str = ""              # keys in one group share a label size, so rows look even
    badge_below: bool = False    # title in the upper part, status badge underneath it

    @property
    def two_rows(self) -> bool:
        return bool(self.subtitle) or self.badge_below


@dataclass(frozen=True)
class Deco:
    """Non-interactive drawing: body, slider track, favorites bar, ghost keys, captions."""
    kind: str
    rect: QRectF
    text: str = ""
    fade: float = 1.0            # ghost keys: opacity factor


@dataclass(frozen=True)
class DiagramLayout:
    spots: tuple[Spot, ...]
    decos: tuple[Deco, ...]
    size: QSizeF

    def spot(self, key_id: str) -> Spot | None:
        return next((s for s in self.spots if s.key_id == key_id), None)


# --- fixed geometry -------------------------------------------------------------------
X0 = 2.2                 # left edge of the main key block (right of the slider)
MAIN_W = 13.7            # width of the F-row block (three groups of four keys)
X1 = X0 + MAIN_W + 0.55  # left edge of the right-hand cluster
RIGHT_W = 3.25
BODY_W = X1 + RIGHT_W + 0.45
ROW_A, ROW_A_H = 0.4, 0.92
ROW_B, ROW_B_H = 1.55, 0.96
ROW_F, ROW_F_H = 2.75, 1.0
MEDIA_H = 0.72
GHOST_Y = 4.0
GHOST_H = 0.9
BODY_H = GHOST_Y + 2 * GHOST_H + GAP + 0.45

LAUNCH = ("my_documents", "my_pictures", "my_music", "mail", "web_home", "messenger", "calculator")
LAUNCH_TITLES = {"my_documents": "Documents", "my_pictures": "Pictures", "my_music": "Music",
                 "web_home": "Web/Home"}
MEDIA_TOP = ("mute", "volume_down", "volume_up")          # drawn with the glyph of the same name
MEDIA_BOTTOM = ("previous", "play_pause", "stop", "next")
FAVORITES = ("fav_star", "fav1", "fav2", "fav3", "fav4", "fav5")
F_ROW = ("help", "undo", "redo", "new", "open", "close", "reply", "forward", "send", "spell",
         "save", "print")
SYSTEM = ("log_off", "sleep")

_F_LABEL = re.compile(r"^(.*?)\s*\((F\d+)\)$")


def _row(ids: Sequence[str], x: float, y: float, width: float, height: float,
         gap: float = GAP) -> list[tuple[str, QRectF]]:
    w = (width - gap * (len(ids) - 1)) / len(ids)
    return [(key_id, QRectF(x + i * (w + gap), y, w, height)) for i, key_id in enumerate(ids)]


def _ghost_rows() -> list[Deco]:
    """The number and top letter rows plus the navigation keys, whole, the second one fainter."""
    rows = [
        [1.0] * 13 + [2.0],
        [1.5] + [1.0] * 12 + [1.5],
    ]
    out = []
    for r, widths in enumerate(rows):
        y = GHOST_Y + r * (GHOST_H + GAP)
        fade = (1.0, 0.55)[r]
        scale = (MAIN_W - GAP * (len(widths) - 1)) / sum(widths)
        x = X0
        for w in widths:
            out.append(Deco("ghost", QRectF(x, y, w * scale, GHOST_H), fade=fade))
            x += w * scale + GAP
        for _id, rect in _row("abc", X1, y, RIGHT_W, GHOST_H):
            out.append(Deco("ghost", rect, fade=fade))
    return out


def build(keys: Iterable[KeyDef]) -> DiagramLayout:
    """Place every key. Keys without a fixed position go in a strip under the keyboard."""
    keys = list(keys)
    by_id = {k.id: k for k in keys}
    spots: list[Spot] = []
    decos: list[Deco] = [Deco("body", QRectF(0, 0, BODY_W, BODY_H))]

    def add(key_id: str, rect: QRectF, shape: Shape, group: str, title: str = "",
            subtitle: str = "", glyph: str | None = None, badge_below: bool = False) -> None:
        if key_id in by_id:
            spots.append(Spot(key_id, rect, shape, title, subtitle, glyph, group, badge_below))

    # Zoom slider: one silver control with an upper and a lower half.
    track = QRectF(0.5, ROW_B - 0.05, 1.1, BODY_H - ROW_B - 0.65)
    decos.append(Deco("slider_track", track))
    half = (track.height() - 0.2 - 0.08) / 2
    add("slider_up", QRectF(track.x() + 0.1, track.y() + 0.1, track.width() - 0.2, half),
        Shape.SLIDER_UP, "slider", glyph="zoom_in")
    add("slider_down", QRectF(track.x() + 0.1, track.y() + 0.18 + half, track.width() - 0.2, half),
        Shape.SLIDER_DOWN, "slider", glyph="zoom_out")
    decos.append(Deco("caption", QRectF(track.x() - 0.4, track.bottom() + 0.12,
                                        track.width() + 0.8, 0.4), "Zoom"))

    # Launch keys along the top.
    for key_id, rect in _row(LAUNCH, X0, ROW_A, MAIN_W, ROW_A_H, gap=0.16):
        title = LAUNCH_TITLES.get(key_id) or (by_id[key_id].label if key_id in by_id else "")
        add(key_id, rect, Shape.KEY, "launch", title, badge_below=True)

    # My Favorites bar, centered over the F-row.
    seg_w, seg_gap, pad = 1.12, 0.08, 0.1
    bar_w = pad * 2 + seg_w * len(FAVORITES) + seg_gap * (len(FAVORITES) - 1)
    bar = QRectF(X0 + (MAIN_W - bar_w) / 2, ROW_B, bar_w, ROW_B_H)
    decos.append(Deco("fav_bar", bar))
    decos.append(Deco("caption_right", QRectF(bar.x() - 3.2, bar.y(), 3.0, bar.height()),
                      GROUP_LABELS[Group.FAVORITES]))
    for i, key_id in enumerate(FAVORITES):
        rect = QRectF(bar.x() + pad + i * (seg_w + seg_gap), bar.y() + pad, seg_w,
                      bar.height() - 2 * pad)
        if key_id == "fav_star":
            add(key_id, rect, Shape.BAR, "favorites", glyph="star")
        else:
            add(key_id, rect, Shape.BAR, "favorites", key_id.removeprefix("fav"))

    # Media keys, top right.
    media = _row(MEDIA_TOP, X1, ROW_A + (ROW_A_H - MEDIA_H) / 2, RIGHT_W, MEDIA_H)
    media += _row(MEDIA_BOTTOM, X1, ROW_B + (ROW_B_H - MEDIA_H) / 2, RIGHT_W, MEDIA_H, gap=0.1)
    for key_id, rect in media:
        add(key_id, rect, Shape.KEY, "media", glyph=key_id)

    # F-row with the F Lock labels.
    x = X0
    for block in (F_ROW[0:4], F_ROW[4:8], F_ROW[8:12]):
        for key_id, rect in _row(block, x, ROW_F, 4.3, ROW_F_H, gap=0.1):
            label = by_id[key_id].label if key_id in by_id else key_id
            m = _F_LABEL.match(label)
            add(key_id, rect, Shape.KEY, "flock", m.group(1) if m else label,
                m.group(2) if m else "")
        x += 4.3 + 0.4

    # Log Off and Sleep above the navigation keys.
    for key_id, rect in _row(SYSTEM, X1, ROW_F, RIGHT_W, ROW_F_H, gap=0.15):
        add(key_id, rect, Shape.KEY, "system", by_id[key_id].label if key_id in by_id else key_id,
            glyph="log_off" if key_id == "log_off" else "sleep")

    decos.extend(_ghost_rows())

    # Everything else (keys found with Detect) in a strip below the keyboard.
    placed = {s.key_id for s in spots}
    extra = [k for k in keys if k.id not in placed]
    height = BODY_H
    if extra:
        all_custom = all(k.group == Group.CUSTOM for k in extra)
        top = BODY_H + 0.35
        decos.append(Deco("caption_left", QRectF(0.1, top, 8, 0.45),
                          GROUP_LABELS[Group.CUSTOM] if all_custom else "More keys"))
        w, h, gap = 2.3, 0.8, 0.2
        per_row = max(1, int((BODY_W + gap) // (w + gap)))
        for i, key in enumerate(extra):
            row, col = divmod(i, per_row)
            rect = QRectF(col * (w + gap), top + 0.6 + row * (h + gap), w, h)
            spots.append(Spot(key.id, rect, Shape.KEY, key.label, group="extra"))
        rows = (len(extra) + per_row - 1) // per_row
        height = top + 0.6 + rows * (h + gap) - gap

    return DiagramLayout(tuple(spots), tuple(decos), QSizeF(BODY_W, height))
