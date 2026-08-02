from fastapi import APIRouter, Query

from app.schemas.llm.runtime_capabilities import LlmRuntimeCapabilitiesResponse
from app.services.llm.runtime import get_llm_runtime_capabilities_service

router = APIRouter(prefix="/llm/runtime", tags=["llm"])


@router.get(
    "/capabilities",
    response_model=LlmRuntimeCapabilitiesResponse,
    summary="Resolve runtime capabilities for a provider/model pair",
)
def get_llm_runtime_capabilities(
    provider_id: str = Query(min_length=1),
    model_id: str | None = Query(default=None, min_length=1),
) -> LlmRuntimeCapabilitiesResponse:
    service = get_llm_runtime_capabilities_service()
    capabilities = service.get_capabilities(
        provider_id=provider_id.strip(),
        model_id=model_id.strip() if model_id else None,
    )
    return LlmRuntimeCapabilitiesResponse.from_domain(capabilities)
