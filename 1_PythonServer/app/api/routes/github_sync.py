from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from app.core.errors import BadRequestError
from app.domain.github_sync import GithubSyncDirection
from app.domain.project import ProjectKind
from app.infra.github import GithubApiError
from app.schemas.github_sync import (
    GithubSyncApplyRequest,
    GithubSyncApplyResponse,
    GithubSyncBindingRequest,
    GithubSyncBindingResponse,
    GithubSyncOverviewResponse,
    GithubSyncPlanRequest,
    GithubSyncPlanResponse,
    GithubSyncToolRequest,
)
from app.services.application.github_sync import get_github_sync_service
from app.services.tools.host_capability_access import (
    HostCapability,
    get_host_capability_access_service,
)


router = APIRouter(prefix="/github/sync", tags=["github"])


@router.post("/tool", summary="Run GitHub sync through an authorized tool process")
async def run_github_sync_tool(
    payload: GithubSyncToolRequest,
    authorization: Annotated[str | None, Header()] = None,
    github_token: Annotated[str | None, Header(alias="X-Tiance-Github-Token")] = None,
) -> dict:
    grant = get_host_capability_access_service().authorize(
        _bearer_token(authorization),
        HostCapability.GITHUB_SYNC,
    )
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="后端 GitHub 同步授权无效或已过期。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    service = get_github_sync_service()
    collection = service.resolve_tool_collection(
        explicit=payload.collection,
        project_id=grant.project_id,
    )
    try:
        if payload.action in {"overview", "list_repositories"}:
            connected, binding, repositories, authorization_url = await service.overview(
                collection=collection,
                fallback_token=github_token,
            )
            return {
                "ok": True,
                "action": payload.action,
                "collection": collection.value,
                "connected": connected,
                "binding": (
                    GithubSyncBindingResponse.from_domain(binding).model_dump(by_alias=True)
                    if binding else None
                ),
                "repositories": repositories,
                "authorizationUrl": authorization_url,
            }
        if payload.action == "get_binding":
            binding = service.get_binding(collection)
            return {
                "ok": True,
                "action": payload.action,
                "collection": collection.value,
                "binding": (
                    GithubSyncBindingResponse.from_domain(binding).model_dump(by_alias=True)
                    if binding else None
                ),
            }
        if payload.action == "bind":
            if not payload.repository:
                raise BadRequestError("bind 必须提供 repository。")
            binding = await service.save_binding(
                collection=collection,
                repository=payload.repository,
                branch=payload.branch or "main",
                remote_path=payload.remote_path or "",
                fallback_token=github_token,
            )
            return {
                "ok": True,
                "action": payload.action,
                "binding": GithubSyncBindingResponse.from_domain(binding).model_dump(by_alias=True),
            }
        if payload.action == "unbind":
            service.delete_binding(collection)
            return {"ok": True, "action": payload.action, "collection": collection.value}
        if payload.action in {"plan_push", "plan_pull"}:
            direction = (
                GithubSyncDirection.PUSH
                if payload.action == "plan_push"
                else GithubSyncDirection.PULL
            )
            plan = await service.create_plan(
                collection=collection,
                direction=direction,
                fallback_token=github_token,
            )
            return {
                "ok": True,
                "action": payload.action,
                "plan": GithubSyncPlanResponse.from_domain(plan).model_dump(by_alias=True),
            }
        if not payload.plan_id:
            raise BadRequestError(f"{payload.action} 必须提供 planId。")
        plan, commit_sha = await service.apply_plan(
            payload.plan_id,
            commit_message=payload.commit_message,
            fallback_token=github_token,
            expected_direction=(
                GithubSyncDirection.PUSH
                if payload.action == "push"
                else GithubSyncDirection.PULL
            ),
        )
        return {
            "ok": True,
            "action": payload.action,
            "collection": plan.collection.value,
            "direction": plan.direction.value,
            "commitSha": commit_sha,
            "changedFiles": len(plan.changes),
        }
    except GithubApiError as exc:
        raise BadRequestError(str(exc)) from exc


@router.get("/{collection}", response_model=GithubSyncOverviewResponse)
async def get_github_sync_overview(collection: ProjectKind) -> GithubSyncOverviewResponse:
    connected, binding, repositories, authorization_url = await get_github_sync_service().overview(
        collection=collection,
    )
    return GithubSyncOverviewResponse(
        collection=collection,
        connected=connected,
        binding=GithubSyncBindingResponse.from_domain(binding) if binding else None,
        repositories=repositories,
        authorization_url=authorization_url,
    )


@router.put("/{collection}/binding", response_model=GithubSyncBindingResponse)
async def save_github_sync_binding(
    collection: ProjectKind,
    payload: GithubSyncBindingRequest,
) -> GithubSyncBindingResponse:
    binding = await get_github_sync_service().save_binding(
        collection=collection,
        repository=payload.repository,
        branch=payload.branch,
        remote_path=payload.remote_path,
    )
    return GithubSyncBindingResponse.from_domain(binding)


@router.delete("/{collection}/binding")
async def delete_github_sync_binding(collection: ProjectKind) -> dict:
    get_github_sync_service().delete_binding(collection)
    return {"ok": True}


@router.post("/plans/create", response_model=GithubSyncPlanResponse)
async def create_github_sync_plan(
    payload: GithubSyncPlanRequest,
) -> GithubSyncPlanResponse:
    if payload.collection is None:
        raise BadRequestError("前端同步必须明确指定 collection。")
    try:
        direction = GithubSyncDirection(payload.direction)
        plan = await get_github_sync_service().create_plan(
            collection=payload.collection,
            direction=direction,
        )
    except GithubApiError as exc:
        raise BadRequestError(str(exc)) from exc
    return GithubSyncPlanResponse.from_domain(plan)


@router.post("/plans/{plan_id}/apply", response_model=GithubSyncApplyResponse)
async def apply_github_sync_plan(
    plan_id: str,
    payload: GithubSyncApplyRequest,
) -> GithubSyncApplyResponse:
    try:
        plan, commit_sha = await get_github_sync_service().apply_plan(
            plan_id,
            commit_message=payload.commit_message,
        )
    except GithubApiError as exc:
        raise BadRequestError(str(exc)) from exc
    return GithubSyncApplyResponse(
        collection=plan.collection,
        direction=plan.direction.value,
        repository=plan.binding.repository,
        branch=plan.binding.branch,
        commit_sha=commit_sha,
        changed_files=len(plan.changes),
        message="提交完成。" if plan.direction is GithubSyncDirection.PUSH else "拉取完成。",
    )


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer":
        return ""
    return token.strip()
