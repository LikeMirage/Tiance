-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

DELETE FROM provider_config_api_keys
WHERE provider_id NOT IN (SELECT provider_id FROM provider_configs);

CREATE TABLE provider_config_api_keys_next (
    key_id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    secret_ref TEXT NOT NULL,
    api_key_hint TEXT,
    poll_weight INTEGER NOT NULL,
    sort_order INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(provider_id) REFERENCES provider_configs(provider_id) ON DELETE CASCADE
);

INSERT INTO provider_config_api_keys_next (
    key_id,
    provider_id,
    secret_ref,
    api_key_hint,
    poll_weight,
    sort_order,
    created_at,
    updated_at
)
SELECT
    key_id,
    provider_id,
    secret_ref,
    api_key_hint,
    poll_weight,
    sort_order,
    created_at,
    updated_at
FROM provider_config_api_keys;

DROP TABLE provider_config_api_keys;

ALTER TABLE provider_config_api_keys_next RENAME TO provider_config_api_keys;

CREATE INDEX IF NOT EXISTS idx_provider_config_api_keys_provider_id
ON provider_config_api_keys(provider_id, sort_order);

DELETE FROM provider_cloud_model_items
WHERE NOT EXISTS (
    SELECT 1
    FROM provider_cloud_model_caches cache
    WHERE cache.provider_id = provider_cloud_model_items.provider_id
      AND cache.protocol_family = provider_cloud_model_items.protocol_family
      AND cache.api_base_url = provider_cloud_model_items.api_base_url
);

CREATE TABLE provider_cloud_model_items_next (
    provider_id TEXT NOT NULL,
    protocol_family TEXT NOT NULL,
    api_base_url TEXT NOT NULL,
    model_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    family_group TEXT NOT NULL,
    capability_tags TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    PRIMARY KEY (provider_id, protocol_family, api_base_url, model_id),
    FOREIGN KEY(provider_id, protocol_family, api_base_url)
        REFERENCES provider_cloud_model_caches(provider_id, protocol_family, api_base_url)
        ON DELETE CASCADE
);

INSERT INTO provider_cloud_model_items_next (
    provider_id,
    protocol_family,
    api_base_url,
    model_id,
    display_name,
    family_group,
    capability_tags,
    sort_order
)
SELECT
    provider_id,
    protocol_family,
    api_base_url,
    model_id,
    display_name,
    family_group,
    capability_tags,
    sort_order
FROM provider_cloud_model_items;

DROP TABLE provider_cloud_model_items;

ALTER TABLE provider_cloud_model_items_next RENAME TO provider_cloud_model_items;

CREATE INDEX IF NOT EXISTS idx_provider_cloud_model_items_binding
ON provider_cloud_model_items(provider_id, protocol_family, api_base_url, sort_order);

DELETE FROM llm_conversation_session_index
WHERE project_id NOT IN (SELECT project_id FROM projects);

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
    PRIMARY KEY (project_id, session_id),
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

INSERT INTO llm_conversation_session_index_next (
    project_id,
    session_id,
    title,
    provider_id,
    model_id,
    message_count,
    created_at,
    updated_at,
    indexed_at,
    sequence_number
)
SELECT
    project_id,
    session_id,
    title,
    provider_id,
    model_id,
    message_count,
    created_at,
    updated_at,
    indexed_at,
    sequence_number
FROM llm_conversation_session_index;

DROP TABLE llm_conversation_session_index;

ALTER TABLE llm_conversation_session_index_next RENAME TO llm_conversation_session_index;

CREATE INDEX IF NOT EXISTS idx_llm_conversation_session_index_project
ON llm_conversation_session_index(project_id, updated_at);

UPDATE llm_usage_records
SET project_id = NULL,
    session_id = NULL
WHERE project_id IS NOT NULL
  AND project_id NOT IN (SELECT project_id FROM projects);

UPDATE llm_usage_records
SET project_id = NULL,
    session_id = NULL
WHERE project_id IS NOT NULL
  AND session_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM llm_conversation_session_index session_index
      WHERE session_index.project_id = llm_usage_records.project_id
        AND session_index.session_id = llm_usage_records.session_id
  );

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
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE SET NULL,
    FOREIGN KEY(project_id, session_id)
        REFERENCES llm_conversation_session_index(project_id, session_id)
        ON DELETE SET NULL
);

INSERT INTO llm_usage_records_next (
    usage_id,
    project_id,
    session_id,
    message_id,
    provider_id,
    model_id,
    usage_feature_key,
    prompt_tokens,
    completion_tokens,
    total_tokens,
    reasoning_tokens,
    prompt_cache_hit_tokens,
    prompt_cache_miss_tokens,
    cost_amount,
    cost_currency,
    is_estimated,
    created_at
)
SELECT
    usage_id,
    project_id,
    session_id,
    message_id,
    provider_id,
    model_id,
    COALESCE(usage_feature_key, 'main_chat'),
    prompt_tokens,
    completion_tokens,
    total_tokens,
    reasoning_tokens,
    prompt_cache_hit_tokens,
    prompt_cache_miss_tokens,
    cost_amount,
    cost_currency,
    is_estimated,
    created_at
FROM llm_usage_records;

DROP TABLE llm_usage_records;

ALTER TABLE llm_usage_records_next RENAME TO llm_usage_records;

CREATE INDEX IF NOT EXISTS idx_llm_usage_records_session
ON llm_usage_records(project_id, session_id, created_at);

CREATE INDEX IF NOT EXISTS idx_llm_usage_records_provider_model
ON llm_usage_records(provider_id, model_id, created_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_llm_usage_records_message_unique
ON llm_usage_records(message_id)
WHERE message_id IS NOT NULL;
