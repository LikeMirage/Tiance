"""Global v48 to v49: attach run identity to activity records."""

import sqlite3
from datetime import UTC, datetime

_ACTIVITY_COLUMNS = ("activity_type", "source_id", "amount", "occurred_at")
_SOURCE_TABLES = {
    "schema_migrations", "app_metadata", "llm_functional_model_settings",
    "workspace_activity_records", "workspace_activity_baselines",
    "llm_token_estimation_settings", "network_settings",
}


def inspect_v48(connection: sqlite3.Connection) -> None:
    tables = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if not _SOURCE_TABLES <= tables:
        raise RuntimeError(f"Unsupported global v48 structure; missing tables: {sorted(_SOURCE_TABLES - tables)}")
    columns = tuple(row[1] for row in connection.execute("PRAGMA table_info(workspace_activity_records)"))
    if columns != _ACTIVITY_COLUMNS:
        raise RuntimeError(f"Unexpected global v48 activity columns: {columns}")
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_workspace_activity_duration'"
    ).fetchone():
        raise RuntimeError("Global v49 activity index already exists in a v48 database.")


def upgrade(connection: sqlite3.Connection) -> None:
    inspect_v48(connection)
    for column in ("project_id", "session_id", "user_message_id"):
        connection.execute(f"ALTER TABLE workspace_activity_records ADD COLUMN {column} TEXT")
    connection.execute(
        "CREATE INDEX idx_workspace_activity_duration "
        "ON workspace_activity_records(activity_type, amount DESC, source_id)"
    )
    connection.execute(
        "INSERT INTO schema_migrations(version, name, applied_at) VALUES (49, ?, ?)",
        ("workspace_activity_run_identity", datetime.now(UTC).isoformat()),
    )
