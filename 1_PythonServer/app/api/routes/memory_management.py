from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from app.core.errors import BadRequestError
from app.schemas.memory_management import MemoryManagementToolRequest
from app.services.project.memory_management import (
    get_project_memory_management_service,
)
from app.services.tools.host_capability_access import (
    HostCapability,
    get_host_capability_access_service,
)


router = APIRouter(prefix="/memory/management", tags=["memory"])


@router.post("/tool", summary="Manage memory through an authorized tool process")
def run_memory_management_tool(
    payload: MemoryManagementToolRequest,
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    grant = get_host_capability_access_service().authorize(
        _bearer_token(authorization),
        HostCapability.MEMORY_MANAGEMENT,
    )
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="后端记忆管理授权无效或已过期。",
            headers={"WWW-Authenticate": "Bearer"},
        )

    service = get_project_memory_management_service()
    if payload.operation in {"list", "search"}:
        return _read_memories(service, payload, grant.project_id)

    if payload.scope is None:
        raise BadRequestError("写入操作必须指定记忆范围。")
    result = service.apply_operation(
        scope=payload.scope,
        operation=payload.operation,
        project_id=grant.project_id,
        memory_id=payload.memory_id,
        content=payload.content,
        keywords=payload.keywords,
        reason=payload.reason,
    )
    return {
        "ok": True,
        "summary": _write_summary(result),
        "data": {
            "scope": result["scope"],
            "operation": result["operation"],
            "memory_id": result["memory_id"],
            "memory": result["memory"],
            "count": len(result["memories"]),
            "memories": result["memories"],
        },
    }


def _read_memories(service, payload: MemoryManagementToolRequest, project_id: str | None) -> dict:
    scopes = ["global", "project"]
    grouped: dict[str, dict] = {}
    for scope in scopes:
        memories = service.list_memories(
            scope=scope,
            project_id=project_id,
            query=payload.query,
        )
        grouped[scope] = {"count": len(memories), "memories": memories}
    total_count = sum(item["count"] for item in grouped.values())
    global_count = grouped["global"]["count"]
    project_count = grouped["project"]["count"]
    return {
        "ok": True,
        "summary": (
            f"已读取全部当前有效长期记忆：全局 {global_count} 条，项目 {project_count} 条。"
            if payload.operation == "list"
            else f"已搜索全部当前有效长期记忆：全局 {global_count} 条，项目 {project_count} 条。"
        ),
        "data": {
            "operation": payload.operation,
            "count": total_count,
            **grouped,
        },
    }


def _write_summary(result: dict) -> str:
    scope = "全局记忆" if result["scope"] == "global" else "项目记忆"
    operation = result["operation"]
    memory_id = result.get("memory_id") or ""
    labels = {"add": "新增", "update": "更新", "delete": "删除"}
    return f"已{labels.get(operation, '完成')}{scope} {memory_id}。"


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer":
        return ""
    return token.strip()
