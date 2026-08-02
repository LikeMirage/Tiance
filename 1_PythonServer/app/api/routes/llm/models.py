# LLM 模型目录路由
# 为前端模型选择器提供统一模型列表

from fastapi import APIRouter, Query

from app.schemas.llm.model_catalog import (
    LlmModelCatalogEntryResponse,
    LlmModelCatalogListResponse,
)
from app.services.llm.model_catalog import (
    LlmModelCatalogKind,
    get_llm_model_catalog_service,
)

router = APIRouter(prefix="/llm/models", tags=["llm"])


@router.get(
    "",
    response_model=LlmModelCatalogListResponse,
    summary="List available LLM models",
)
def list_llm_models(
    enabled_only: bool = Query(default=True),
    kind: LlmModelCatalogKind | None = Query(default=None),
) -> LlmModelCatalogListResponse:
    service = get_llm_model_catalog_service()
    models = service.list_models(enabled_only=enabled_only, kind=kind)
    items = [LlmModelCatalogEntryResponse.from_domain(model) for model in models]
    return LlmModelCatalogListResponse(count=len(items), items=items)
