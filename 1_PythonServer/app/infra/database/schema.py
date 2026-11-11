"""Fresh global schema and the single initialization/upgrade entry point."""
from datetime import UTC, datetime
from pathlib import Path
from app.infra.database.sqlite import database_connection
from app.migrations.global_db import ensure_version
from app.migrations.runner import schema_transaction
from app.infra.database.mobile_schema import MOBILE_SCHEMA

SCHEMA_VERSION = 55
SCHEMA_STATEMENTS = (
    """CREATE TABLE collection_default_roles (
        project_kind TEXT PRIMARY KEY,
        role_project_id TEXT NOT NULL
    )""",
    """CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )""",
    """CREATE TABLE app_metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE llm_functional_model_settings (
        settings_id TEXT PRIMARY KEY,
        version INTEGER NOT NULL,
        settings_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE workspace_activity_records (
        activity_type TEXT NOT NULL,
        source_id TEXT NOT NULL,
        amount INTEGER NOT NULL,
        occurred_at TEXT NOT NULL, project_id TEXT, session_id TEXT, user_message_id TEXT,
        PRIMARY KEY (activity_type, source_id)
    )""",
    """CREATE TABLE workspace_activity_baselines (
        activity_type TEXT PRIMARY KEY,
        baseline_count INTEGER NOT NULL,
        starts_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE llm_token_estimation_settings (
        settings_id TEXT PRIMARY KEY,
        version INTEGER NOT NULL,
        settings_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE network_settings (
                settings_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                settings_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""",
    """CREATE INDEX idx_workspace_activity_records_type_time
    ON workspace_activity_records(activity_type, occurred_at)""",
    """CREATE INDEX idx_workspace_activity_duration
            ON workspace_activity_records(activity_type, amount DESC, source_id)""",
)

def ensure_database_schema(database_path: Path) -> None:
    with database_connection(database_path) as connection:
        # Historical table replacements require FK enforcement off before BEGIN.
        # The migration runner verifies all foreign keys before committing.
        connection.execute("PRAGMA foreign_keys=OFF")
        with schema_transaction(connection):
            _ensure_schema(connection)
    from app.migrations.functional_settings import upgrade_profiles
    upgrade_profiles(database_path)


def _ensure_schema(connection) -> None:
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if tables:
        ensure_version(connection, SCHEMA_VERSION)
        return
    for statement in SCHEMA_STATEMENTS + MOBILE_SCHEMA:
        connection.execute(statement)
    connection.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES (?,?,?)", (SCHEMA_VERSION, 'current_schema', datetime.now(UTC).isoformat()))
