-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

CREATE TABLE custom_provider_catalog_next (
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

INSERT INTO custom_provider_catalog_next (
    provider_id,
    display_name,
    upstream_key,
    protocol_family,
    auth_scheme,
    supports_custom_base_url,
    api_base_url,
    created_at,
    updated_at
)
SELECT
    provider_id,
    display_name,
    upstream_key,
    protocol_family,
    auth_scheme,
    supports_custom_base_url,
    api_base_url,
    created_at,
    updated_at
FROM custom_provider_catalog;

DROP TABLE custom_provider_catalog;

ALTER TABLE custom_provider_catalog_next RENAME TO custom_provider_catalog;
