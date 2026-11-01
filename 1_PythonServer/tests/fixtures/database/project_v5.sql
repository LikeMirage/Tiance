-- Frozen project schema v5, before audit snapshots and compression indexes.
CREATE TABLE conversation_schema (
            version INTEGER NOT NULL
        );

CREATE TABLE conversation_meta (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL
        );

CREATE TABLE conversation_sessions (
            session_id TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL
        );

CREATE TABLE conversation_messages (
            session_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            message_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(session_id, ordinal),
            UNIQUE(session_id, message_id),
            FOREIGN KEY(session_id) REFERENCES conversation_sessions(session_id) ON DELETE CASCADE
        );

CREATE TABLE conversation_session_documents (
            session_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(session_id, kind),
            FOREIGN KEY(session_id) REFERENCES conversation_sessions(session_id) ON DELETE CASCADE
        );

CREATE TABLE conversation_session_events (
            session_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(session_id, kind, ordinal),
            FOREIGN KEY(session_id) REFERENCES conversation_sessions(session_id) ON DELETE CASCADE
        );

CREATE TABLE conversation_project_events (
            kind TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(kind, ordinal)
        );

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

CREATE TABLE conversation_artifact_payloads (
            artifact_id TEXT PRIMARY KEY,
            compression TEXT NOT NULL,
            stored_size_bytes INTEGER NOT NULL,
            payload_blob BLOB NOT NULL,
            FOREIGN KEY(artifact_id) REFERENCES conversation_artifacts(artifact_id) ON DELETE CASCADE
        );

CREATE TABLE conversation_session_runtime_states (
            session_id TEXT PRIMARY KEY,
            runtime_status TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES conversation_sessions(session_id) ON DELETE CASCADE
        );

CREATE TABLE conversation_session_drafts (
            session_id TEXT PRIMARY KEY,
            draft TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES conversation_sessions(session_id) ON DELETE CASCADE
        );

CREATE TABLE conversation_session_references (
            session_id TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES conversation_sessions(session_id) ON DELETE CASCADE
        );

CREATE TABLE conversation_runs (
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

CREATE INDEX idx_conversation_messages_id
            ON conversation_messages(message_id);

CREATE INDEX idx_conversation_artifacts_session
            ON conversation_artifacts(session_id, created_at);

CREATE INDEX idx_conversation_journal_session
            ON conversation_journal(session_id, event_id);

CREATE INDEX idx_conversation_journal_run
            ON conversation_journal(run_id, event_id);

CREATE INDEX idx_conversation_journal_tool_call
            ON conversation_journal(tool_call_id, event_id);

CREATE INDEX idx_conversation_journal_type
            ON conversation_journal(event_type, event_id);

CREATE INDEX idx_conversation_runs_session_user
            ON conversation_runs(session_id, user_message_id, started_at);
INSERT INTO conversation_schema VALUES (5);
