from pydantic import BaseModel

from app.domain.desktop_page_zoom import DesktopPageZoomPreferences


class DesktopPageZoomPreferencesResponse(BaseModel):
    version: int = 1
    zoom_factor: float | None

    @classmethod
    def from_domain(
        cls,
        preferences: DesktopPageZoomPreferences,
    ) -> "DesktopPageZoomPreferencesResponse":
        return cls(zoom_factor=preferences.zoom_factor)


class DesktopPageZoomPreferencesSaveRequest(BaseModel):
    zoom_factor: float
