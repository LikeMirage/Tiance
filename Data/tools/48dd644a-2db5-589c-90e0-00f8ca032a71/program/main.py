from __future__ import annotations

import os
from typing import Any

from app.core.errors import AppError
from app.services.project.memory_management import (
    get_project_memory_management_service,
    is_read_operation,
)
from tiance_runtime import run_tool


def ok(summary: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "summary": summary,
        "data": data,
    }


def fail(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "error": f"{code}: {message}",
        "error_info": {
            "code": code,
            "message": message,
            "details": details or {},
        },
    }


def run(payload: dict[str, Any]) -> dict[str, Any]:
    operation = read_text(payload.get("operation")).lower()
    project_id = read_text(os.environ.get("TIANCE_PROJECT_ID"))
    service = get_project_memory_management_service()

    try:
        if is_read_operation(operation):
            query = read_text(payload.get("query"))
            global_memories = service.list_memories(
                scope="global",
                query=query,
            )
            project_memories = service.list_memories(
                scope="project",
                project_id=project_id or None,
                query=query,
            )
            total_count = len(global_memories) + len(project_memories)
            return ok(
                (
                    "已读取全部当前有效长期记忆："
                    f"全局 {len(global_memories)} 条，"
                    f"项目 {len(project_memories)} 条。"
                ),
                {
                    "operation": operation,
                    "count": total_count,
                    "global": {
                        "count": len(global_memories),
                        "memories": global_memories,
                    },
                    "project": {
                        "count": len(project_memories),
                        "memories": project_memories,
                    },
                },
            )

        scope = read_text(payload.get("scope")).lower()
        result = service.apply_operation(
            scope=scope,
            operation=operation,
            project_id=project_id or None,
            memory_id=read_text(payload.get("memory_id")),
            content=read_text(payload.get("content")),
            keywords=read_keywords(payload.get("keywords")),
            reason=read_text(payload.get("reason")),
        )
        return ok(
            write_summary(result),
            {
                "scope": result["scope"],
                "operation": result["operation"],
                "memory_id": result["memory_id"],
                "memory": result["memory"],
                "count": len(result["memories"]),
                "memories": result["memories"],
            },
        )
    except AppError as exc:
        return fail(exc.code, exc.message, details=exc.details if isinstance(exc.details, dict) else {})


def read_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def read_keywords(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def scope_label(scope: str) -> str:
    return "全局记忆" if scope == "global" else "项目记忆"


def write_summary(result: dict[str, Any]) -> str:
    operation = result["operation"]
    scope = scope_label(result["scope"])
    memory_id = result.get("memory_id") or ""
    if operation == "add":
        return f"已新增{scope} {memory_id}。"
    if operation == "update":
        return f"已更新{scope} {memory_id}。"
    if operation == "delete":
        return f"已删除{scope} {memory_id}。"
    return f"已完成{scope}操作。"


if __name__ == "__main__":
    run_tool(run)
