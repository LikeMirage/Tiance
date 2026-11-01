-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

DROP TRIGGER IF EXISTS trg_projects_category_kind_insert;

DROP TRIGGER IF EXISTS trg_projects_category_kind_update;

DROP TRIGGER IF EXISTS trg_project_categories_kind_update;

DROP TRIGGER IF EXISTS trg_projects_root_path_unique_insert;

DROP TRIGGER IF EXISTS trg_projects_root_path_unique_update;

DROP TRIGGER IF EXISTS trg_reject_legacy_role_category_insert;

DROP TRIGGER IF EXISTS trg_reject_legacy_role_category_id_update;

DROP INDEX IF EXISTS idx_projects_default_singleton;

DROP INDEX IF EXISTS idx_projects_sort_order;

DROP INDEX IF EXISTS idx_projects_category_order;

DROP INDEX IF EXISTS idx_project_categories_kind_default_singleton;

DROP INDEX IF EXISTS idx_project_categories_kind_name_unique;

DROP INDEX IF EXISTS idx_project_categories_sort_order;

CREATE TABLE project_categories_next (
    category_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    is_default INTEGER NOT NULL,
    sort_order INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    category_kind TEXT NOT NULL DEFAULT 'standard'
        CHECK (category_kind IN ('standard', 'role', 'theme'))
);

INSERT INTO project_categories_next (
    category_id,
    name,
    is_default,
    sort_order,
    created_at,
    updated_at,
    category_kind
)
SELECT
    category_id,
    name,
    is_default,
    sort_order,
    created_at,
    updated_at,
    category_kind
FROM project_categories;

CREATE TABLE projects_next (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL,
    category_id TEXT NOT NULL DEFAULT 'daily-project',
    is_default INTEGER NOT NULL,
    sort_order INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    project_kind TEXT NOT NULL DEFAULT 'standard'
        CHECK (project_kind IN ('standard', 'role', 'theme'))
);

INSERT INTO projects_next (
    project_id,
    name,
    root_path,
    category_id,
    is_default,
    sort_order,
    created_at,
    updated_at,
    project_kind
)
SELECT
    project_id,
    name,
    root_path,
    category_id,
    is_default,
    sort_order,
    created_at,
    updated_at,
    project_kind
FROM projects;

DROP TABLE projects;

DROP TABLE project_categories;

ALTER TABLE project_categories_next RENAME TO project_categories;

ALTER TABLE projects_next RENAME TO projects;

CREATE UNIQUE INDEX idx_projects_default_singleton
ON projects(is_default)
WHERE is_default = 1;

CREATE INDEX idx_projects_sort_order
ON projects(sort_order, created_at);

CREATE INDEX idx_projects_category_order
ON projects(category_id, sort_order, created_at);

CREATE UNIQUE INDEX idx_project_categories_kind_default_singleton
ON project_categories(category_kind)
WHERE is_default = 1;

CREATE UNIQUE INDEX idx_project_categories_kind_name_unique
ON project_categories(category_kind, name COLLATE NOCASE);

CREATE INDEX idx_project_categories_sort_order
ON project_categories(sort_order, created_at);

CREATE TRIGGER trg_projects_root_path_unique_insert
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

CREATE TRIGGER trg_projects_root_path_unique_update
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

CREATE TRIGGER trg_projects_category_kind_insert
BEFORE INSERT ON projects
WHEN NOT EXISTS (
    SELECT 1
    FROM project_categories
    WHERE category_id = NEW.category_id
      AND category_kind = NEW.project_kind
)
BEGIN
    SELECT RAISE(ABORT, 'project_category_kind_mismatch');
END;

CREATE TRIGGER trg_projects_category_kind_update
BEFORE UPDATE OF category_id, project_kind ON projects
WHEN NOT EXISTS (
    SELECT 1
    FROM project_categories
    WHERE category_id = NEW.category_id
      AND category_kind = NEW.project_kind
)
BEGIN
    SELECT RAISE(ABORT, 'project_category_kind_mismatch');
END;

CREATE TRIGGER trg_project_categories_kind_update
BEFORE UPDATE OF category_kind ON project_categories
WHEN EXISTS (
    SELECT 1
    FROM projects
    WHERE category_id = OLD.category_id
      AND project_kind <> NEW.category_kind
)
BEGIN
    SELECT RAISE(ABORT, 'project_category_kind_mismatch');
END;

CREATE TRIGGER trg_reject_legacy_role_category_insert
BEFORE INSERT ON project_categories
WHEN NEW.category_id = 'role-set'
BEGIN
    SELECT RAISE(ABORT, 'legacy_role_category_removed');
END;

CREATE TRIGGER trg_reject_legacy_role_category_id_update
BEFORE UPDATE OF category_id ON project_categories
WHEN NEW.category_id = 'role-set'
BEGIN
    SELECT RAISE(ABORT, 'legacy_role_category_removed');
END;
