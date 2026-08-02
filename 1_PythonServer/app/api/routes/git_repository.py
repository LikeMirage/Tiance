from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from app.schemas.git_repository import GitRepositoryToolRequest
from app.services.application.git_repository import get_git_repository_service
from app.services.tools.host_capability_access import (
    HostCapability,
    get_host_capability_access_service,
)


router = APIRouter(prefix="/git/repository", tags=["git"])


@router.post("/tool", summary="Operate the current project Git repository")
async def run_git_repository_tool(
    payload: GitRepositoryToolRequest,
    authorization: Annotated[str | None, Header()] = None,
    github_token: Annotated[str | None, Header(alias="X-Tiance-Github-Token")] = None,
) -> dict:
    grant = get_host_capability_access_service().authorize(
        _bearer_token(authorization),
        HostCapability.GIT_REPOSITORY,
    )
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="后端 Git 仓库授权无效或已过期。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await get_git_repository_service().execute(
        payload,
        project_id=grant.project_id,
        fallback_token=github_token,
    )


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer":
        return ""
    return token.strip()
