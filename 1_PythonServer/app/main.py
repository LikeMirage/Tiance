import asyncio
from contextlib import asynccontextmanager
from contextlib import suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.bootstrap import bootstrap_application
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.infra.http_client import (
    close_shared_http_clients,
    configure_shared_http_client,
    start_shared_http_client,
)
from app.services.network_settings import get_network_settings_service
from app.services.project.conversation_background_tasks import (
    get_conversation_background_task_registry,
)
from app.services.project.conversation_audit import get_conversation_audit_service
from app.services.project.conversation_run_manager import get_conversation_run_manager
from app.services.application.project_workspace_reconciliation import (
    get_project_workspace_reconciliation_service,
)
from app.services.application.project_market import (
    get_experience_market_application_service,
    get_knowledge_market_application_service,
    get_project_market_application_service,
)
from app.services.project.project_workspace_watcher import (
    watch_project_workspace_changes,
)
from app.services.tools.tool_metadata_watcher import watch_tool_metadata_changes
from app.services.tools.tool_registry import get_tool_registry_service
from app.services.application.theme_workspace_reconciliation import (
    get_theme_workspace_reconciliation_service,
)
from app.services.themes.theme_workspace_watcher import watch_theme_workspace_changes
from app.static_frontend import mount_frontend_dist


@asynccontextmanager
async def _lifespan(_application: FastAPI):
    settings = get_settings()
    bootstrap_application()
    configure_shared_http_client(get_network_settings_service().get_settings())
    start_shared_http_client()
    tool_metadata_watch_task = asyncio.create_task(
        watch_tool_metadata_changes(
            settings.tools_data_path,
            get_tool_registry_service(),
        )
    )
    theme_workspace_watch_task = asyncio.create_task(
        watch_theme_workspace_changes(
            settings.themes_data_path,
            get_theme_workspace_reconciliation_service(),
        )
    )
    project_workspace_watch_task = asyncio.create_task(
        watch_project_workspace_changes(
            settings.projects_data_path,
            get_project_workspace_reconciliation_service(),
        )
    )
    try:
        yield
    finally:
        project_workspace_watch_task.cancel()
        with suppress(asyncio.CancelledError):
            await project_workspace_watch_task
        theme_workspace_watch_task.cancel()
        with suppress(asyncio.CancelledError):
            await theme_workspace_watch_task
        tool_metadata_watch_task.cancel()
        with suppress(asyncio.CancelledError):
            await tool_metadata_watch_task
        await get_conversation_run_manager().close()
        await get_conversation_background_task_registry().close()
        await get_conversation_audit_service().close()
        await get_project_market_application_service().close()
        await get_knowledge_market_application_service().close()
        await get_experience_market_application_service().close()
        await close_shared_http_clients()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=_lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(application)

    @application.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"message": "Tiance API server is running."}

    application.include_router(api_router)
    mount_frontend_dist(application, settings)
    return application


app = create_app()
