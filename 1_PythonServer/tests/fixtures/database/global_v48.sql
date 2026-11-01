-- Frozen global schema v48.
CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            );

CREATE TABLE app_metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

CREATE TABLE llm_functional_model_settings (
        settings_id TEXT PRIMARY KEY,
        version INTEGER NOT NULL,
        settings_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

CREATE TABLE workspace_activity_records (activity_type TEXT NOT NULL, source_id TEXT NOT NULL, amount INTEGER NOT NULL, occurred_at TEXT NOT NULL, PRIMARY KEY(activity_type, source_id));

CREATE TABLE workspace_activity_baselines (
        activity_type TEXT PRIMARY KEY,
        baseline_count INTEGER NOT NULL,
        starts_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

CREATE TABLE llm_token_estimation_settings (
        settings_id TEXT PRIMARY KEY,
        version INTEGER NOT NULL,
        settings_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

CREATE TABLE network_settings (
                settings_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                settings_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

CREATE INDEX idx_workspace_activity_records_type_time
    ON workspace_activity_records(activity_type, occurred_at);
INSERT INTO schema_migrations VALUES (48, 'old', '2026-10-01');
