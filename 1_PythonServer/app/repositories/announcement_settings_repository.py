from __future__ import annotations

from contextlib import suppress
import json
from pathlib import Path
from threading import RLock
from uuid import uuid4

from pydantic import ValidationError

from app.core.atomic_replace import atomic_replace_path
from app.core.errors import BadRequestError
from app.schemas.announcements import AnnouncementSettings


class AnnouncementSettingsRepository:
    def __init__(self, settings_path: Path, *, default_source: str) -> None:
        self._settings_path = settings_path
        self._default_source = default_source
        self._lock = RLock()

    def get_settings(self) -> AnnouncementSettings:
        with self._lock:
            try:
                raw = self._settings_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                return AnnouncementSettings(source=self._default_source, check_on_startup=True)
            except OSError as exc:
                raise BadRequestError("无法读取公告设置。") from exc
            try:
                return AnnouncementSettings.model_validate_json(raw)
            except (ValidationError, ValueError) as exc:
                raise BadRequestError("公告设置文件格式无效。") from exc

    def save_settings(self, settings: AnnouncementSettings) -> AnnouncementSettings:
        with self._lock:
            self._settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._settings_path.with_name(
                f".{self._settings_path.name}.{uuid4().hex}.tmp"
            )
            try:
                temporary.write_text(
                    json.dumps(
                        settings.model_dump(mode="json", by_alias=True),
                        ensure_ascii=False,
                        indent=2,
                    ) + "\n",
                    encoding="utf-8",
                )
                atomic_replace_path(temporary, self._settings_path)
            finally:
                with suppress(OSError):
                    temporary.unlink(missing_ok=True)
            return settings

    def save_source(self, source: str) -> AnnouncementSettings:
        return self.save_settings(self.get_settings().model_copy(update={"source": source}))
