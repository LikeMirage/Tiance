-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

UPDATE projects
SET category_id = 'default-role-category',
    updated_at = CURRENT_TIMESTAMP
WHERE category_id = 'role-set'
  AND project_kind = 'role';

DELETE FROM project_categories
WHERE category_id = 'role-set';

CREATE TRIGGER IF NOT EXISTS trg_reject_legacy_role_category_insert
BEFORE INSERT ON project_categories
WHEN NEW.category_id = 'role-set'
BEGIN
    SELECT RAISE(ABORT, 'legacy_role_category_removed');
END;

CREATE TRIGGER IF NOT EXISTS trg_reject_legacy_role_category_id_update
BEFORE UPDATE OF category_id ON project_categories
WHEN NEW.category_id = 'role-set'
BEGIN
    SELECT RAISE(ABORT, 'legacy_role_category_removed');
END;
