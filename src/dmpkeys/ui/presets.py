"""One-click setups for both halves of the zoom slider."""
from __future__ import annotations

from dataclasses import dataclass

from ..core.config import Action, Kind

UP, DOWN = "slider_up", "slider_down"


@dataclass(frozen=True)
class SliderPreset:
    id: str
    label: str
    up: Action
    down: Action

    def actions(self) -> dict[str, Action]:
        return {UP: self.up, DOWN: self.down}


def _keys(up: str, down: str) -> tuple[Action, Action]:
    return Action(Kind.KEY, up), Action(Kind.KEY, down)


PRESETS: tuple[SliderPreset, ...] = (
    SliderPreset("zoom", "Zoom", Action(), Action()),
    SliderPreset("brightness", "Brightness", *_keys("brightnessup", "brightnessdown")),
    SliderPreset("volume", "Volume", *_keys("volumeup", "volumedown")),
    SliderPreset("tracks", "Next/previous track", *_keys("nextsong", "previoussong")),
)


def matching(up: Action, down: Action) -> SliderPreset | None:
    """The preset the slider is set to, or None for a custom setup."""
    return next((p for p in PRESETS if p.up == up and p.down == down), None)
