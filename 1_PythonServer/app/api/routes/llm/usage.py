from fastapi import APIRouter, Query

from app.schemas.llm.usage import LlmProviderModelUsageSummaryResponse
from app.services.llm.usage import get_llm_usage_service

router = APIRouter(prefix="/llm/usage", tags=["llm"])


@router.get(
    "/provider-model-summary",
    response_model=LlmProviderModelUsageSummaryResponse,
    summary="Get provider and model usage summary",
)
def get_provider_model_usage_summary(
    provider_id: str | None = Query(default=None),
) -> LlmProviderModelUsageSummaryResponse:
    summary = get_llm_usage_service().get_provider_model_summary(provider_id=provider_id)
    return LlmProviderModelUsageSummaryResponse.from_domain(summary)
