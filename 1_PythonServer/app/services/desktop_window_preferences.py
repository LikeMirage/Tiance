from datetime import UTC, datetime
from functools import lru_cache
from json import dumps, loads
from typing import Any

from app.domain.desktop_window import DesktopWindowSizePreferences
from app.repositories.project import ProjectRepository, get_project_repository

DESKTOP_WINDOW_SIZE_PREFERENCES_KEY = "desktop.window_size_preferences"
DEFAULT_WINDOW_WIDTH = 1440
DEFAULT_WINDOW_HEIGHT = 900
DEFAULT_WINDOW_MAXIMIZED = False
MIN_WINDOW_WIDTH = 1080
MIN_WINDOW_HEIGHT = 720
MAX_WINDOW_WIDTH = 7680
MAX_WINDOW_HEIGHT = 4320


class DesktopWindowPreferencesService:
    def __init__(self, project_repository: ProjectRepository) -> None:
        self._project_repository = project_repository

    def get_size_preferences(self) -> DesktopWindowSizePreferences:
        raw = self._project_repository.get_metadata_value(DESKTOP_WINDOW_SIZE_PREFERENCES_KEY)
        if not raw:
            return _default_size_preferences()

        payload = _parse_json_object(raw)
        if payload is None:
            return _default_size_preferences()

        return _size_preferences_from_payload(payload)

    def save_size_preferences(
        self,
        *,
        width: int | None = None,
        height: int | None = None,
        maximized: bool | None = None,
    ) -> DesktopWindowSizePreferences:
        current = self.get_size_preferences()
        preferences = DesktopWindowSizePreferences(
            width=_clamp_int(width, current.width, MIN_WINDOW_WIDTH, MAX_WINDOW_WIDTH),
            height=_clamp_int(height, current.height, MIN_WINDOW_HEIGHT, MAX_WINDOW_HEIGHT),
            maximized=maximized if isinstance(maximized, bool) else current.maximized,
        )
        self._project_repository.set_metadata_value(
            key=DESKTOP_WINDOW_SIZE_PREFERENCES_KEY,
            value=dumps(_size_preferences_payload(preferences), ensure_ascii=False),
            updated_at=datetime.now(UTC).isoformat(),
        )
        return preferences


def _default_size_preferences() -> DesktopWindowSizePreferences:
    return DesktopWindowSizePreferences(
        width=DEFAULT_WINDOW_WIDTH,
        height=DEFAULT_WINDOW_HEIGHT,
        maximized=DEFAULT_WINDOW_MAXIMIZED,
    )


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    try:
        payload = loads(raw)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _size_preferences_from_payload(payload: dict[str, Any]) -> DesktopWindowSizePreferences:
    return DesktopWindowSizePreferences(
        width=_clamp_int(
            payload.get("width"),
            DEFAULT_WINDOW_WIDTH,
            MIN_WINDOW_WIDTH,
            MAX_WINDOW_WIDTH,
        ),
        height=_clamp_int(
            payload.get("height"),
            DEFAULT_WINDOW_HEIGHT,
            MIN_WINDOW_HEIGHT,
            MAX_WINDOW_HEIGHT,
        ),
        maximized=payload.get("maximized")
        if isinstance(payload.get("maximized"), bool)
        else DEFAULT_WINDOW_MAXIMIZED,
    )


def _size_preferences_payload(preferences: DesktopWindowSizePreferences) -> dict[str, int | bool]:
    return {
        "version": 1,
        "width": preferences.width,
        "height": preferences.height,
        "maximized": preferences.maximized,
    }


def _clamp_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    if isinstance(value, bool):
        candidate = default
    elif isinstance(value, int):
        candidate = value
    elif isinstance(value, float) and value.is_integer():
        candidate = int(value)
    else:
        candidate = default
    return min(max(candidate, min_value), max_value)


@lru_cache
def get_desktop_window_preferences_service() -> DesktopWindowPreferencesService:
    return DesktopWindowPreferencesService(get_project_repository())
