from __future__ import annotations

from contextlib import suppress
import json
from pathlib import Path
from typing import Generic, TypeVar
from uuid import uuid4

from pydantic import BaseModel

from app.core.atomic_replace import atomic_replace_path


SettingsT = TypeVar("SettingsT", bound=BaseModel)


class OnlineMarketSettingsRepository(Generic[SettingsT]):
    """在线市场地址和筛选条件共用的 JSON 持久化。"""

    def __init__(
        self,
        settings_path: Path,
        *,
        settings_model: type[SettingsT],
        default_source: str,
    ) -> None:
        self._settings_path = settings_path
        self._settings_model = settings_model
        self._default_source = default_source

    def get_settings(self) -> SettingsT:
        return self._read_settings() or self._settings_model(source=self._default_source)

    def ensure_settings_file(self) -> SettingsT:
        current = self._read_settings()
        return current if current is not None else self.save_settings(self.get_settings())

    def save_source(self, source: str) -> SettingsT:
        return self.save_settings(self.get_settings().model_copy(update={"source": source}))

    def save_filters(self, filters: BaseModel) -> SettingsT:
        return self.save_settings(self.get_settings().model_copy(update={"filters": filters}))

    def save_settings(self, settings: SettingsT) -> SettingsT:
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
                )
                + "\n",
                encoding="utf-8",
            )
            atomic_replace_path(temporary, self._settings_path)
        finally:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
        return settings

    def _read_settings(self) -> SettingsT | None:
        try:
            return self._settings_model.model_validate_json(
                self._settings_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None
