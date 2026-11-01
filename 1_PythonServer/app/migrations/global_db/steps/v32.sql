-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

CREATE TRIGGER IF NOT EXISTS trg_projects_category_kind_insert
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

CREATE TRIGGER IF NOT EXISTS trg_projects_category_kind_update
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

CREATE TRIGGER IF NOT EXISTS trg_project_categories_kind_update
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

CREATE TRIGGER IF NOT EXISTS trg_role_project_category_update
BEFORE UPDATE OF category_id, name, category_kind, is_default
ON project_categories
WHEN OLD.category_id = 'role-set'
BEGIN
    SELECT RAISE(ABORT, 'builtin_role_category_readonly');
END;

CREATE TRIGGER IF NOT EXISTS trg_role_project_category_delete
BEFORE DELETE ON project_categories
WHEN OLD.category_id = 'role-set'
BEGIN
    SELECT RAISE(ABORT, 'builtin_role_category_readonly');
END;
