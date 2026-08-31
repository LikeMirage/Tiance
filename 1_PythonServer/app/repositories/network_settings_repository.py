from datetime import UTC, datetime
from functools import lru_cache
import json
from pathlib import Path
import sqlite3

from app.core.config import get_settings
from app.domain.network_settings import (
    BackendPortMode,
    NetworkConnectionMode,
    NetworkSettings,
    ProxyScheme,
)
from app.infra.database import database_connection, database_transaction


_SETTINGS_ID = "default"
_SETTINGS_VERSION = 1


class NetworkSettingsRepository:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def get_settings(self) -> NetworkSettings | None:
        with database_connection(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT settings_json, updated_at
                FROM network_settings
                WHERE settings_id = ?
                """,
                (_SETTINGS_ID,),
            ).fetchone()
        return None if row is None else _row_to_settings(row)

    def save_settings(self, settings: NetworkSettings) -> NetworkSettings:
        now = datetime.now(UTC).isoformat()
        payload = {
            "connection_mode": settings.connection_mode.value,
            "proxy_scheme": settings.proxy_scheme.value,
            "proxy_host": settings.proxy_host,
            "proxy_port": settings.proxy_port,
            "connect_timeout_seconds": settings.connect_timeout_seconds,
            "read_timeout_seconds": settings.read_timeout_seconds,
            "stream_timeout_seconds": settings.stream_timeout_seconds,
            "backend_port_mode": settings.backend_port_mode.value,
            "fixed_backend_port": settings.fixed_backend_port,
            "external_access_enabled": settings.external_access_enabled,
        }
        with database_transaction(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO network_settings (
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
        return NetworkSettings(
            connection_mode=settings.connection_mode,
            proxy_scheme=settings.proxy_scheme,
            proxy_host=settings.proxy_host,
            proxy_port=settings.proxy_port,
            connect_timeout_seconds=settings.connect_timeout_seconds,
            read_timeout_seconds=settings.read_timeout_seconds,
            stream_timeout_seconds=settings.stream_timeout_seconds,
            backend_port_mode=settings.backend_port_mode,
            fixed_backend_port=settings.fixed_backend_port,
            external_access_enabled=settings.external_access_enabled,
            updated_at=now,
        )


def _row_to_settings(row: sqlite3.Row) -> NetworkSettings | None:
    try:
        payload = json.loads(str(row["settings_json"]))
        return NetworkSettings(
            connection_mode=NetworkConnectionMode(str(payload["connection_mode"])),
            proxy_scheme=ProxyScheme(str(payload["proxy_scheme"])),
            proxy_host=str(payload["proxy_host"]),
            proxy_port=int(payload["proxy_port"]),
            connect_timeout_seconds=float(payload["connect_timeout_seconds"]),
            read_timeout_seconds=float(payload["read_timeout_seconds"]),
            stream_timeout_seconds=float(payload["stream_timeout_seconds"]),
            backend_port_mode=BackendPortMode(str(payload["backend_port_mode"])),
            fixed_backend_port=int(payload["fixed_backend_port"]),
            external_access_enabled=payload.get("external_access_enabled") is True,
            updated_at=str(row["updated_at"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


@lru_cache
def get_network_settings_repository() -> NetworkSettingsRepository:
    settings = get_settings()
    return NetworkSettingsRepository(settings.app_database_file)
