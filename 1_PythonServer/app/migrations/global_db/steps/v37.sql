-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

UPDATE project_categories
SET name = '基础角色',
    updated_at = CURRENT_TIMESTAMP
WHERE category_id = 'default-role-category'
  AND category_kind = 'role';
