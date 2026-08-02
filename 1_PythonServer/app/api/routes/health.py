# 健康检查路由
# GET /api/health 返回服务器状态信息

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.shell_lease import managed_shell_instance_id
from app.schemas.health import HealthResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="Server health check")
async def get_health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        name=settings.app_name,
        status="ok",
        environment=settings.environment,
        version=settings.app_version,
        docs_url="/docs",
        instance_id=managed_shell_instance_id(),
    )
