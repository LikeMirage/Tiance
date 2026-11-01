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

CREATE TABLE IF NOT EXISTS project_categories (
    category_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    is_default INTEGER NOT NULL,
    sort_order INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_project_categories_default_singleton
ON project_categories(is_default)
WHERE is_default = 1;

CREATE UNIQUE INDEX IF NOT EXISTS idx_project_categories_name_unique
ON project_categories(name COLLATE NOCASE);

CREATE INDEX IF NOT EXISTS idx_project_categories_sort_order
ON project_categories(sort_order, created_at);

INSERT INTO project_categories (
    category_id,
    name,
    is_default,
    sort_order,
    created_at,
    updated_at
)
SELECT
    'daily-project',
    '日常项目',
    1,
    0,
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1
    FROM project_categories
    WHERE category_id = 'daily-project'
);

UPDATE projects
SET category_id = 'daily-project'
WHERE category_id IS NULL OR trim(category_id) = '';

CREATE INDEX IF NOT EXISTS idx_projects_category_order
ON projects(category_id, sort_order, created_at);
