# 主路由聚合模块
# 将所有子路由挂载到 /api 前缀下

from fastapi import APIRouter

from app.api.routes.desktop import router as desktop_router
from app.api.routes.health import router as health_router
from app.api.routes.github_connection import router as github_connection_router
from app.api.routes.github_sync import router as github_sync_router
from app.api.routes.git_repository import router as git_repository_router
from app.api.routes.locales import router as locales_router
from app.api.routes.llm.client_tools import router as llm_client_tools_router
from app.api.routes.llm.chat import router as llm_chat_router
from app.api.routes.llm.chat_socket import router as llm_chat_socket_router
from app.api.routes.llm.functional_model_settings import (
    router as llm_functional_model_settings_router,
)
from app.api.routes.llm.models import router as llm_models_router
from app.api.routes.llm.provider_capabilities import (
    router as llm_provider_capabilities_router,
)
from app.api.routes.llm.provider_configs import router as llm_provider_config_router
from app.api.routes.llm.provider_market import router as llm_provider_market_router
from app.api.routes.llm.providers import router as llm_provider_router
from app.api.routes.llm.runtime import router as llm_runtime_router
from app.api.routes.llm.token_estimation_settings import (
    router as llm_token_estimation_settings_router,
)
from app.api.routes.network_settings import router as network_settings_router
from app.api.routes.llm.usage import router as llm_usage_router
from app.api.routes.project import router as project_router
from app.api.routes.roles import router as roles_router
from app.api.routes.themes import router as themes_router
from app.api.routes.tools import router as tools_router
from app.api.routes.workspace import router as workspace_router
from app.core.config import get_settings

settings = get_settings()

api_router = APIRouter(prefix=settings.api_prefix)
api_router.include_router(health_router)
api_router.include_router(github_connection_router)
api_router.include_router(github_sync_router)
api_router.include_router(git_repository_router)
api_router.include_router(desktop_router)
api_router.include_router(project_router)
api_router.include_router(roles_router)
api_router.include_router(workspace_router)
api_router.include_router(tools_router)
api_router.include_router(themes_router)
api_router.include_router(locales_router)
api_router.include_router(llm_chat_router)
api_router.include_router(llm_chat_socket_router)
api_router.include_router(llm_client_tools_router)
api_router.include_router(llm_provider_router)
api_router.include_router(llm_provider_market_router)
api_router.include_router(llm_provider_config_router)
api_router.include_router(llm_models_router)
api_router.include_router(llm_provider_capabilities_router)
api_router.include_router(llm_runtime_router)
api_router.include_router(llm_functional_model_settings_router)
api_router.include_router(llm_token_estimation_settings_router)
api_router.include_router(llm_usage_router)
api_router.include_router(network_settings_router)
