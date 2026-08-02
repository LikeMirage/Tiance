from datetime import UTC, datetime
from functools import lru_cache
from json import dumps, loads
from math import isfinite
from typing import Any

from app.domain.desktop_page_zoom import DesktopPageZoomPreferences
from app.repositories.project import ProjectRepository, get_project_repository

DESKTOP_PAGE_ZOOM_PREFERENCES_KEY = "desktop.page_zoom_preferences"
DEFAULT_PAGE_ZOOM_FACTOR = 1.0
MIN_PAGE_ZOOM_FACTOR = 0.6
MAX_PAGE_ZOOM_FACTOR = 1.25


class DesktopPageZoomPreferencesService:
    def __init__(self, project_repository: ProjectRepository) -> None:
        self._project_repository = project_repository

    def get_preferences(self) -> DesktopPageZoomPreferences:
        raw = self._project_repository.get_metadata_value(DESKTOP_PAGE_ZOOM_PREFERENCES_KEY)
        if not raw:
            return DesktopPageZoomPreferences(zoom_factor=None)

        payload = _parse_json_object(raw)
        if payload is None:
            return DesktopPageZoomPreferences(zoom_factor=None)

        return DesktopPageZoomPreferences(
            zoom_factor=_normalize_page_zoom_factor(payload.get("zoom_factor")),
        )

    def save_preferences(self, *, zoom_factor: float) -> DesktopPageZoomPreferences:
        preferences = DesktopPageZoomPreferences(
            zoom_factor=_normalize_page_zoom_factor(zoom_factor) or DEFAULT_PAGE_ZOOM_FACTOR,
        )
        self._project_repository.set_metadata_value(
            key=DESKTOP_PAGE_ZOOM_PREFERENCES_KEY,
            value=dumps(_preferences_payload(preferences), ensure_ascii=False),
            updated_at=datetime.now(UTC).isoformat(),
        )
        return preferences


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    try:
        payload = loads(raw)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _preferences_payload(preferences: DesktopPageZoomPreferences) -> dict[str, float | int | None]:
    return {
        "version": 1,
        "zoom_factor": preferences.zoom_factor,
    }


def _normalize_page_zoom_factor(value: Any) -> float | None:
    if isinstance(value, bool):
        return None

    try:
        candidate = float(value)
    except (TypeError, ValueError):
        return None

    if not isfinite(candidate):
        return None

    clamped = max(MIN_PAGE_ZOOM_FACTOR, min(MAX_PAGE_ZOOM_FACTOR, candidate))
    return round(clamped, 2)


@lru_cache
def get_desktop_page_zoom_preferences_service() -> DesktopPageZoomPreferencesService:
    return DesktopPageZoomPreferencesService(get_project_repository())
