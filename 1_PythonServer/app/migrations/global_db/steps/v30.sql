-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

UPDATE projects
SET project_kind = 'standard'
WHERE project_kind IS NULL OR trim(project_kind) = '';
