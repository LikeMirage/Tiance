from datetime import UTC, datetime
from functools import lru_cache
import json
from pathlib import Path
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.core.config import get_settings


THEME_SETTINGS_FILE = "theme-settings.json"
THEME_SETTINGS_SCHEMA_VERSION = 1


class ThemeSettingsRepository:
    def __init__(self, settings_path: Path) -> None:
        self._settings_path = settings_path

    def get_active_theme_id(self) -> str | None:
        try:
            payload = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        if not isinstance(payload, dict):
            return None

        theme_id = str(payload.get("activeThemeId") or "").strip()
        return theme_id or None

    def save_active_theme_id(self, theme_id: str) -> None:
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schemaVersion": THEME_SETTINGS_SCHEMA_VERSION,
            "activeThemeId": theme_id,
            "updatedAt": datetime.now(UTC).isoformat(),
        }
        temporary_path = self._settings_path.with_name(
            f".{self._settings_path.name}.{uuid4().hex}.tmp"
        )
        try:
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            atomic_replace_path(temporary_path, self._settings_path)
        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    def ensure_active_theme_id(self, default_theme_id: str) -> str:
        active_theme_id = self.get_active_theme_id()
        if active_theme_id is not None:
            return active_theme_id

        self.save_active_theme_id(default_theme_id)
        return default_theme_id


@lru_cache
def get_theme_settings_repository() -> ThemeSettingsRepository:
    settings = get_settings()
    return ThemeSettingsRepository(settings.themes_data_path / THEME_SETTINGS_FILE)
