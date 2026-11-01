-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

CREATE TABLE llm_conversation_session_index_next (
    project_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    title TEXT NOT NULL,
    provider_id TEXT,
    model_id TEXT,
    message_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    indexed_at TEXT NOT NULL,
    sequence_number INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (project_id, session_id)
);

INSERT INTO llm_conversation_session_index_next (
    project_id, session_id, title, provider_id, model_id,
    message_count, created_at, updated_at, indexed_at, sequence_number
)
SELECT
    project_id, session_id, title, provider_id, model_id,
    message_count, created_at, updated_at, indexed_at, sequence_number
FROM llm_conversation_session_index;

DROP TABLE llm_conversation_session_index;

ALTER TABLE llm_conversation_session_index_next RENAME TO llm_conversation_session_index;

CREATE INDEX idx_llm_conversation_session_index_project
ON llm_conversation_session_index(project_id, updated_at);

CREATE TABLE llm_usage_records_next (
    usage_id TEXT PRIMARY KEY,
    project_id TEXT,
    session_id TEXT,
    message_id TEXT,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    usage_feature_key TEXT NOT NULL DEFAULT 'main_chat',
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens INTEGER NOT NULL DEFAULT 0,
    prompt_cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
    prompt_cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
    cost_amount REAL,
    cost_currency TEXT,
    is_estimated INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(project_id, session_id)
        REFERENCES llm_conversation_session_index(project_id, session_id)
        ON DELETE SET NULL
);

INSERT INTO llm_usage_records_next (
    usage_id, project_id, session_id, message_id,
    provider_id, model_id, usage_feature_key,
    prompt_tokens, completion_tokens, total_tokens, reasoning_tokens,
    prompt_cache_hit_tokens, prompt_cache_miss_tokens,
    cost_amount, cost_currency, is_estimated, created_at
)
SELECT
    usage_id, project_id, session_id, message_id,
    provider_id, model_id, usage_feature_key,
    prompt_tokens, completion_tokens, total_tokens, reasoning_tokens,
    prompt_cache_hit_tokens, prompt_cache_miss_tokens,
    cost_amount, cost_currency, is_estimated, created_at
FROM llm_usage_records;

DROP TABLE llm_usage_records;

ALTER TABLE llm_usage_records_next RENAME TO llm_usage_records;

CREATE INDEX idx_llm_usage_records_session
ON llm_usage_records(project_id, session_id, created_at);

CREATE INDEX idx_llm_usage_records_provider_model
ON llm_usage_records(provider_id, model_id, created_at);

CREATE INDEX idx_llm_usage_records_session_feature
ON llm_usage_records(
    project_id, session_id, provider_id, model_id,
    usage_feature_key, created_at
);

CREATE UNIQUE INDEX idx_llm_usage_records_message_unique
ON llm_usage_records(message_id)
WHERE message_id IS NOT NULL;
