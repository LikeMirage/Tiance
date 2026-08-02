from pydantic import BaseModel

from app.domain.desktop_window import DesktopWindowSizePreferences


class DesktopWindowSizePreferencesResponse(BaseModel):
    version: int = 1
    width: int
    height: int
    maximized: bool

    @classmethod
    def from_domain(
        cls,
        preferences: DesktopWindowSizePreferences,
    ) -> "DesktopWindowSizePreferencesResponse":
        return cls(
            width=preferences.width,
            height=preferences.height,
            maximized=preferences.maximized,
        )


class DesktopWindowSizePreferencesSaveRequest(BaseModel):
    width: int | None = None
    height: int | None = None
    maximized: bool | None = None
