# 健康检查响应模型

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """健康检查响应；受桌面壳管理时同时返回实例身份。"""

    name: str
    status: str
    environment: str
    version: str
    docs_url: str
    instance_id: str | None = None
