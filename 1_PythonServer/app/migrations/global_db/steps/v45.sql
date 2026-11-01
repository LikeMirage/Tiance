-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

CREATE TABLE IF NOT EXISTS app_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Preserve the retired selection as historical data; current readers use theme-settings.json.
