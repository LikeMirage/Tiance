-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

CREATE TABLE IF NOT EXISTS llm_functional_model_settings (
    settings_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    settings_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
