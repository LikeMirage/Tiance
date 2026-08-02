from __future__ import annotations

from json import dumps, loads
import subprocess
from typing import Any

from app.domain.llm.chat import ChatToolCall, ChatToolResult


TOOL_ARGUMENT_VALIDATION_FAILED = "TOOL_ARGUMENT_VALIDATION_FAILED"


def completed_process_result(
    tool_call: ChatToolCall,
    completed: subprocess.CompletedProcess[str],
    *,
    tool_project_id: str | None = None,
    dynamic: bool | None = None,
) -> ChatToolResult:
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if not stdout:
        return failure_result(tool_call, stderr or "工具没有返回 JSON。", tool_project_id=tool_project_id, dynamic=dynamic)
    try:
        payload = loads(stdout)
    except ValueError as exc:
        return failure_result(tool_call, f"工具返回值不是合法 JSON：{exc}", tool_project_id=tool_project_id, dynamic=dynamic)
    if not isinstance(payload, dict):
        return failure_result(tool_call, "工具返回值必须是 JSON 对象。", tool_project_id=tool_project_id, dynamic=dynamic)

    ok = completed.returncode == 0 and payload.get("ok") is not False
    content = dumps(payload, ensure_ascii=False, separators=(",", ":"))
    error = _read_error(payload, stderr=stderr) if not ok else None
    return ChatToolResult(
        call_id=tool_call.call_id,
        name=tool_call.name,
        arguments=tool_call.arguments,
        ok=ok,
        content=content,
        error=error,
        tool_project_id=tool_project_id,
        dynamic=dynamic,
    )


def failure_result(
    tool_call: ChatToolCall,
    error: str,
    *,
    tool_project_id: str | None = None,
    dynamic: bool | None = None,
    error_code: str | None = None,
) -> ChatToolResult:
    payload = {
        "ok": False,
        "error": error,
    }
    if error_code:
        payload["error_info"] = {"code": error_code}
    return ChatToolResult(
        call_id=tool_call.call_id,
        name=tool_call.name,
        arguments=tool_call.arguments,
        ok=False,
        content=dumps(payload, ensure_ascii=False, separators=(",", ":")),
        error=error,
        tool_project_id=tool_project_id,
        dynamic=dynamic,
    )


def dynamic_tool_execution_result(
    executor_call: ChatToolCall,
    target_result: ChatToolResult,
    *,
    executor_project_id: str,
) -> ChatToolResult:
    target_payload = _load_json_value(target_result.content)
    data = {
        "tool_name": target_result.name,
        "arguments": _load_json_value(target_result.arguments),
        "result": target_payload,
    }
    payload: dict[str, Any] = {
        "ok": target_result.ok,
        "data": data,
    }
    if isinstance(target_payload, dict):
        content = target_payload.get("content")
        if isinstance(content, list):
            payload["content"] = content
        structured_content = target_payload.get("structuredContent")
        if isinstance(structured_content, dict):
            payload["structuredContent"] = structured_content
    error = None
    if target_result.ok:
        payload["summary"] = f"已执行动态工具 {target_result.name}。"
    else:
        error = target_result.error or "目标动态工具执行失败。"
        payload["error"] = error

    return ChatToolResult(
        call_id=executor_call.call_id,
        name=executor_call.name,
        arguments=executor_call.arguments,
        ok=target_result.ok,
        content=dumps(payload, ensure_ascii=False, separators=(",", ":")),
        error=error,
        tool_project_id=executor_project_id,
        dynamic=False,
    )


def _read_error(payload: dict[str, Any], *, stderr: str) -> str:
    error = payload.get("error")
    if isinstance(error, str) and error.strip():
        return error.strip()
    return stderr or "工具执行失败。"


def _load_json_value(value: str) -> Any:
    try:
        return loads(value)
    except (TypeError, ValueError):
        return value
