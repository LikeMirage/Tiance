from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException

from app.schemas.github_platform import GithubPlatformToolRequest
from app.services.application.github_platform import get_github_platform_service
from app.services.tools.host_capability_access import (
    HostCapability,
    get_host_capability_access_service,
)


router = APIRouter(prefix="/github/platform", tags=["github"])


def register_resource(path: str, capability: HostCapability, resource: str) -> None:
    async def execute(
        payload: GithubPlatformToolRequest,
        authorization: Annotated[str | None, Header()] = None,
        github_token: Annotated[str | None, Header(alias="X-Tiance-Github-Token")] = None,
    ) -> dict:
        grant = get_host_capability_access_service().authorize(_bearer_token(authorization), capability)
        if grant is None:
            raise HTTPException(status_code=401, detail="GitHub 能力授权无效或已过期。",
                headers={"WWW-Authenticate": "Bearer"})
        result = await get_github_platform_service().execute(
            resource=resource, project_id=grant.project_id, action=payload.action,
            dry_run=payload.dry_run, parameters=payload.parameters, fallback_token=github_token)
        return {**result, "tool": grant.tool_name}
    router.add_api_route(path, execute, methods=["POST"], name="github_" + resource)


register_resource("/repositories", HostCapability.GITHUB_REPOSITORIES, "repositories")
register_resource("/pull-requests", HostCapability.GITHUB_PULL_REQUESTS, "pull_requests")
register_resource("/issues", HostCapability.GITHUB_ISSUES, "issues")
register_resource("/releases", HostCapability.GITHUB_RELEASES, "releases")
register_resource("/actions", HostCapability.GITHUB_ACTIONS, "actions")


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer":
        return ""
    return token.strip()
