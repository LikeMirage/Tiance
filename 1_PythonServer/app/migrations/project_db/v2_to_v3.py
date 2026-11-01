"""Historical project conversion, within the caller transaction."""

import sqlite3
from app.migrations.sql import execute_script


def upgrade(connection: sqlite3.Connection) -> None:
    execute_script(connection,
        """
        CREATE TABLE conversation_artifact_payloads (
            artifact_id TEXT PRIMARY KEY,
            compression TEXT NOT NULL,
            stored_size_bytes INTEGER NOT NULL,
            payload_blob BLOB NOT NULL,
            FOREIGN KEY(artifact_id) REFERENCES conversation_artifacts(artifact_id) ON DELETE CASCADE
        );
        UPDATE conversation_schema SET version = 3;
        """
    )
