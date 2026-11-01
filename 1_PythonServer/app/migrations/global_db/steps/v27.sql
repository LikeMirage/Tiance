-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

CREATE TABLE IF NOT EXISTS workspace_activity_baselines (
    activity_type TEXT PRIMARY KEY,
    baseline_count INTEGER NOT NULL,
    starts_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
