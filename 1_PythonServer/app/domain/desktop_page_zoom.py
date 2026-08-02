from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DesktopPageZoomPreferences:
    zoom_factor: float | None
