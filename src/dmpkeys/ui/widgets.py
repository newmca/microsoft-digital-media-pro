"""Small widgets shared by the main window and the editor."""
from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QFrame, QWidget

from .theme import app_colors, apply_css, mix


class Card(QFrame):
    """A softly tinted panel; colors follow the palette."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.tone = "neutral"
        self._restyle()

    def set_tone(self, tone: str) -> None:
        """neutral | info | pending | error"""
        if tone != self.tone:
            self.tone = tone
            self._restyle()

    def _restyle(self) -> None:
        c = app_colors()
        border = {"neutral": c.key_edge, "info": c.accent, "pending": c.pending,
                  "error": c.error}[self.tone]
        bg = mix(c.window, c.key, 0.6) if self.tone == "neutral" else mix(c.window, border, 0.07)
        apply_css(self, f"QFrame#card {{ background: {bg.name()}; border: 1px solid "
                        f"{mix(border, c.window, 0.45).name()}; border-radius: 6px; }}")

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.PaletteChange:
            self._restyle()
        super().changeEvent(event)
