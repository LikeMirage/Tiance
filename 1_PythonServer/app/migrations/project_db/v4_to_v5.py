"""Historical project conversion, within the caller transaction."""

import sqlite3
from app.migrations.sql import execute_script


def upgrade(connection: sqlite3.Connection) -> None:
    execute_script(connection,
        """
        CREATE TABLE IF NOT EXISTS conversation_runs (
            run_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            user_message_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('running', 'done', 'error', 'cancelled')),
            error_code TEXT,
            error_message TEXT,
            attempt_count INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            settled_at TEXT,
            FOREIGN KEY(session_id) REFERENCES conversation_sessions(session_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_conversation_runs_session_user
            ON conversation_runs(session_id, user_message_id, started_at);
        UPDATE conversation_schema SET version = 5;
        """
    )
