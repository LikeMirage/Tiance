# 应用启动引导模块
# 在 FastAPI 启动时确保数据库 Schema 已创建/迁移

import logging

from app.core.errors import AppError
from app.core.config import get_settings
from app.infra.database import (
    ensure_database_schema,
    prepare_database_for_provider_file_migration,
)
from app.services.llm.provider.storage_bootstrap import ensure_provider_file_storage
from app.services.llm.provider.workspace_registry import (
    get_provider_workspace_registry_service,
)
from app.services.locales import ensure_locale_catalog
from app.services.application.role_configuration import (
    get_role_configuration_application_service,
)
from app.services.application.legacy_collection_project_migration import (
    get_legacy_collection_project_migration_service,
)
from app.services.application.knowledge_workspace_migration import (
    migrate_knowledge_workspace,
)
from app.services.application.project_file_catalog_migration import (
    get_project_file_catalog_migration_service,
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
from app.services.application.usage_file_migration import ensure_usage_file_storage
from app.services.project import get_project_conversation_service, get_project_service
from app.services.themes import ensure_active_theme_selection
from app.services.tools import get_toolset_service
from app.services.workspace_activity import get_workspace_activity_service

logger = logging.getLogger(__name__)


def bootstrap_application() -> None:
    """初始化数据库 Schema，在应用启动时调用"""

    settings = get_settings()
    migrate_knowledge_workspace(settings.knowledge_data_path)
    prepare_database_for_provider_file_migration(settings.app_database_file)
    ensure_provider_file_storage(
        settings.providers_data_path,
        settings.app_database_file,
    )
    ensure_usage_file_storage(
        settings.app_database_file,
        settings.usage_data_path,
    )
    ensure_database_schema(settings.app_database_file)
    get_project_file_catalog_migration_service().migrate()
    get_provider_workspace_registry_service().synchronize()
    get_legacy_collection_project_migration_service().migrate_once()
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
    _reconcile_conversation_activity()
    ensure_locale_catalog()
    logger.info("Database schema initialized at %s", settings.app_database_file)


def _reconcile_conversation_activity() -> None:
    project_service = get_project_service()
    conversation_service = get_project_conversation_service()
    activity_service = get_workspace_activity_service()
    for project in project_service.list_projects():
        try:
            sessions = conversation_service.list_sessions(project.project_id)
        except (AppError, OSError):
            logger.exception(
                "Failed to reconcile conversation activity for project %s.",
                project.project_id,
            )
            continue
        for session in sessions:
            activity_service.record_conversation_created(session)
