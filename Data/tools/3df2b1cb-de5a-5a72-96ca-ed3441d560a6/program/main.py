from __future__ import annotations

import os
from typing import Any

from app.core.errors import AppError
from app.services.project.conversation_memory import (
    get_project_conversation_memory_service,
)
from tiance_runtime import run_tool


def run(payload: dict[str, Any]) -> dict[str, Any]:
    project_id = _text(os.environ.get("TIANCE_PROJECT_ID"))
    session_id = _text(os.environ.get("TIANCE_SESSION_ID"))
    if not project_id or not session_id:
        return _failure(
            "MISSING_CONVERSATION_CONTEXT",
            "当前工具调用缺少项目或会话上下文。",
        )
    try:
        outcome = get_project_conversation_memory_service().handle_compaction_tool_call(
            project_id,
            session_id,
            payload.get("result"),
        )
    except AppError as exc:
        return _failure(
            exc.code,
            exc.message,
            exc.details if isinstance(exc.details, dict) else None,
        )
    action = outcome.get("action")
    if action == "not_needed":
        return {
            "ok": True,
            "summary": "当前会话的原文保护区之外没有可压缩历史，未创建记忆压缩会话。",
            "data": outcome,
        }
    if action == "disabled":
        return {
            "ok": True,
            "summary": "当前会话未启用记忆压缩，未创建记忆压缩会话。",
            "data": outcome,
        }
    if action == "scheduled":
        request = outcome.get("request")
        return {
            "ok": True,
            "summary": "已登记手动记忆压缩请求，将由会话调度创建并运行记忆压缩功能会话。",
            "data": request if isinstance(request, dict) else {},
        }
    task = outcome.get("task")
    if not isinstance(task, dict):
        return _failure(
            "INVALID_COMPACTION_OUTCOME",
            "记忆压缩工具返回了无法识别的处理结果。",
        )
    return {
        "ok": True,
        "summary": "记忆压缩结果已保存并应用到来源会话。",
        "data": {
            "compression_id": task.get("compression_id"),
            "source_session_id": task.get("source_session_id"),
            "function_session_id": task.get("function_session_id"),
            "status": task.get("status"),
        },
    }


def _failure(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "error": f"{code}: {message}",
        "error_info": {
            "code": code,
            "message": message,
            "details": details or {},
        },
    }


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


if __name__ == "__main__":
    run_tool(run)
