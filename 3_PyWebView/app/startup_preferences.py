"""Read-only boot snapshot adapter for backend-owned desktop preferences.

The backend owns writes and schema evolution. The shell reads only the versioned
snapshot needed before the backend is ready, and falls back to stable defaults
when the snapshot contract is unavailable or unsupported.
"""

from contextlib import closing
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3

from app.startup_timing import mark


APP_METADATA_TABLE = "app_metadata"
DESKTOP_WINDOW_SIZE_PREFERENCES_KEY = "desktop.window_size_preferences"
DESKTOP_WINDOW_SIZE_SNAPSHOT_VERSION = 1
NETWORK_SETTINGS_TABLE = "network_settings"
NETWORK_SETTINGS_ID = "default"
NETWORK_SETTINGS_SNAPSHOT_VERSION = 1
DEFAULT_WINDOW_WIDTH = 1440
DEFAULT_WINDOW_HEIGHT = 900
DEFAULT_WINDOW_MAXIMIZED = False
MIN_WINDOW_WIDTH = 1080
MIN_WINDOW_HEIGHT = 720
MAX_WINDOW_WIDTH = 7680
MAX_WINDOW_HEIGHT = 4320


@dataclass(frozen=True)
class DesktopWindowSizePreferences:
    width: int
    height: int
    maximized: bool


@dataclass(frozen=True)
class NetworkStartupPreferences:
    backend_port_mode: str
    fixed_backend_port: int


def load_desktop_window_size_preferences(project_root: Path) -> DesktopWindowSizePreferences:
    database_file = _resolve_database_file(project_root)
    if not database_file.is_file():
        return default_desktop_window_size_preferences()

    try:
        database_uri = f"{database_file.as_uri()}?mode=ro"
        with closing(sqlite3.connect(database_uri, uri=True)) as connection:
            row = connection.execute(
                f"SELECT value FROM {APP_METADATA_TABLE} WHERE key = ?",
                (DESKTOP_WINDOW_SIZE_PREFERENCES_KEY,),
            ).fetchone()
    except (OSError, sqlite3.Error) as exc:
        mark("startup snapshot: window preferences unavailable", error=str(exc))
        return default_desktop_window_size_preferences()

    if row is None:
        return default_desktop_window_size_preferences()

    try:
        payload = json.loads(str(row[0]))
    except (TypeError, ValueError):
        mark("startup snapshot: invalid window preferences JSON")
        return default_desktop_window_size_preferences()

    if not isinstance(payload, dict):
        mark("startup snapshot: invalid window preferences payload")
        return default_desktop_window_size_preferences()

    if payload.get("version") != DESKTOP_WINDOW_SIZE_SNAPSHOT_VERSION:
        mark(
            "startup snapshot: unsupported window preferences version",
            expected=DESKTOP_WINDOW_SIZE_SNAPSHOT_VERSION,
            actual=payload.get("version"),
        )
        return default_desktop_window_size_preferences()

    return DesktopWindowSizePreferences(
        width=_read_saved_window_dimension(
            payload.get("width"),
            DEFAULT_WINDOW_WIDTH,
            MIN_WINDOW_WIDTH,
            MAX_WINDOW_WIDTH,
        ),
        height=_read_saved_window_dimension(
            payload.get("height"),
            DEFAULT_WINDOW_HEIGHT,
            MIN_WINDOW_HEIGHT,
            MAX_WINDOW_HEIGHT,
        ),
        maximized=payload.get("maximized")
        if isinstance(payload.get("maximized"), bool)
        else DEFAULT_WINDOW_MAXIMIZED,
    )


def default_desktop_window_size_preferences() -> DesktopWindowSizePreferences:
    return DesktopWindowSizePreferences(
        width=DEFAULT_WINDOW_WIDTH,
        height=DEFAULT_WINDOW_HEIGHT,
        maximized=DEFAULT_WINDOW_MAXIMIZED,
    )


def load_network_startup_preferences(project_root: Path) -> NetworkStartupPreferences:
    database_file = _resolve_database_file(project_root)
    if not database_file.is_file():
        return default_network_startup_preferences()

    try:
        database_uri = f"{database_file.as_uri()}?mode=ro"
        with closing(sqlite3.connect(database_uri, uri=True)) as connection:
            row = connection.execute(
                f"""
                SELECT version, settings_json
                FROM {NETWORK_SETTINGS_TABLE}
                WHERE settings_id = ?
                """,
                (NETWORK_SETTINGS_ID,),
            ).fetchone()
    except (OSError, sqlite3.Error) as exc:
        mark("startup snapshot: network preferences unavailable", error=str(exc))
        return default_network_startup_preferences()

    if row is None or row[0] != NETWORK_SETTINGS_SNAPSHOT_VERSION:
        return default_network_startup_preferences()
    try:
        payload = json.loads(str(row[1]))
    except (TypeError, ValueError):
        mark("startup snapshot: invalid network preferences JSON")
        return default_network_startup_preferences()
    if not isinstance(payload, dict):
        return default_network_startup_preferences()

    port_mode = payload.get("backend_port_mode")
    fixed_port = payload.get("fixed_backend_port")
    return NetworkStartupPreferences(
        backend_port_mode=port_mode if port_mode in {"auto", "fixed"} else "auto",
        fixed_backend_port=_read_saved_port(fixed_port, 18000),
    )


def default_network_startup_preferences() -> NetworkStartupPreferences:
    return NetworkStartupPreferences(
        backend_port_mode="auto",
        fixed_backend_port=18000,
    )


def _resolve_database_file(project_root: Path) -> Path:
    configured_path = os.getenv("DATABASE_FILE", "Data/db/tiance.db")
    path = Path(configured_path).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()


def _read_saved_window_dimension(
    value: object,
    default: int,
    min_value: int,
    max_value: int,
) -> int:
    if isinstance(value, bool):
        candidate = default
    elif isinstance(value, int):
        candidate = value
    elif isinstance(value, float) and value.is_integer():
        candidate = int(value)
    else:
        candidate = default
    return min(max(candidate, min_value), max_value)


def _read_saved_port(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value if 1 <= value <= 65535 else default
