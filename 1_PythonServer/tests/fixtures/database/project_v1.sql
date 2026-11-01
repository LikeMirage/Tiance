BEGIN TRANSACTION;
CREATE TABLE conversation_messages (
            session_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            message_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(session_id, ordinal),
            UNIQUE(session_id, message_id),
            FOREIGN KEY(session_id) REFERENCES conversation_sessions(session_id) ON DELETE CASCADE
        );
CREATE TABLE conversation_meta (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL
        );
CREATE TABLE conversation_project_events (
            kind TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(kind, ordinal)
        );
CREATE TABLE conversation_schema (
            version INTEGER NOT NULL
        );
INSERT INTO "conversation_schema" VALUES(1);
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
CREATE TABLE conversation_sessions (
            session_id TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL
        );
CREATE INDEX idx_conversation_messages_id
            ON conversation_messages(message_id);
CREATE INDEX idx_compression_record_id
        ON conversation_session_events(session_id, json_extract(payload_json, '$.compression_id'))
        WHERE kind = 'compressions';
CREATE INDEX idx_compression_status
        ON conversation_session_events(session_id, json_extract(payload_json, '$.source_type'),
            json_extract(payload_json, '$.status'), ordinal DESC)
        WHERE kind = 'compressions';
COMMIT;
