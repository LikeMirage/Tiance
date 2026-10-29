"""Current global schema. Existing databases must already use this version."""
from datetime import UTC, datetime
from pathlib import Path
from app.infra.database.sqlite import database_transaction

SCHEMA_VERSION = 49
SCHEMA_STATEMENTS = (
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
    with database_transaction(database_path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if tables:
            version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] if 'schema_migrations' in tables else None
            if version != SCHEMA_VERSION:
                raise RuntimeError(f"Unsupported global database schema {version}; expected {SCHEMA_VERSION}. No data was converted or removed.")
            return
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        connection.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES (?,?,?)", (SCHEMA_VERSION, 'current_schema', datetime.now(UTC).isoformat()))
