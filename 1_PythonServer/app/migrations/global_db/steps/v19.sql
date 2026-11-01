-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

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
