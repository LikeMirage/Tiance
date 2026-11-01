-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

CREATE TABLE provider_config_api_keys_next (
    key_id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    api_key_hint TEXT,
    api_key_ciphertext TEXT,
    poll_weight INTEGER NOT NULL,
    sort_order INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(provider_id) REFERENCES provider_configs(provider_id) ON DELETE CASCADE
);

INSERT INTO provider_config_api_keys_next (
    key_id,
    provider_id,
    api_key_hint,
    api_key_ciphertext,
    poll_weight,
    sort_order,
    created_at,
    updated_at
)
SELECT
    key_id,
    provider_id,
    api_key_hint,
    api_key_ciphertext,
    poll_weight,
    sort_order,
    created_at,
    updated_at
FROM provider_config_api_keys;

DROP TABLE provider_config_api_keys;

ALTER TABLE provider_config_api_keys_next RENAME TO provider_config_api_keys;

CREATE INDEX IF NOT EXISTS idx_provider_config_api_keys_provider_id
ON provider_config_api_keys(provider_id, sort_order);
