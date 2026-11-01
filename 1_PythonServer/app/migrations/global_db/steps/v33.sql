-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

DROP TRIGGER IF EXISTS trg_role_project_category_update;

DROP TRIGGER IF EXISTS trg_role_project_category_delete;

DROP INDEX IF EXISTS idx_project_categories_default_singleton;

CREATE UNIQUE INDEX IF NOT EXISTS idx_project_categories_kind_default_singleton
ON project_categories(category_kind)
WHERE is_default = 1;

INSERT INTO project_categories (
    category_id,
    name,
    category_kind,
    is_default,
    sort_order,
    created_at,
    updated_at
) VALUES (
    'default-role-category',
    '默认分类',
    'role',
    1,
    0,
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
)
ON CONFLICT(category_id) DO UPDATE SET
    name = excluded.name,
    category_kind = excluded.category_kind,
    is_default = 1,
    sort_order = excluded.sort_order,
    updated_at = CURRENT_TIMESTAMP;

UPDATE projects
SET category_id = 'default-role-category',
    updated_at = CURRENT_TIMESTAMP
WHERE category_id = 'role-set'
  AND project_kind = 'role';

DELETE FROM project_categories
WHERE category_id = 'role-set';
