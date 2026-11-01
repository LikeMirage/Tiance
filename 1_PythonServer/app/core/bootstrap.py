# 应用启动引导模块
# 在 FastAPI 启动时确保数据库 当前 Schema 已创建

import logging

from app.core.config import get_settings
from app.infra.database import ensure_database_schema
from app.services.llm.provider.storage_bootstrap import ensure_provider_file_storage
from app.services.llm.provider.workspace_registry import (
    get_provider_workspace_registry_service,
)
from app.services.locales import ensure_locale_catalog
from app.services.application.role_configuration import (
    get_role_configuration_application_service,
)
from app.services.application.project_workspace_reconciliation import (
    get_project_workspace_reconciliation_service,
)
from app.services.application.project_market import (
    get_experience_market_application_service,
    get_knowledge_market_application_service,
    get_project_market_application_service,
)
from app.services.application.theme_workspace_reconciliation import (
    get_theme_workspace_reconciliation_service,
)
from app.services.application.tool_market import get_tool_market_application_service
from app.repositories.themes import get_theme_market_settings_repository
from app.migrations.catalogs.database import migrate_project_catalogs
from app.migrations.catalogs.knowledge import migrate_knowledge_workspace
from app.migrations.catalogs.themes import get_legacy_collection_project_migration_service
from app.migrations.catalogs.workspace import upgrade_workspace_selection
from app.migrations.usage_db.storage import upgrade_usage_storage
from app.repositories.project import get_project_repository
from app.services.themes import ensure_active_theme_selection
from app.services.tools import get_toolset_service

logger = logging.getLogger(__name__)


def bootstrap_application() -> None:
    """初始化数据库 Schema，在应用启动时调用"""

    settings = get_settings()
    migrate_knowledge_workspace(settings.knowledge_data_path)
    ensure_database_schema(settings.app_database_file)
    ensure_provider_file_storage(settings.providers_data_path, settings.app_database_file)
    upgrade_usage_storage(settings.usage_data_path, settings.app_database_file)
    migrate_project_catalogs(settings.app_database_file, get_project_repository())
    get_provider_workspace_registry_service().synchronize()
    get_legacy_collection_project_migration_service().migrate_once()
    upgrade_workspace_selection(settings.app_database_file, get_project_repository())
    get_role_configuration_application_service().ensure_default_role()
    get_project_workspace_reconciliation_service().synchronize()
    get_project_market_application_service().prepare()
    get_knowledge_market_application_service().prepare()
    get_experience_market_application_service().prepare()
    get_theme_workspace_reconciliation_service().synchronize()
    get_theme_market_settings_repository().ensure_settings_file()
    ensure_active_theme_selection()
    get_toolset_service().ensure_default_toolsets()
    get_tool_market_application_service().prepare()
    ensure_locale_catalog()
    logger.info("Database schema initialized at %s", settings.app_database_file)
