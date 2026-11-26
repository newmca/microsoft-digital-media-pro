"""Colors for custom painting, derived from the current palette so light and dark themes both work."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

# Hues of KDE Breeze's negative/neutral/positive text colors; lightness is adapted per theme.
_ERROR_HUE, _PENDING_HUE, _OK_HUE = 354, 28, 145


def mix(a: QColor, b: QColor, t: float) -> QColor:
    """Linear blend: t=0 gives a, t=1 gives b."""
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * t,
                           a.greenF() + (b.greenF() - a.greenF()) * t,
                           a.blueF() + (b.blueF() - a.blueF()) * t,
                           a.alphaF() + (b.alphaF() - a.alphaF()) * t)


def with_alpha(color: QColor, alpha: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(alpha)
    return c


def is_dark(palette: QPalette) -> bool:
    return palette.color(QPalette.ColorRole.Window).lightnessF() < 0.5


def _semantic(hue: int, dark: bool) -> QColor:
    return QColor.fromHslF(hue / 360, 0.72 if dark else 0.68, 0.64 if dark else 0.46)


@dataclass(frozen=True)
class Colors:
    dark: bool
    window: QColor
    text: QColor
    muted: QColor            # secondary text
    body: QColor             # keyboard body
    body_edge: QColor
    key: QColor              # key cap
    key_hover: QColor
    key_edge: QColor
    key_text: QColor
    silver_top: QColor       # slider and favorites bar
    silver_bottom: QColor
    ghost: QColor            # the normal typing keys, drawn faintly for orientation
    accent: QColor           # palette highlight
    accent_text: QColor
    changed: QColor          # cap tint for keys that do something else
    error: QColor
    pending: QColor
    ok: QColor

    @classmethod
    def from_palette(cls, pal: QPalette) -> "Colors":
        role = QPalette.ColorRole
        dark = is_dark(pal)
        window = pal.color(role.Window)
        text = pal.color(role.WindowText)
        button = pal.color(role.Button)
        accent = pal.color(role.Highlight)
        white, black = QColor(255, 255, 255), QColor(0, 0, 0)
        body = mix(window, black, 0.18) if dark else mix(window, black, 0.06)
        key = mix(button, white, 0.07) if dark else mix(button, white, 0.65)
        silver = mix(button, white, 0.30) if dark else mix(button, black, 0.04)
        return cls(
            dark=dark,
            window=window,
            text=text,
            muted=mix(text, window, 0.42),
            body=body,
            body_edge=mix(body, text, 0.16),
            key=key,
            key_hover=mix(key, accent, 0.14),
            key_edge=mix(key, text, 0.26 if dark else 0.22),
            key_text=pal.color(role.ButtonText),
            silver_top=mix(silver, white, 0.10 if dark else 0.55),
            silver_bottom=mix(silver, black, 0.12),
            ghost=mix(body, text, 0.10),
            accent=accent,
            accent_text=pal.color(role.HighlightedText),
            changed=mix(key, accent, 0.30 if dark else 0.20),
            error=_semantic(_ERROR_HUE, dark),
            pending=_semantic(_PENDING_HUE, dark),
            ok=_semantic(_OK_HUE, dark),
        )


def app_colors() -> Colors:
    """Colors from the application palette. Stylesheet-based widgets use this rather than
    their own palette, which their stylesheet itself changes."""
    return Colors.from_palette(QApplication.palette())


def apply_css(widget: QWidget, css: str) -> None:
    """Set a stylesheet only when it changed; setting one triggers a PaletteChange event,
    so this keeps restyle-on-palette-change handlers from looping."""
    if widget.styleSheet() != css:
        widget.setStyleSheet(css)
