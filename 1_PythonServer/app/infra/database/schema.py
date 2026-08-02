# 数据库 Schema 定义与迁移列表
# 包含所有建表语句、索引以及数据库版本迁移

from pathlib import Path

from app.infra.database.migrations import (
    AddColumnIfMissing,
    Migration,
    MigrationStatement,
    run_database_migrations,
)


INITIAL_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS custom_provider_catalog (
        provider_id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        upstream_key TEXT NOT NULL,
        protocol_family TEXT NOT NULL,
        auth_scheme TEXT NOT NULL,
        supports_custom_base_url INTEGER NOT NULL,
        api_base_url TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS provider_configs (
        provider_id TEXT PRIMARY KEY,
        api_base_url TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS provider_config_api_keys (
        key_id TEXT PRIMARY KEY,
        provider_id TEXT NOT NULL,
        secret_ref TEXT NOT NULL,
        api_key_hint TEXT,
        poll_weight INTEGER NOT NULL,
        sort_order INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(provider_id) REFERENCES provider_configs(provider_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_provider_config_api_keys_provider_id
    ON provider_config_api_keys(provider_id, sort_order)
    """,
    """
    CREATE TABLE IF NOT EXISTS provider_cloud_model_caches (
        provider_id TEXT NOT NULL,
        protocol_family TEXT NOT NULL,
        api_base_url TEXT NOT NULL,
        discovered_at TEXT NOT NULL,
        PRIMARY KEY (provider_id, protocol_family, api_base_url)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS provider_cloud_model_items (
        provider_id TEXT NOT NULL,
        protocol_family TEXT NOT NULL,
        api_base_url TEXT NOT NULL,
        model_id TEXT NOT NULL,
        display_name TEXT NOT NULL,
        family_group TEXT NOT NULL,
        capability_tags TEXT NOT NULL,
        sort_order INTEGER NOT NULL,
        PRIMARY KEY (provider_id, protocol_family, api_base_url, model_id),
        FOREIGN KEY(provider_id, protocol_family, api_base_url)
            REFERENCES provider_cloud_model_caches(provider_id, protocol_family, api_base_url)
            ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_provider_cloud_model_items_binding
    ON provider_cloud_model_items(provider_id, protocol_family, api_base_url, sort_order)
    """,
)


CUSTOM_PROVIDER_MODELS_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS provider_custom_models (
        provider_id TEXT NOT NULL,
        model_id TEXT NOT NULL,
        display_name TEXT NOT NULL,
        family_group TEXT NOT NULL,
        capability_tags TEXT NOT NULL,
        note TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (provider_id, model_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_provider_custom_models_provider_id
    ON provider_custom_models(provider_id, created_at)
    """,
)


PROVIDER_CATALOG_ORDER_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS provider_catalog_order (
        provider_id TEXT PRIMARY KEY,
        sort_order INTEGER NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_provider_catalog_order_sort_order
    ON provider_catalog_order(sort_order)
    """,
)


PROJECT_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS projects (
        project_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        root_path TEXT NOT NULL,
        category_id TEXT NOT NULL DEFAULT 'daily-project',
        is_default INTEGER NOT NULL,
        sort_order INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_default_singleton
    ON projects(is_default)
    WHERE is_default = 1
    """,
    """
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
    END
    """,
    """
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
    END
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_projects_sort_order
    ON projects(sort_order, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_projects_category_order
    ON projects(category_id, sort_order, created_at)
    """,
)


PROJECT_CATEGORY_SCHEMA_STATEMENTS: tuple[MigrationStatement, ...] = (
    """
    CREATE TABLE IF NOT EXISTS projects (
        project_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        root_path TEXT NOT NULL,
        category_id TEXT NOT NULL DEFAULT 'daily-project',
        is_default INTEGER NOT NULL,
        sort_order INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS project_categories (
        category_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        is_default INTEGER NOT NULL,
        sort_order INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_project_categories_default_singleton
    ON project_categories(is_default)
    WHERE is_default = 1
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_project_categories_name_unique
    ON project_categories(name COLLATE NOCASE)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_project_categories_sort_order
    ON project_categories(sort_order, created_at)
    """,
    """
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
    )
    """,
    AddColumnIfMissing(
        table_name="projects",
        column_name="category_id",
        column_definition="TEXT NOT NULL DEFAULT 'daily-project'",
    ),
    """
    UPDATE projects
    SET category_id = 'daily-project'
    WHERE category_id IS NULL OR trim(category_id) = ''
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_projects_category_order
    ON projects(category_id, sort_order, created_at)
    """,
)


PROJECT_ROOT_PATH_GUARD_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
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
    END
    """,
    """
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
    END
    """,
)


WORKSPACE_ACTIVITY_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS workspace_activity_records (
        activity_type TEXT NOT NULL,
        source_id TEXT NOT NULL,
        amount INTEGER NOT NULL,
        occurred_at TEXT NOT NULL,
        PRIMARY KEY (activity_type, source_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_workspace_activity_records_type_time
    ON workspace_activity_records(activity_type, occurred_at)
    """,
)


WORKSPACE_ACTIVITY_BASELINE_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS workspace_activity_baselines (
        activity_type TEXT PRIMARY KEY,
        baseline_count INTEGER NOT NULL,
        starts_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
)


APP_METADATA_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS app_metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
)


LLM_FUNCTIONAL_MODEL_SETTINGS_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS llm_functional_model_settings (
        settings_id TEXT PRIMARY KEY,
        version INTEGER NOT NULL,
        settings_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
)


LLM_TOKEN_ESTIMATION_SETTINGS_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS llm_token_estimation_settings (
        settings_id TEXT PRIMARY KEY,
        version INTEGER NOT NULL,
        settings_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
)


LLM_USAGE_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS llm_conversation_session_index (
        project_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        title TEXT NOT NULL,
        provider_id TEXT,
        model_id TEXT,
        message_count INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        indexed_at TEXT NOT NULL,
        PRIMARY KEY (project_id, session_id),
        FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_llm_conversation_session_index_project
    ON llm_conversation_session_index(project_id, updated_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS llm_usage_records (
        usage_id TEXT PRIMARY KEY,
        project_id TEXT,
        session_id TEXT,
        message_id TEXT,
        provider_id TEXT NOT NULL,
        model_id TEXT NOT NULL,
        usage_feature_key TEXT NOT NULL DEFAULT 'main_chat',
        prompt_tokens INTEGER NOT NULL DEFAULT 0,
        completion_tokens INTEGER NOT NULL DEFAULT 0,
        total_tokens INTEGER NOT NULL DEFAULT 0,
        reasoning_tokens INTEGER NOT NULL DEFAULT 0,
        prompt_cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
        prompt_cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
        cost_amount REAL,
        cost_currency TEXT,
        is_estimated INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE SET NULL,
        FOREIGN KEY(project_id, session_id)
            REFERENCES llm_conversation_session_index(project_id, session_id)
            ON DELETE SET NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_llm_usage_records_session
    ON llm_usage_records(project_id, session_id, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_llm_usage_records_provider_model
    ON llm_usage_records(provider_id, model_id, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_llm_usage_records_session_feature
    ON llm_usage_records(project_id, session_id, provider_id, model_id, usage_feature_key, created_at)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_llm_usage_records_message_unique
    ON llm_usage_records(message_id)
    WHERE message_id IS NOT NULL
    """,
)


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="initial_llm_provider_schema",
        statements=INITIAL_SCHEMA_STATEMENTS,
    ),
    Migration(
        version=2,
        name="provider_custom_models",
        statements=CUSTOM_PROVIDER_MODELS_SCHEMA_STATEMENTS,
    ),
    Migration(
        version=3,
        name="provider_catalog_order",
        statements=PROVIDER_CATALOG_ORDER_SCHEMA_STATEMENTS,
    ),
    Migration(
        version=4,
        name="provider_custom_model_pricing",
        statements=(
            """
            ALTER TABLE provider_custom_models
            ADD COLUMN price_currency TEXT NOT NULL DEFAULT 'CNY'
            """,
            """
            ALTER TABLE provider_custom_models
            ADD COLUMN input_price_per_million REAL
            """,
            """
            ALTER TABLE provider_custom_models
            ADD COLUMN output_price_per_million REAL
            """,
        ),
    ),
    Migration(
        version=5,
        name="remove_derived_provider_endpoint_columns",
        statements=(
            """
            CREATE TABLE custom_provider_catalog_next (
                provider_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                upstream_key TEXT NOT NULL,
                protocol_family TEXT NOT NULL,
                auth_scheme TEXT NOT NULL,
                supports_custom_base_url INTEGER NOT NULL,
                api_base_url TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            INSERT INTO custom_provider_catalog_next (
                provider_id,
                display_name,
                upstream_key,
                protocol_family,
                auth_scheme,
                supports_custom_base_url,
                api_base_url,
                created_at,
                updated_at
            )
            SELECT
                provider_id,
                display_name,
                upstream_key,
                protocol_family,
                auth_scheme,
                supports_custom_base_url,
                api_base_url,
                created_at,
                updated_at
            FROM custom_provider_catalog
            """,
            "DROP TABLE custom_provider_catalog",
            "ALTER TABLE custom_provider_catalog_next RENAME TO custom_provider_catalog",
        ),
    ),
    Migration(
        version=6,
        name="projects",
        statements=PROJECT_SCHEMA_STATEMENTS,
    ),
    Migration(
        version=7,
        name="app_metadata",
        statements=APP_METADATA_SCHEMA_STATEMENTS,
    ),
    Migration(
        version=8,
        name="llm_functional_model_settings",
        statements=LLM_FUNCTIONAL_MODEL_SETTINGS_SCHEMA_STATEMENTS,
    ),
    Migration(
        version=9,
        name="llm_usage_records",
        statements=LLM_USAGE_SCHEMA_STATEMENTS,
    ),
    Migration(
        version=10,
        name="provider_custom_model_cache_hit_pricing",
        statements=(
            """
            ALTER TABLE provider_custom_models
            ADD COLUMN cache_hit_price_per_million REAL
            """,
        ),
    ),
    Migration(
        version=11,
        name="conversation_session_sequence_number",
        statements=(
            """
            ALTER TABLE llm_conversation_session_index
            ADD COLUMN sequence_number INTEGER NOT NULL DEFAULT 0
            """,
        ),
    ),
    Migration(
        version=12,
        name="core_data_integrity_constraints",
        statements=(
            AddColumnIfMissing(
                table_name="llm_usage_records",
                column_name="usage_feature_key",
                column_definition="TEXT NOT NULL DEFAULT 'main_chat'",
            ),
            """
            DELETE FROM provider_config_api_keys
            WHERE provider_id NOT IN (SELECT provider_id FROM provider_configs)
            """,
            """
            CREATE TABLE provider_config_api_keys_next (
                key_id TEXT PRIMARY KEY,
                provider_id TEXT NOT NULL,
                secret_ref TEXT NOT NULL,
                api_key_hint TEXT,
                poll_weight INTEGER NOT NULL,
                sort_order INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(provider_id) REFERENCES provider_configs(provider_id) ON DELETE CASCADE
            )
            """,
            """
            INSERT INTO provider_config_api_keys_next (
                key_id,
                provider_id,
                secret_ref,
                api_key_hint,
                poll_weight,
                sort_order,
                created_at,
                updated_at
            )
            SELECT
                key_id,
                provider_id,
                secret_ref,
                api_key_hint,
                poll_weight,
                sort_order,
                created_at,
                updated_at
            FROM provider_config_api_keys
            """,
            "DROP TABLE provider_config_api_keys",
            "ALTER TABLE provider_config_api_keys_next RENAME TO provider_config_api_keys",
            """
            CREATE INDEX IF NOT EXISTS idx_provider_config_api_keys_provider_id
            ON provider_config_api_keys(provider_id, sort_order)
            """,
            """
            DELETE FROM provider_cloud_model_items
            WHERE NOT EXISTS (
                SELECT 1
                FROM provider_cloud_model_caches cache
                WHERE cache.provider_id = provider_cloud_model_items.provider_id
                  AND cache.protocol_family = provider_cloud_model_items.protocol_family
                  AND cache.api_base_url = provider_cloud_model_items.api_base_url
            )
            """,
            """
            CREATE TABLE provider_cloud_model_items_next (
                provider_id TEXT NOT NULL,
                protocol_family TEXT NOT NULL,
                api_base_url TEXT NOT NULL,
                model_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                family_group TEXT NOT NULL,
                capability_tags TEXT NOT NULL,
                sort_order INTEGER NOT NULL,
                PRIMARY KEY (provider_id, protocol_family, api_base_url, model_id),
                FOREIGN KEY(provider_id, protocol_family, api_base_url)
                    REFERENCES provider_cloud_model_caches(provider_id, protocol_family, api_base_url)
                    ON DELETE CASCADE
            )
            """,
            """
            INSERT INTO provider_cloud_model_items_next (
                provider_id,
                protocol_family,
                api_base_url,
                model_id,
                display_name,
                family_group,
                capability_tags,
                sort_order
            )
            SELECT
                provider_id,
                protocol_family,
                api_base_url,
                model_id,
                display_name,
                family_group,
                capability_tags,
                sort_order
            FROM provider_cloud_model_items
            """,
            "DROP TABLE provider_cloud_model_items",
            "ALTER TABLE provider_cloud_model_items_next RENAME TO provider_cloud_model_items",
            """
            CREATE INDEX IF NOT EXISTS idx_provider_cloud_model_items_binding
            ON provider_cloud_model_items(provider_id, protocol_family, api_base_url, sort_order)
            """,
            """
            DELETE FROM llm_conversation_session_index
            WHERE project_id NOT IN (SELECT project_id FROM projects)
            """,
            """
            CREATE TABLE llm_conversation_session_index_next (
                project_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                title TEXT NOT NULL,
                provider_id TEXT,
                model_id TEXT,
                message_count INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                indexed_at TEXT NOT NULL,
                sequence_number INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (project_id, session_id),
                FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
            )
            """,
            """
            INSERT INTO llm_conversation_session_index_next (
                project_id,
                session_id,
                title,
                provider_id,
                model_id,
                message_count,
                created_at,
                updated_at,
                indexed_at,
                sequence_number
            )
            SELECT
                project_id,
                session_id,
                title,
                provider_id,
                model_id,
                message_count,
                created_at,
                updated_at,
                indexed_at,
                sequence_number
            FROM llm_conversation_session_index
            """,
            "DROP TABLE llm_conversation_session_index",
            "ALTER TABLE llm_conversation_session_index_next RENAME TO llm_conversation_session_index",
            """
            CREATE INDEX IF NOT EXISTS idx_llm_conversation_session_index_project
            ON llm_conversation_session_index(project_id, updated_at)
            """,
            """
            UPDATE llm_usage_records
            SET project_id = NULL,
                session_id = NULL
            WHERE project_id IS NOT NULL
              AND project_id NOT IN (SELECT project_id FROM projects)
            """,
            """
            UPDATE llm_usage_records
            SET project_id = NULL,
                session_id = NULL
            WHERE project_id IS NOT NULL
              AND session_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM llm_conversation_session_index session_index
                  WHERE session_index.project_id = llm_usage_records.project_id
                    AND session_index.session_id = llm_usage_records.session_id
              )
            """,
            """
            CREATE TABLE llm_usage_records_next (
                usage_id TEXT PRIMARY KEY,
                project_id TEXT,
                session_id TEXT,
                message_id TEXT,
                provider_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                usage_feature_key TEXT NOT NULL DEFAULT 'main_chat',
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                reasoning_tokens INTEGER NOT NULL DEFAULT 0,
                prompt_cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
                prompt_cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
                cost_amount REAL,
                cost_currency TEXT,
                is_estimated INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE SET NULL,
                FOREIGN KEY(project_id, session_id)
                    REFERENCES llm_conversation_session_index(project_id, session_id)
                    ON DELETE SET NULL
            )
            """,
            """
            INSERT INTO llm_usage_records_next (
                usage_id,
                project_id,
                session_id,
                message_id,
                provider_id,
                model_id,
                usage_feature_key,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                reasoning_tokens,
                prompt_cache_hit_tokens,
                prompt_cache_miss_tokens,
                cost_amount,
                cost_currency,
                is_estimated,
                created_at
            )
            SELECT
                usage_id,
                project_id,
                session_id,
                message_id,
                provider_id,
                model_id,
                COALESCE(usage_feature_key, 'main_chat'),
                prompt_tokens,
                completion_tokens,
                total_tokens,
                reasoning_tokens,
                prompt_cache_hit_tokens,
                prompt_cache_miss_tokens,
                cost_amount,
                cost_currency,
                is_estimated,
                created_at
            FROM llm_usage_records
            """,
            "DROP TABLE llm_usage_records",
            "ALTER TABLE llm_usage_records_next RENAME TO llm_usage_records",
            """
            CREATE INDEX IF NOT EXISTS idx_llm_usage_records_session
            ON llm_usage_records(project_id, session_id, created_at)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_llm_usage_records_provider_model
            ON llm_usage_records(provider_id, model_id, created_at)
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_llm_usage_records_message_unique
            ON llm_usage_records(message_id)
            WHERE message_id IS NOT NULL
            """,
        ),
    ),
    Migration(
        version=13,
        name="provider_api_key_sqlite_ciphertext",
        statements=(
            AddColumnIfMissing(
                table_name="provider_config_api_keys",
                column_name="api_key_ciphertext",
                column_definition="TEXT",
            ),
        ),
    ),
    Migration(
        version=14,
        name="remove_provider_api_key_secret_refs",
        statements=(
            AddColumnIfMissing(
                table_name="provider_config_api_keys",
                column_name="api_key_ciphertext",
                column_definition="TEXT",
            ),
            """
            CREATE TABLE provider_config_api_keys_next (
                key_id TEXT PRIMARY KEY,
                provider_id TEXT NOT NULL,
                api_key_hint TEXT,
                api_key_ciphertext TEXT,
                poll_weight INTEGER NOT NULL,
                sort_order INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(provider_id) REFERENCES provider_configs(provider_id) ON DELETE CASCADE
            )
            """,
            """
            INSERT INTO provider_config_api_keys_next (
                key_id,
                provider_id,
                api_key_hint,
                api_key_ciphertext,
                poll_weight,
                sort_order,
                created_at,
                updated_at
            )
            SELECT
                key_id,
                provider_id,
                api_key_hint,
                api_key_ciphertext,
                poll_weight,
                sort_order,
                created_at,
                updated_at
            FROM provider_config_api_keys
            """,
            "DROP TABLE provider_config_api_keys",
            "ALTER TABLE provider_config_api_keys_next RENAME TO provider_config_api_keys",
            """
            CREATE INDEX IF NOT EXISTS idx_provider_config_api_keys_provider_id
            ON provider_config_api_keys(provider_id, sort_order)
            """,
        ),
    ),
    Migration(
        version=15,
        name="llm_usage_feature_key",
        statements=(
            AddColumnIfMissing(
                table_name="llm_usage_records",
                column_name="usage_feature_key",
                column_definition="TEXT NOT NULL DEFAULT 'main_chat'",
            ),
            """
            UPDATE llm_usage_records
            SET usage_feature_key = 'conversation_naming'
            WHERE message_id LIKE 'system:naming:%'
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_llm_usage_records_session_feature
            ON llm_usage_records(project_id, session_id, provider_id, model_id, usage_feature_key, created_at)
            """,
        ),
    ),
    Migration(
        version=16,
        name="schema_column_contract_checks",
        statements=(
            AddColumnIfMissing(
                table_name="provider_config_api_keys",
                column_name="api_key_ciphertext",
                column_definition="TEXT",
            ),
            AddColumnIfMissing(
                table_name="llm_usage_records",
                column_name="usage_feature_key",
                column_definition="TEXT NOT NULL DEFAULT 'main_chat'",
            ),
            """
            CREATE INDEX IF NOT EXISTS idx_llm_usage_records_session_feature
            ON llm_usage_records(project_id, session_id, provider_id, model_id, usage_feature_key, created_at)
            """,
        ),
    ),
    Migration(
        version=17,
        name="llm_usage_memory_compression_feature_key",
        statements=(
            AddColumnIfMissing(
                table_name="llm_usage_records",
                column_name="usage_feature_key",
                column_definition="TEXT NOT NULL DEFAULT 'main_chat'",
            ),
            """
            UPDATE llm_usage_records
            SET usage_feature_key = 'memory_compression'
            WHERE message_id LIKE 'system:memory_compression:%'
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_llm_usage_records_session_feature
            ON llm_usage_records(project_id, session_id, provider_id, model_id, usage_feature_key, created_at)
            """,
        ),
    ),
    Migration(
        version=18,
        name="project_categories",
        statements=PROJECT_CATEGORY_SCHEMA_STATEMENTS,
    ),
    Migration(
        version=19,
        name="project_root_path_guard",
        statements=PROJECT_ROOT_PATH_GUARD_SCHEMA_STATEMENTS,
    ),
    Migration(
        version=25,
        name="drop_tool_registry_cache",
        statements=(
            "DROP INDEX IF EXISTS idx_tool_registry_tool_name",
            "DROP INDEX IF EXISTS idx_tool_registry_enabled_name",
            "DROP INDEX IF EXISTS idx_tool_registry_search",
            "DROP TABLE IF EXISTS tool_registry",
        ),
    ),
    Migration(
        version=26,
        name="workspace_activity_records",
        statements=(
            *WORKSPACE_ACTIVITY_SCHEMA_STATEMENTS,
            """
            INSERT OR IGNORE INTO workspace_activity_records (
                activity_type,
                source_id,
                amount,
                occurred_at
            )
            SELECT
                'conversation_created',
                session_id,
                1,
                created_at
            FROM llm_conversation_session_index
            """,
        ),
    ),
    Migration(
        version=27,
        name="workspace_activity_baselines",
        statements=WORKSPACE_ACTIVITY_BASELINE_SCHEMA_STATEMENTS,
    ),
    Migration(
        version=28,
        name="move_provider_storage_to_files",
        statements=(
            "DROP INDEX IF EXISTS idx_provider_config_api_keys_provider_id",
            "DROP INDEX IF EXISTS idx_provider_cloud_model_items_binding",
            "DROP INDEX IF EXISTS idx_provider_custom_models_provider_id",
            "DROP INDEX IF EXISTS idx_provider_catalog_order_sort_order",
            "DROP TABLE IF EXISTS provider_config_api_keys",
            "DROP TABLE IF EXISTS provider_cloud_model_items",
            "DROP TABLE IF EXISTS provider_cloud_model_caches",
            "DROP TABLE IF EXISTS provider_custom_models",
            "DROP TABLE IF EXISTS provider_catalog_order",
            "DROP TABLE IF EXISTS custom_provider_catalog",
            "DROP TABLE IF EXISTS provider_configs",
        ),
    ),
    Migration(
        version=29,
        name="llm_token_estimation_settings",
        statements=LLM_TOKEN_ESTIMATION_SETTINGS_SCHEMA_STATEMENTS,
    ),
    Migration(
        version=30,
        name="project_kind",
        statements=(
            AddColumnIfMissing(
                table_name="projects",
                column_name="project_kind",
                column_definition=(
                    "TEXT NOT NULL DEFAULT 'standard' "
                    "CHECK (project_kind IN ('standard', 'role', 'theme'))"
                ),
            ),
            """
            UPDATE projects
            SET project_kind = 'standard'
            WHERE project_kind IS NULL OR trim(project_kind) = ''
            """,
        ),
    ),
    Migration(
        version=31,
        name="project_category_kind_and_builtin_role_set",
        statements=(
            AddColumnIfMissing(
                table_name="project_categories",
                column_name="category_kind",
                column_definition=(
                    "TEXT NOT NULL DEFAULT 'standard' "
                    "CHECK (category_kind IN ('standard', 'role', 'theme'))"
                ),
            ),
            """
            UPDATE project_categories
            SET category_kind = 'standard'
            WHERE category_kind IS NULL OR trim(category_kind) = ''
            """,
            "DROP INDEX IF EXISTS idx_project_categories_name_unique",
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_project_categories_kind_name_unique
            ON project_categories(category_kind, name COLLATE NOCASE)
            """,
            """
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
                updated_at = CURRENT_TIMESTAMP
            """,
        ),
    ),
    Migration(
        version=32,
        name="project_category_kind_integrity",
        statements=(
            """
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
            END
            """,
            """
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
            END
            """,
            """
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
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_role_project_category_update
            BEFORE UPDATE OF category_id, name, category_kind, is_default
            ON project_categories
            WHEN OLD.category_id = 'role-set'
            BEGIN
                SELECT RAISE(ABORT, 'builtin_role_category_readonly');
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_role_project_category_delete
            BEFORE DELETE ON project_categories
            WHEN OLD.category_id = 'role-set'
            BEGIN
                SELECT RAISE(ABORT, 'builtin_role_category_readonly');
            END
            """,
        ),
    ),
    Migration(
        version=33,
        name="role_project_categories",
        statements=(
            "DROP TRIGGER IF EXISTS trg_role_project_category_update",
            "DROP TRIGGER IF EXISTS trg_role_project_category_delete",
            "DROP INDEX IF EXISTS idx_project_categories_default_singleton",
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_project_categories_kind_default_singleton
            ON project_categories(category_kind)
            WHERE is_default = 1
            """,
            """
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
                updated_at = CURRENT_TIMESTAMP
            """,
            """
            UPDATE projects
            SET category_id = 'default-role-category',
                updated_at = CURRENT_TIMESTAMP
            WHERE category_id = 'role-set'
              AND project_kind = 'role'
            """,
            """
            DELETE FROM project_categories
            WHERE category_id = 'role-set'
            """,
        ),
    ),
    Migration(
        version=34,
        name="remove_legacy_fixed_role_category",
        statements=(
            """
            UPDATE projects
            SET category_id = 'default-role-category',
                updated_at = CURRENT_TIMESTAMP
            WHERE category_id = 'role-set'
              AND project_kind = 'role'
            """,
            """
            DELETE FROM project_categories
            WHERE category_id = 'role-set'
            """,
        ),
    ),
    Migration(
        version=35,
        name="remove_recreated_legacy_role_category",
        statements=(
            """
            UPDATE projects
            SET category_id = 'default-role-category',
                updated_at = CURRENT_TIMESTAMP
            WHERE category_id = 'role-set'
              AND project_kind = 'role'
            """,
            """
            DELETE FROM project_categories
            WHERE category_id = 'role-set'
            """,
        ),
    ),
    Migration(
        version=36,
        name="prevent_legacy_role_category_recreation",
        statements=(
            """
            UPDATE projects
            SET category_id = 'default-role-category',
                updated_at = CURRENT_TIMESTAMP
            WHERE category_id = 'role-set'
              AND project_kind = 'role'
            """,
            """
            DELETE FROM project_categories
            WHERE category_id = 'role-set'
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_reject_legacy_role_category_insert
            BEFORE INSERT ON project_categories
            WHEN NEW.category_id = 'role-set'
            BEGIN
                SELECT RAISE(ABORT, 'legacy_role_category_removed');
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_reject_legacy_role_category_id_update
            BEFORE UPDATE OF category_id ON project_categories
            WHEN NEW.category_id = 'role-set'
            BEGIN
                SELECT RAISE(ABORT, 'legacy_role_category_removed');
            END
            """,
        ),
    ),
    Migration(
        version=37,
        name="rename_default_role_category",
        statements=(
            """
            UPDATE project_categories
            SET name = '基础角色',
                updated_at = CURRENT_TIMESTAMP
            WHERE category_id = 'default-role-category'
              AND category_kind = 'role'
            """,
        ),
    ),
    Migration(
        version=38,
        name="theme_project_kind",
        foreign_keys_disabled=True,
        statements=(
            "DROP TRIGGER IF EXISTS trg_projects_category_kind_insert",
            "DROP TRIGGER IF EXISTS trg_projects_category_kind_update",
            "DROP TRIGGER IF EXISTS trg_project_categories_kind_update",
            "DROP TRIGGER IF EXISTS trg_projects_root_path_unique_insert",
            "DROP TRIGGER IF EXISTS trg_projects_root_path_unique_update",
            "DROP TRIGGER IF EXISTS trg_reject_legacy_role_category_insert",
            "DROP TRIGGER IF EXISTS trg_reject_legacy_role_category_id_update",
            "DROP INDEX IF EXISTS idx_projects_default_singleton",
            "DROP INDEX IF EXISTS idx_projects_sort_order",
            "DROP INDEX IF EXISTS idx_projects_category_order",
            "DROP INDEX IF EXISTS idx_project_categories_kind_default_singleton",
            "DROP INDEX IF EXISTS idx_project_categories_kind_name_unique",
            "DROP INDEX IF EXISTS idx_project_categories_sort_order",
            """
            CREATE TABLE project_categories_next (
                category_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                is_default INTEGER NOT NULL,
                sort_order INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                category_kind TEXT NOT NULL DEFAULT 'standard'
                    CHECK (category_kind IN ('standard', 'role', 'theme'))
            )
            """,
            """
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
            FROM project_categories
            """,
            """
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
            )
            """,
            """
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
            FROM projects
            """,
            "DROP TABLE projects",
            "DROP TABLE project_categories",
            "ALTER TABLE project_categories_next RENAME TO project_categories",
            "ALTER TABLE projects_next RENAME TO projects",
            """
            CREATE UNIQUE INDEX idx_projects_default_singleton
            ON projects(is_default)
            WHERE is_default = 1
            """,
            """
            CREATE INDEX idx_projects_sort_order
            ON projects(sort_order, created_at)
            """,
            """
            CREATE INDEX idx_projects_category_order
            ON projects(category_id, sort_order, created_at)
            """,
            """
            CREATE UNIQUE INDEX idx_project_categories_kind_default_singleton
            ON project_categories(category_kind)
            WHERE is_default = 1
            """,
            """
            CREATE UNIQUE INDEX idx_project_categories_kind_name_unique
            ON project_categories(category_kind, name COLLATE NOCASE)
            """,
            """
            CREATE INDEX idx_project_categories_sort_order
            ON project_categories(sort_order, created_at)
            """,
            """
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
            END
            """,
            """
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
            END
            """,
            """
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
            END
            """,
            """
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
            END
            """,
            """
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
            END
            """,
            """
            CREATE TRIGGER trg_reject_legacy_role_category_insert
            BEFORE INSERT ON project_categories
            WHEN NEW.category_id = 'role-set'
            BEGIN
                SELECT RAISE(ABORT, 'legacy_role_category_removed');
            END
            """,
            """
            CREATE TRIGGER trg_reject_legacy_role_category_id_update
            BEFORE UPDATE OF category_id ON project_categories
            WHEN NEW.category_id = 'role-set'
            BEGIN
                SELECT RAISE(ABORT, 'legacy_role_category_removed');
            END
            """,
        ),
    ),
    Migration(
        version=39,
        name="tool_project_kind",
        foreign_keys_disabled=True,
        statements=(
            "DROP TRIGGER IF EXISTS trg_projects_category_kind_insert",
            "DROP TRIGGER IF EXISTS trg_projects_category_kind_update",
            "DROP TRIGGER IF EXISTS trg_project_categories_kind_update",
            "DROP TRIGGER IF EXISTS trg_projects_root_path_unique_insert",
            "DROP TRIGGER IF EXISTS trg_projects_root_path_unique_update",
            "DROP TRIGGER IF EXISTS trg_reject_legacy_role_category_insert",
            "DROP TRIGGER IF EXISTS trg_reject_legacy_role_category_id_update",
            "DROP INDEX IF EXISTS idx_projects_default_singleton",
            "DROP INDEX IF EXISTS idx_projects_sort_order",
            "DROP INDEX IF EXISTS idx_projects_category_order",
            "DROP INDEX IF EXISTS idx_project_categories_kind_default_singleton",
            "DROP INDEX IF EXISTS idx_project_categories_kind_name_unique",
            "DROP INDEX IF EXISTS idx_project_categories_sort_order",
            """
            CREATE TABLE project_categories_next (
                category_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                is_default INTEGER NOT NULL,
                sort_order INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                category_kind TEXT NOT NULL DEFAULT 'standard'
                    CHECK (category_kind IN ('standard', 'role', 'theme', 'tool'))
            )
            """,
            """
            INSERT INTO project_categories_next (
                category_id, name, is_default, sort_order,
                created_at, updated_at, category_kind
            )
            SELECT
                category_id, name, is_default, sort_order,
                created_at, updated_at, category_kind
            FROM project_categories
            """,
            """
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
                    CHECK (project_kind IN ('standard', 'role', 'theme', 'tool'))
            )
            """,
            """
            INSERT INTO projects_next (
                project_id, name, root_path, category_id, is_default,
                sort_order, created_at, updated_at, project_kind
            )
            SELECT
                project_id, name, root_path, category_id, is_default,
                sort_order, created_at, updated_at, project_kind
            FROM projects
            """,
            "DROP TABLE projects",
            "DROP TABLE project_categories",
            "ALTER TABLE project_categories_next RENAME TO project_categories",
            "ALTER TABLE projects_next RENAME TO projects",
            """
            CREATE UNIQUE INDEX idx_projects_default_singleton
            ON projects(is_default)
            WHERE is_default = 1
            """,
            """
            CREATE INDEX idx_projects_sort_order
            ON projects(sort_order, created_at)
            """,
            """
            CREATE INDEX idx_projects_category_order
            ON projects(category_id, sort_order, created_at)
            """,
            """
            CREATE UNIQUE INDEX idx_project_categories_kind_default_singleton
            ON project_categories(category_kind)
            WHERE is_default = 1
            """,
            """
            CREATE UNIQUE INDEX idx_project_categories_kind_name_unique
            ON project_categories(category_kind, name COLLATE NOCASE)
            """,
            """
            CREATE INDEX idx_project_categories_sort_order
            ON project_categories(sort_order, created_at)
            """,
            """
            CREATE TRIGGER trg_projects_root_path_unique_insert
            BEFORE INSERT ON projects
            WHEN EXISTS (
                SELECT 1 FROM projects
                WHERE root_path = NEW.root_path
                  AND project_id <> NEW.project_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_root_path_duplicate');
            END
            """,
            """
            CREATE TRIGGER trg_projects_root_path_unique_update
            BEFORE UPDATE OF root_path ON projects
            WHEN EXISTS (
                SELECT 1 FROM projects
                WHERE root_path = NEW.root_path
                  AND project_id <> OLD.project_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_root_path_duplicate');
            END
            """,
            """
            CREATE TRIGGER trg_projects_category_kind_insert
            BEFORE INSERT ON projects
            WHEN NOT EXISTS (
                SELECT 1 FROM project_categories
                WHERE category_id = NEW.category_id
                  AND category_kind = NEW.project_kind
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_category_kind_mismatch');
            END
            """,
            """
            CREATE TRIGGER trg_projects_category_kind_update
            BEFORE UPDATE OF category_id, project_kind ON projects
            WHEN NOT EXISTS (
                SELECT 1 FROM project_categories
                WHERE category_id = NEW.category_id
                  AND category_kind = NEW.project_kind
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_category_kind_mismatch');
            END
            """,
            """
            CREATE TRIGGER trg_project_categories_kind_update
            BEFORE UPDATE OF category_kind ON project_categories
            WHEN EXISTS (
                SELECT 1 FROM projects
                WHERE category_id = OLD.category_id
                  AND project_kind <> NEW.category_kind
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_category_kind_mismatch');
            END
            """,
            """
            CREATE TRIGGER trg_reject_legacy_role_category_insert
            BEFORE INSERT ON project_categories
            WHEN NEW.category_id = 'role-set'
            BEGIN
                SELECT RAISE(ABORT, 'legacy_role_category_removed');
            END
            """,
            """
            CREATE TRIGGER trg_reject_legacy_role_category_id_update
            BEFORE UPDATE OF category_id ON project_categories
            WHEN NEW.category_id = 'role-set'
            BEGIN
                SELECT RAISE(ABORT, 'legacy_role_category_removed');
            END
            """,
        ),
    ),
    Migration(
        version=40,
        name="network_settings",
        statements=(
            """
            CREATE TABLE network_settings (
                settings_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                settings_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
        ),
    ),
    Migration(
        version=41,
        name="literature_and_experience_project_kinds",
        foreign_keys_disabled=True,
        statements=(
            """
            CREATE TABLE project_categories_next (
                category_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                is_default INTEGER NOT NULL,
                sort_order INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                category_kind TEXT NOT NULL DEFAULT 'standard'
                    CHECK (category_kind IN (
                        'standard', 'literature', 'experience', 'role', 'theme', 'tool'
                    ))
            )
            """,
            """
            INSERT INTO project_categories_next (
                category_id, name, is_default, sort_order,
                created_at, updated_at, category_kind
            )
            SELECT
                category_id, name, is_default, sort_order,
                created_at, updated_at, category_kind
            FROM project_categories
            """,
            """
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
                    CHECK (project_kind IN (
                        'standard', 'literature', 'experience', 'role', 'theme', 'tool'
                    ))
            )
            """,
            """
            INSERT INTO projects_next (
                project_id, name, root_path, category_id, is_default,
                sort_order, created_at, updated_at, project_kind
            )
            SELECT
                project_id, name, root_path, category_id, is_default,
                sort_order, created_at, updated_at, project_kind
            FROM projects
            """,
            "DROP TABLE projects",
            "DROP TABLE project_categories",
            "ALTER TABLE project_categories_next RENAME TO project_categories",
            "ALTER TABLE projects_next RENAME TO projects",
            """
            CREATE UNIQUE INDEX idx_projects_default_singleton
            ON projects(is_default)
            WHERE is_default = 1
            """,
            """
            CREATE INDEX idx_projects_sort_order
            ON projects(sort_order, created_at)
            """,
            """
            CREATE INDEX idx_projects_category_order
            ON projects(category_id, sort_order, created_at)
            """,
            """
            CREATE UNIQUE INDEX idx_project_categories_kind_default_singleton
            ON project_categories(category_kind)
            WHERE is_default = 1
            """,
            """
            CREATE UNIQUE INDEX idx_project_categories_kind_name_unique
            ON project_categories(category_kind, name COLLATE NOCASE)
            """,
            """
            CREATE INDEX idx_project_categories_sort_order
            ON project_categories(sort_order, created_at)
            """,
            """
            CREATE TRIGGER trg_projects_root_path_unique_insert
            BEFORE INSERT ON projects
            WHEN EXISTS (
                SELECT 1 FROM projects
                WHERE root_path = NEW.root_path
                  AND project_id <> NEW.project_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_root_path_duplicate');
            END
            """,
            """
            CREATE TRIGGER trg_projects_root_path_unique_update
            BEFORE UPDATE OF root_path ON projects
            WHEN EXISTS (
                SELECT 1 FROM projects
                WHERE root_path = NEW.root_path
                  AND project_id <> OLD.project_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_root_path_duplicate');
            END
            """,
            """
            CREATE TRIGGER trg_projects_category_kind_insert
            BEFORE INSERT ON projects
            WHEN NOT EXISTS (
                SELECT 1 FROM project_categories
                WHERE category_id = NEW.category_id
                  AND category_kind = NEW.project_kind
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_category_kind_mismatch');
            END
            """,
            """
            CREATE TRIGGER trg_projects_category_kind_update
            BEFORE UPDATE OF category_id, project_kind ON projects
            WHEN NOT EXISTS (
                SELECT 1 FROM project_categories
                WHERE category_id = NEW.category_id
                  AND category_kind = NEW.project_kind
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_category_kind_mismatch');
            END
            """,
            """
            CREATE TRIGGER trg_project_categories_kind_update
            BEFORE UPDATE OF category_kind ON project_categories
            WHEN EXISTS (
                SELECT 1 FROM projects
                WHERE category_id = OLD.category_id
                  AND project_kind <> NEW.category_kind
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_category_kind_mismatch');
            END
            """,
            """
            CREATE TRIGGER trg_reject_legacy_role_category_insert
            BEFORE INSERT ON project_categories
            WHEN NEW.category_id = 'role-set'
            BEGIN
                SELECT RAISE(ABORT, 'legacy_role_category_removed');
            END
            """,
            """
            CREATE TRIGGER trg_reject_legacy_role_category_id_update
            BEFORE UPDATE OF category_id ON project_categories
            WHEN NEW.category_id = 'role-set'
            BEGIN
                SELECT RAISE(ABORT, 'legacy_role_category_removed');
            END
            """,
        ),
    ),
    Migration(
        version=42,
        name="provider_project_kind",
        foreign_keys_disabled=True,
        statements=(
            """
            CREATE TABLE project_categories_next (
                category_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                is_default INTEGER NOT NULL,
                sort_order INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                category_kind TEXT NOT NULL DEFAULT 'standard'
                    CHECK (category_kind IN (
                        'standard', 'literature', 'experience', 'role', 'theme', 'tool',
                        'provider'
                    ))
            )
            """,
            """
            INSERT INTO project_categories_next (
                category_id, name, is_default, sort_order,
                created_at, updated_at, category_kind
            )
            SELECT
                category_id, name, is_default, sort_order,
                created_at, updated_at, category_kind
            FROM project_categories
            """,
            """
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
                    CHECK (project_kind IN (
                        'standard', 'literature', 'experience', 'role', 'theme', 'tool',
                        'provider'
                    ))
            )
            """,
            """
            INSERT INTO projects_next (
                project_id, name, root_path, category_id, is_default,
                sort_order, created_at, updated_at, project_kind
            )
            SELECT
                project_id, name, root_path, category_id, is_default,
                sort_order, created_at, updated_at, project_kind
            FROM projects
            """,
            "DROP TABLE projects",
            "DROP TABLE project_categories",
            "ALTER TABLE project_categories_next RENAME TO project_categories",
            "ALTER TABLE projects_next RENAME TO projects",
            """
            CREATE UNIQUE INDEX idx_projects_default_singleton
            ON projects(is_default)
            WHERE is_default = 1
            """,
            """
            CREATE INDEX idx_projects_sort_order
            ON projects(sort_order, created_at)
            """,
            """
            CREATE INDEX idx_projects_category_order
            ON projects(category_id, sort_order, created_at)
            """,
            """
            CREATE UNIQUE INDEX idx_project_categories_kind_default_singleton
            ON project_categories(category_kind)
            WHERE is_default = 1
            """,
            """
            CREATE UNIQUE INDEX idx_project_categories_kind_name_unique
            ON project_categories(category_kind, name COLLATE NOCASE)
            """,
            """
            CREATE INDEX idx_project_categories_sort_order
            ON project_categories(sort_order, created_at)
            """,
            """
            CREATE TRIGGER trg_projects_root_path_unique_insert
            BEFORE INSERT ON projects
            WHEN EXISTS (
                SELECT 1 FROM projects
                WHERE root_path = NEW.root_path
                  AND project_id <> NEW.project_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_root_path_duplicate');
            END
            """,
            """
            CREATE TRIGGER trg_projects_root_path_unique_update
            BEFORE UPDATE OF root_path ON projects
            WHEN EXISTS (
                SELECT 1 FROM projects
                WHERE root_path = NEW.root_path
                  AND project_id <> OLD.project_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_root_path_duplicate');
            END
            """,
            """
            CREATE TRIGGER trg_projects_category_kind_insert
            BEFORE INSERT ON projects
            WHEN NOT EXISTS (
                SELECT 1 FROM project_categories
                WHERE category_id = NEW.category_id
                  AND category_kind = NEW.project_kind
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_category_kind_mismatch');
            END
            """,
            """
            CREATE TRIGGER trg_projects_category_kind_update
            BEFORE UPDATE OF category_id, project_kind ON projects
            WHEN NOT EXISTS (
                SELECT 1 FROM project_categories
                WHERE category_id = NEW.category_id
                  AND category_kind = NEW.project_kind
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_category_kind_mismatch');
            END
            """,
            """
            CREATE TRIGGER trg_project_categories_kind_update
            BEFORE UPDATE OF category_kind ON project_categories
            WHEN EXISTS (
                SELECT 1 FROM projects
                WHERE category_id = OLD.category_id
                  AND project_kind <> NEW.category_kind
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_category_kind_mismatch');
            END
            """,
            """
            CREATE TRIGGER trg_reject_legacy_role_category_insert
            BEFORE INSERT ON project_categories
            WHEN NEW.category_id = 'role-set'
            BEGIN
                SELECT RAISE(ABORT, 'legacy_role_category_removed');
            END
            """,
            """
            CREATE TRIGGER trg_reject_legacy_role_category_id_update
            BEFORE UPDATE OF category_id ON project_categories
            WHEN NEW.category_id = 'role-set'
            BEGIN
                SELECT RAISE(ABORT, 'legacy_role_category_removed');
            END
            """,
        ),
    ),
    Migration(
        version=43,
        name="decouple_usage_index_from_project_catalog",
        foreign_keys_disabled=True,
        statements=(
            """
            CREATE TABLE llm_conversation_session_index_next (
                project_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                title TEXT NOT NULL,
                provider_id TEXT,
                model_id TEXT,
                message_count INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                indexed_at TEXT NOT NULL,
                sequence_number INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (project_id, session_id)
            )
            """,
            """
            INSERT INTO llm_conversation_session_index_next (
                project_id, session_id, title, provider_id, model_id,
                message_count, created_at, updated_at, indexed_at, sequence_number
            )
            SELECT
                project_id, session_id, title, provider_id, model_id,
                message_count, created_at, updated_at, indexed_at, sequence_number
            FROM llm_conversation_session_index
            """,
            "DROP TABLE llm_conversation_session_index",
            "ALTER TABLE llm_conversation_session_index_next RENAME TO llm_conversation_session_index",
            """
            CREATE INDEX idx_llm_conversation_session_index_project
            ON llm_conversation_session_index(project_id, updated_at)
            """,
            """
            CREATE TABLE llm_usage_records_next (
                usage_id TEXT PRIMARY KEY,
                project_id TEXT,
                session_id TEXT,
                message_id TEXT,
                provider_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                usage_feature_key TEXT NOT NULL DEFAULT 'main_chat',
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                reasoning_tokens INTEGER NOT NULL DEFAULT 0,
                prompt_cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
                prompt_cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
                cost_amount REAL,
                cost_currency TEXT,
                is_estimated INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id, session_id)
                    REFERENCES llm_conversation_session_index(project_id, session_id)
                    ON DELETE SET NULL
            )
            """,
            """
            INSERT INTO llm_usage_records_next (
                usage_id, project_id, session_id, message_id,
                provider_id, model_id, usage_feature_key,
                prompt_tokens, completion_tokens, total_tokens, reasoning_tokens,
                prompt_cache_hit_tokens, prompt_cache_miss_tokens,
                cost_amount, cost_currency, is_estimated, created_at
            )
            SELECT
                usage_id, project_id, session_id, message_id,
                provider_id, model_id, usage_feature_key,
                prompt_tokens, completion_tokens, total_tokens, reasoning_tokens,
                prompt_cache_hit_tokens, prompt_cache_miss_tokens,
                cost_amount, cost_currency, is_estimated, created_at
            FROM llm_usage_records
            """,
            "DROP TABLE llm_usage_records",
            "ALTER TABLE llm_usage_records_next RENAME TO llm_usage_records",
            """
            CREATE INDEX idx_llm_usage_records_session
            ON llm_usage_records(project_id, session_id, created_at)
            """,
            """
            CREATE INDEX idx_llm_usage_records_provider_model
            ON llm_usage_records(provider_id, model_id, created_at)
            """,
            """
            CREATE INDEX idx_llm_usage_records_session_feature
            ON llm_usage_records(
                project_id, session_id, provider_id, model_id,
                usage_feature_key, created_at
            )
            """,
            """
            CREATE UNIQUE INDEX idx_llm_usage_records_message_unique
            ON llm_usage_records(message_id)
            WHERE message_id IS NOT NULL
            """,
        ),
    ),
    Migration(
        version=44,
        name="remove_database_tool_call_records",
        statements=(
            "DROP INDEX IF EXISTS idx_tool_call_records_folder_created",
            "DROP INDEX IF EXISTS idx_tool_call_records_tool_created",
            "DROP INDEX IF EXISTS idx_tool_call_records_session",
            "DROP TABLE IF EXISTS tool_call_records",
        ),
    ),
    Migration(
        version=45,
        name="remove_legacy_active_theme_metadata",
        statements=(
            *APP_METADATA_SCHEMA_STATEMENTS,
            "DELETE FROM app_metadata WHERE key = 'theme.active_theme_id'",
        ),
    ),
    Migration(
        version=46,
        name="move_llm_usage_to_file_storage",
        statements=(
            "DROP TABLE IF EXISTS llm_usage_records",
            "DROP TABLE IF EXISTS llm_conversation_session_index",
        ),
    ),
    Migration(
        version=47,
        name="rename_standard_project_kind_to_project",
        foreign_keys_disabled=True,
        statements=(
            """
            CREATE TABLE project_categories_next (
                category_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                is_default INTEGER NOT NULL,
                sort_order INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                category_kind TEXT NOT NULL DEFAULT 'project'
                    CHECK (category_kind IN (
                        'project', 'literature', 'experience', 'role', 'theme', 'tool',
                        'provider'
                    ))
            )
            """,
            """
            INSERT INTO project_categories_next (
                category_id, name, is_default, sort_order,
                created_at, updated_at, category_kind
            )
            SELECT
                category_id, name, is_default, sort_order,
                created_at, updated_at,
                CASE WHEN category_kind = 'standard' THEN 'project' ELSE category_kind END
            FROM project_categories
            """,
            """
            CREATE TABLE projects_next (
                project_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                root_path TEXT NOT NULL,
                category_id TEXT NOT NULL DEFAULT 'daily-project',
                is_default INTEGER NOT NULL,
                sort_order INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                project_kind TEXT NOT NULL DEFAULT 'project'
                    CHECK (project_kind IN (
                        'project', 'literature', 'experience', 'role', 'theme', 'tool',
                        'provider'
                    ))
            )
            """,
            """
            INSERT INTO projects_next (
                project_id, name, root_path, category_id, is_default,
                sort_order, created_at, updated_at, project_kind
            )
            SELECT
                project_id, name, root_path, category_id, is_default,
                sort_order, created_at, updated_at,
                CASE WHEN project_kind = 'standard' THEN 'project' ELSE project_kind END
            FROM projects
            """,
            "DROP TABLE projects",
            "DROP TABLE project_categories",
            "ALTER TABLE project_categories_next RENAME TO project_categories",
            "ALTER TABLE projects_next RENAME TO projects",
            """
            CREATE UNIQUE INDEX idx_projects_default_singleton
            ON projects(is_default)
            WHERE is_default = 1
            """,
            """
            CREATE INDEX idx_projects_sort_order
            ON projects(sort_order, created_at)
            """,
            """
            CREATE INDEX idx_projects_category_order
            ON projects(category_id, sort_order, created_at)
            """,
            """
            CREATE UNIQUE INDEX idx_project_categories_kind_default_singleton
            ON project_categories(category_kind)
            WHERE is_default = 1
            """,
            """
            CREATE UNIQUE INDEX idx_project_categories_kind_name_unique
            ON project_categories(category_kind, name COLLATE NOCASE)
            """,
            """
            CREATE INDEX idx_project_categories_sort_order
            ON project_categories(sort_order, created_at)
            """,
            """
            CREATE TRIGGER trg_projects_root_path_unique_insert
            BEFORE INSERT ON projects
            WHEN EXISTS (
                SELECT 1 FROM projects
                WHERE root_path = NEW.root_path
                  AND project_id <> NEW.project_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_root_path_duplicate');
            END
            """,
            """
            CREATE TRIGGER trg_projects_root_path_unique_update
            BEFORE UPDATE OF root_path ON projects
            WHEN EXISTS (
                SELECT 1 FROM projects
                WHERE root_path = NEW.root_path
                  AND project_id <> OLD.project_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_root_path_duplicate');
            END
            """,
            """
            CREATE TRIGGER trg_projects_category_kind_insert
            BEFORE INSERT ON projects
            WHEN NOT EXISTS (
                SELECT 1 FROM project_categories
                WHERE category_id = NEW.category_id
                  AND category_kind = NEW.project_kind
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_category_kind_mismatch');
            END
            """,
            """
            CREATE TRIGGER trg_projects_category_kind_update
            BEFORE UPDATE OF category_id, project_kind ON projects
            WHEN NOT EXISTS (
                SELECT 1 FROM project_categories
                WHERE category_id = NEW.category_id
                  AND category_kind = NEW.project_kind
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_category_kind_mismatch');
            END
            """,
            """
            CREATE TRIGGER trg_project_categories_kind_update
            BEFORE UPDATE OF category_kind ON project_categories
            WHEN EXISTS (
                SELECT 1 FROM projects
                WHERE category_id = OLD.category_id
                  AND project_kind <> NEW.category_kind
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_category_kind_mismatch');
            END
            """,
            """
            CREATE TRIGGER trg_reject_legacy_role_category_insert
            BEFORE INSERT ON project_categories
            WHEN NEW.category_id = 'role-set'
            BEGIN
                SELECT RAISE(ABORT, 'legacy_role_category_removed');
            END
            """,
            """
            CREATE TRIGGER trg_reject_legacy_role_category_id_update
            BEFORE UPDATE OF category_id ON project_categories
            WHEN NEW.category_id = 'role-set'
            BEGIN
                SELECT RAISE(ABORT, 'legacy_role_category_removed');
            END
            """,
        ),
    ),
    Migration(
        version=48,
        name="rename_literature_project_kind_to_knowledge",
        foreign_keys_disabled=True,
        statements=(
            """
            CREATE TABLE project_categories_next (
                category_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                is_default INTEGER NOT NULL,
                sort_order INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                category_kind TEXT NOT NULL DEFAULT 'project'
                    CHECK (category_kind IN (
                        'project', 'knowledge', 'experience', 'role', 'theme', 'tool',
                        'provider'
                    ))
            )
            """,
            """
            INSERT INTO project_categories_next (
                category_id, name, is_default, sort_order,
                created_at, updated_at, category_kind
            )
            SELECT
                CASE
                    WHEN category_id = 'default-literature-category'
                    THEN 'default-knowledge-category'
                    ELSE category_id
                END,
                CASE
                    WHEN category_id = 'default-literature-category'
                         AND name = '基础文献'
                    THEN '基础知识'
                    ELSE name
                END,
                is_default,
                sort_order,
                created_at,
                updated_at,
                CASE WHEN category_kind = 'literature' THEN 'knowledge' ELSE category_kind END
            FROM project_categories
            """,
            """
            CREATE TABLE projects_next (
                project_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                root_path TEXT NOT NULL,
                category_id TEXT NOT NULL DEFAULT 'daily-project',
                is_default INTEGER NOT NULL,
                sort_order INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                project_kind TEXT NOT NULL DEFAULT 'project'
                    CHECK (project_kind IN (
                        'project', 'knowledge', 'experience', 'role', 'theme', 'tool',
                        'provider'
                    ))
            )
            """,
            """
            INSERT INTO projects_next (
                project_id, name, root_path, category_id, is_default,
                sort_order, created_at, updated_at, project_kind
            )
            SELECT
                project_id,
                CASE
                    WHEN name = '新建文献' OR name GLOB '新建文献 [0-9]*'
                    THEN '新建知识' || substr(name, length('新建文献') + 1)
                    ELSE name
                END,
                replace(
                    replace(
                        root_path,
                        char(92) || 'literature' || char(92),
                        char(92) || 'knowledge' || char(92)
                    ),
                    '/literature/',
                    '/knowledge/'
                ),
                CASE
                    WHEN category_id = 'default-literature-category'
                    THEN 'default-knowledge-category'
                    ELSE category_id
                END,
                is_default,
                sort_order,
                created_at,
                updated_at,
                CASE WHEN project_kind = 'literature' THEN 'knowledge' ELSE project_kind END
            FROM projects
            """,
            "DROP TABLE projects",
            "DROP TABLE project_categories",
            "ALTER TABLE project_categories_next RENAME TO project_categories",
            "ALTER TABLE projects_next RENAME TO projects",
            """
            CREATE UNIQUE INDEX idx_projects_default_singleton
            ON projects(is_default)
            WHERE is_default = 1
            """,
            """
            CREATE INDEX idx_projects_sort_order
            ON projects(sort_order, created_at)
            """,
            """
            CREATE INDEX idx_projects_category_order
            ON projects(category_id, sort_order, created_at)
            """,
            """
            CREATE UNIQUE INDEX idx_project_categories_kind_default_singleton
            ON project_categories(category_kind)
            WHERE is_default = 1
            """,
            """
            CREATE UNIQUE INDEX idx_project_categories_kind_name_unique
            ON project_categories(category_kind, name COLLATE NOCASE)
            """,
            """
            CREATE INDEX idx_project_categories_sort_order
            ON project_categories(sort_order, created_at)
            """,
            """
            CREATE TRIGGER trg_projects_root_path_unique_insert
            BEFORE INSERT ON projects
            WHEN EXISTS (
                SELECT 1 FROM projects
                WHERE root_path = NEW.root_path
                  AND project_id <> NEW.project_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_root_path_duplicate');
            END
            """,
            """
            CREATE TRIGGER trg_projects_root_path_unique_update
            BEFORE UPDATE OF root_path ON projects
            WHEN EXISTS (
                SELECT 1 FROM projects
                WHERE root_path = NEW.root_path
                  AND project_id <> OLD.project_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_root_path_duplicate');
            END
            """,
            """
            CREATE TRIGGER trg_projects_category_kind_insert
            BEFORE INSERT ON projects
            WHEN NOT EXISTS (
                SELECT 1 FROM project_categories
                WHERE category_id = NEW.category_id
                  AND category_kind = NEW.project_kind
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_category_kind_mismatch');
            END
            """,
            """
            CREATE TRIGGER trg_projects_category_kind_update
            BEFORE UPDATE OF category_id, project_kind ON projects
            WHEN NOT EXISTS (
                SELECT 1 FROM project_categories
                WHERE category_id = NEW.category_id
                  AND category_kind = NEW.project_kind
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_category_kind_mismatch');
            END
            """,
            """
            CREATE TRIGGER trg_project_categories_kind_update
            BEFORE UPDATE OF category_kind ON project_categories
            WHEN EXISTS (
                SELECT 1 FROM projects
                WHERE category_id = OLD.category_id
                  AND project_kind <> NEW.category_kind
            )
            BEGIN
                SELECT RAISE(ABORT, 'project_category_kind_mismatch');
            END
            """,
            """
            CREATE TRIGGER trg_reject_legacy_role_category_insert
            BEFORE INSERT ON project_categories
            WHEN NEW.category_id = 'role-set'
            BEGIN
                SELECT RAISE(ABORT, 'legacy_role_category_removed');
            END
            """,
            """
            CREATE TRIGGER trg_reject_legacy_role_category_id_update
            BEFORE UPDATE OF category_id ON project_categories
            WHEN NEW.category_id = 'role-set'
            BEGIN
                SELECT RAISE(ABORT, 'legacy_role_category_removed');
            END
            """,
        ),
    ),
)


def ensure_database_schema(database_path: Path) -> None:
    """确保数据库 Schema 已创建并应用所有待迁移"""
    run_database_migrations(database_path, MIGRATIONS)


def prepare_database_for_provider_file_migration(database_path: Path) -> None:
    """Apply the legacy provider schema before its one-time export to Data/providers."""

    run_database_migrations(
        database_path,
        tuple(migration for migration in MIGRATIONS if migration.version < 28),
    )
