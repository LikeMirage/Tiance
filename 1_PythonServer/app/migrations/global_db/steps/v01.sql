-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

CREATE TABLE IF NOT EXISTS custom_provider_catalog (
    provider_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    upstream_key TEXT NOT NULL,
    protocol_family TEXT NOT NULL,
    auth_scheme TEXT NOT NULL,
    supports_custom_base_url INTEGER NOT NULL,
    api_base_url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_configs (
    provider_id TEXT PRIMARY KEY,
    api_base_url TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_config_api_keys (
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

CREATE INDEX IF NOT EXISTS idx_provider_config_api_keys_provider_id
ON provider_config_api_keys(provider_id, sort_order);

CREATE TABLE IF NOT EXISTS provider_cloud_model_caches (
    provider_id TEXT NOT NULL,
    protocol_family TEXT NOT NULL,
    api_base_url TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    PRIMARY KEY (provider_id, protocol_family, api_base_url)
);

CREATE TABLE IF NOT EXISTS provider_cloud_model_items (
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

CREATE INDEX IF NOT EXISTS idx_provider_cloud_model_items_binding
ON provider_cloud_model_items(provider_id, protocol_family, api_base_url, sort_order);
