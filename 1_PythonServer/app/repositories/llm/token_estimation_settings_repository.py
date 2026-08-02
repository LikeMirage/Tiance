from datetime import UTC, datetime
from functools import lru_cache
import json
from pathlib import Path
import sqlite3

from app.core.config import get_settings
from app.domain.llm.token_estimation_settings import TokenEstimationSettings
from app.infra.database import database_connection, database_transaction


_SETTINGS_ID = "default"
_SETTINGS_VERSION = 1


class TokenEstimationSettingsRepository:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def get_settings(self) -> TokenEstimationSettings | None:
        with database_connection(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT settings_json, updated_at
                FROM llm_token_estimation_settings
                WHERE settings_id = ?
                """,
                (_SETTINGS_ID,),
            ).fetchone()
        return None if row is None else _row_to_settings(row)

    def save_settings(
        self,
        settings: TokenEstimationSettings,
    ) -> TokenEstimationSettings:
        now = datetime.now(UTC).isoformat()
        payload = {
            "ascii_chars_per_token": settings.ascii_chars_per_token,
            "other_chars_per_token": settings.other_chars_per_token,
            "message_overhead_tokens": settings.message_overhead_tokens,
            "image_placeholder_tokens": settings.image_placeholder_tokens,
        }
        with database_transaction(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO llm_token_estimation_settings (
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
                (
                    _SETTINGS_ID,
                    _SETTINGS_VERSION,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
        return TokenEstimationSettings(**payload, updated_at=now)


def _row_to_settings(row: sqlite3.Row) -> TokenEstimationSettings | None:
    try:
        payload = json.loads(str(row["settings_json"]))
        return TokenEstimationSettings(
            ascii_chars_per_token=float(payload["ascii_chars_per_token"]),
            other_chars_per_token=float(payload["other_chars_per_token"]),
            message_overhead_tokens=int(payload["message_overhead_tokens"]),
            image_placeholder_tokens=int(payload["image_placeholder_tokens"]),
            updated_at=str(row["updated_at"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


@lru_cache
def get_token_estimation_settings_repository() -> TokenEstimationSettingsRepository:
    settings = get_settings()
    return TokenEstimationSettingsRepository(settings.app_database_file)
