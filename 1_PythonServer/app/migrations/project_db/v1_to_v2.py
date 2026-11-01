"""Historical project conversion, within the caller transaction."""

import sqlite3
from app.migrations.sql import execute_script


def upgrade(connection: sqlite3.Connection) -> None:
    execute_script(connection,
        """
        CREATE TABLE conversation_artifacts (
            artifact_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            media_type TEXT NOT NULL,
            encoding TEXT,
            size_bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES conversation_sessions(session_id) ON DELETE CASCADE
        );
        CREATE INDEX idx_conversation_artifacts_session
            ON conversation_artifacts(session_id, created_at);
        CREATE TABLE conversation_journal (
            event_id INTEGER PRIMARY KEY,
            session_id TEXT,
            run_id TEXT,
            turn_id TEXT,
            tool_call_id TEXT,
            event_type TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            artifact_id TEXT,
            FOREIGN KEY(session_id) REFERENCES conversation_sessions(session_id) ON DELETE CASCADE,
            FOREIGN KEY(artifact_id) REFERENCES conversation_artifacts(artifact_id) ON DELETE SET NULL
        );
        CREATE INDEX idx_conversation_journal_session
            ON conversation_journal(session_id, event_id);
        CREATE INDEX idx_conversation_journal_run
            ON conversation_journal(run_id, event_id);
        CREATE INDEX idx_conversation_journal_tool_call
            ON conversation_journal(tool_call_id, event_id);
        CREATE INDEX idx_conversation_journal_type
            ON conversation_journal(event_type, event_id);
        UPDATE conversation_schema SET version = 2;
        """
    )
