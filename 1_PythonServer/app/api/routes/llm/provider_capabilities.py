from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.domain.tools.host_capabilities import HostCapability
from app.domain.llm.provider_catalog import ProviderProtocolFamily
from app.services.llm.tool_provider_requests import model_source, post_to_endpoint, post_to_model
from app.services.tools.host_capability_access import get_host_capability_access_service


router = APIRouter(prefix="/llm/provider-capabilities", tags=["llm"])


class ModelSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["source"]


class ModelPostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["post"]
    protocol_family: ProviderProtocolFamily
    endpoint: str | None = None
    body: dict


class EndpointPostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str
    body: dict


def _grant(authorization, capability):
    scheme, _, token = (authorization or "").partition(" ")
    grant = get_host_capability_access_service().authorize(token if scheme.lower() == "bearer" else "", capability)
    if grant is None:
        raise HTTPException(401, "供应商能力授权无效或已过期。", headers={"WWW-Authenticate": "Bearer"})
    return grant


@router.post("/session-model")
async def session_model(
    payload: Annotated[ModelSourceRequest | ModelPostRequest, Field(discriminator="operation")],
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    grant = _grant(authorization, HostCapability.SESSION_MODEL)
    if isinstance(payload, ModelSourceRequest):
        return model_source(grant)
    return await post_to_model(grant, payload.protocol_family, payload.body, endpoint=payload.endpoint)


@router.post("/authenticated-post")
async def authenticated_post(payload: EndpointPostRequest, authorization: Annotated[str | None, Header()] = None) -> dict:
    grant = _grant(authorization, HostCapability.PROVIDER_AUTH)
    return await post_to_endpoint(grant, payload.endpoint, payload.body)
