from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from app.schemas.github_platform import GithubPlatformToolRequest
from app.services.application.github_platform import get_github_platform_service
from app.services.tools.host_capability_access import (
    HostCapability,
    get_host_capability_access_service,
)


router = APIRouter(prefix="/github/platform", tags=["github"])


@router.post("/tool", summary="Operate GitHub through an authorized Tiance tool")
async def run_github_platform_tool(
    payload: GithubPlatformToolRequest,
    authorization: Annotated[str | None, Header()] = None,
    github_token: Annotated[str | None, Header(alias="X-Tiance-Github-Token")] = None,
) -> dict:
    grant = get_host_capability_access_service().authorize(
        _bearer_token(authorization),
        HostCapability.GITHUB_PLATFORM,
    )
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="GitHub 平台授权无效或已过期。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await get_github_platform_service().execute(
        tool_name=grant.tool_name,
        project_id=grant.project_id,
        action=payload.action,
        dry_run=payload.dry_run,
        parameters=payload.parameters,
        fallback_token=github_token,
    )


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer":
        return ""
    return token.strip()
