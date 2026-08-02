from datetime import UTC, datetime
from functools import lru_cache
import json
from pathlib import Path
import sqlite3
from typing import Any

from app.core.config import get_settings
from app.domain.llm.functional_model_settings import LlmFunctionalModelSettings
from app.infra.database import database_connection, database_transaction


DEFAULT_FUNCTIONAL_MODEL_SETTINGS_ID = "default"


class LlmFunctionalModelSettingsRepository:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def get_settings(
        self,
        settings_id: str = DEFAULT_FUNCTIONAL_MODEL_SETTINGS_ID,
    ) -> LlmFunctionalModelSettings | None:
        with database_connection(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT settings_id, version, settings_json, created_at, updated_at
                FROM llm_functional_model_settings
                WHERE settings_id = ?
                """,
                (settings_id,),
            ).fetchone()

        return None if row is None else _row_to_domain(row)

    def save_settings(
        self,
        *,
        settings: dict[str, Any],
        version: int,
        settings_id: str = DEFAULT_FUNCTIONAL_MODEL_SETTINGS_ID,
    ) -> LlmFunctionalModelSettings:
        now = datetime.now(UTC).isoformat()
        existing = self.get_settings(settings_id)
        created_at = existing.created_at if existing is not None else now
        settings_json = json.dumps(settings, ensure_ascii=False, sort_keys=True)

        with database_transaction(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO llm_functional_model_settings (
                    settings_id,
                    version,
                    settings_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(settings_id) DO UPDATE SET
                    version = excluded.version,
                    settings_json = excluded.settings_json,
                    updated_at = excluded.updated_at
                """,
                (settings_id, version, settings_json, created_at, now),
            )

        return LlmFunctionalModelSettings(
            settings_id=settings_id,
            version=version,
            settings=settings,
            created_at=created_at,
            updated_at=now,
        )


def _row_to_domain(row: sqlite3.Row) -> LlmFunctionalModelSettings:
    return LlmFunctionalModelSettings(
        settings_id=str(row["settings_id"]),
        version=int(row["version"]),
        settings=_load_settings_json(str(row["settings_json"])),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _load_settings_json(raw_value: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}

    return payload if isinstance(payload, dict) else {}


@lru_cache
def get_llm_functional_model_settings_repository() -> LlmFunctionalModelSettingsRepository:
    settings = get_settings()
    return LlmFunctionalModelSettingsRepository(settings.app_database_file)
