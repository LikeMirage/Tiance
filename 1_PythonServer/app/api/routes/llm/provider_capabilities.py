from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, Header, HTTPException, status

from app.core.errors import (
    UpstreamProviderError,
    local_exception_message,
    to_upstream_provider_error,
)
from app.schemas.llm.provider_capabilities import (
    ProviderWebSearchRequestBody,
    ProviderWebSearchResponse,
)
from app.services.llm.provider_capabilities import get_provider_capability_service
from app.services.tools.host_capability_access import (
    HostCapability,
    get_host_capability_access_service,
)


router = APIRouter(prefix="/llm/provider-capabilities", tags=["llm"])


@router.post(
    "/web-search",
    response_model=ProviderWebSearchResponse,
    summary="Run provider-hosted web search for an authorized tool process",
)
async def run_provider_web_search(
    payload: ProviderWebSearchRequestBody,
    authorization: Annotated[str | None, Header()] = None,
) -> ProviderWebSearchResponse:
    token = _bearer_token(authorization)
    grant = get_host_capability_access_service().authorize(
        token,
        HostCapability.WEB_SEARCH,
    )
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="后端供应商能力授权无效或已过期。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        result = await get_provider_capability_service().web_search(
            grant=grant,
            query=payload.query,
        )
    except httpx.HTTPStatusError as exc:
        raise to_upstream_provider_error(exc) from exc
    except httpx.RequestError as exc:
        raise UpstreamProviderError(
            local_exception_message(exc),
            code="upstream_connection_error",
        ) from exc
    return ProviderWebSearchResponse.from_domain(result)


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer":
        return ""
    return token.strip()
