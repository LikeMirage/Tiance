-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

UPDATE projects
SET category_id = 'default-role-category',
    updated_at = CURRENT_TIMESTAMP
WHERE category_id = 'role-set'
  AND project_kind = 'role';

DELETE FROM project_categories
WHERE category_id = 'role-set';
