-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

UPDATE project_categories
SET category_kind = 'standard'
WHERE category_kind IS NULL OR trim(category_kind) = '';

DROP INDEX IF EXISTS idx_project_categories_name_unique;

CREATE UNIQUE INDEX IF NOT EXISTS idx_project_categories_kind_name_unique
ON project_categories(category_kind, name COLLATE NOCASE);

INSERT INTO project_categories (
    category_id,
    name,
    category_kind,
    is_default,
    sort_order,
    created_at,
    updated_at
) VALUES (
    'role-set',
    '角色集',
    'role',
    0,
    0,
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
)
ON CONFLICT(category_id) DO UPDATE SET
    name = excluded.name,
    category_kind = excluded.category_kind,
    is_default = 0,
    sort_order = excluded.sort_order,
    updated_at = CURRENT_TIMESTAMP;
