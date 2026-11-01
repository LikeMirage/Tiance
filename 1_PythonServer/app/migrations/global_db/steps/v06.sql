-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL,
    category_id TEXT NOT NULL DEFAULT 'daily-project',
    is_default INTEGER NOT NULL,
    sort_order INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_default_singleton
ON projects(is_default)
WHERE is_default = 1;

CREATE TRIGGER IF NOT EXISTS trg_projects_root_path_unique_insert
BEFORE INSERT ON projects
WHEN EXISTS (
    SELECT 1
    FROM projects
    WHERE root_path = NEW.root_path
      AND project_id <> NEW.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'project_root_path_duplicate');
END;

CREATE TRIGGER IF NOT EXISTS trg_projects_root_path_unique_update
BEFORE UPDATE OF root_path ON projects
WHEN EXISTS (
    SELECT 1
    FROM projects
    WHERE root_path = NEW.root_path
      AND project_id <> OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'project_root_path_duplicate');
END;

CREATE INDEX IF NOT EXISTS idx_projects_sort_order
ON projects(sort_order, created_at);

CREATE INDEX IF NOT EXISTS idx_projects_category_order
ON projects(category_id, sort_order, created_at);
