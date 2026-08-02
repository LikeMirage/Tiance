from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DesktopWindowSizePreferences:
    width: int
    height: int
    maximized: bool
