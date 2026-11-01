-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

CREATE TABLE IF NOT EXISTS provider_catalog_order (
    provider_id TEXT PRIMARY KEY,
    sort_order INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_provider_catalog_order_sort_order
ON provider_catalog_order(sort_order);
