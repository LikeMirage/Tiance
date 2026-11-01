-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

UPDATE llm_usage_records
SET usage_feature_key = 'conversation_naming'
WHERE message_id LIKE 'system:naming:%';

CREATE INDEX IF NOT EXISTS idx_llm_usage_records_session_feature
ON llm_usage_records(project_id, session_id, provider_id, model_id, usage_feature_key, created_at);
