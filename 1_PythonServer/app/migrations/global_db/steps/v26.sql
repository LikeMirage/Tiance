-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

CREATE TABLE IF NOT EXISTS workspace_activity_records (
    activity_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    amount INTEGER NOT NULL,
    occurred_at TEXT NOT NULL,
    PRIMARY KEY (activity_type, source_id)
);

CREATE INDEX IF NOT EXISTS idx_workspace_activity_records_type_time
ON workspace_activity_records(activity_type, occurred_at);

INSERT OR IGNORE INTO workspace_activity_records (
    activity_type,
    source_id,
    amount,
    occurred_at
)
SELECT
    'conversation_created',
    session_id,
    1,
    created_at
FROM llm_conversation_session_index;
