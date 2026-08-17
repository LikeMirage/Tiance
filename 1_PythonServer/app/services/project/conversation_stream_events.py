from json import dumps

from app.domain.llm.chat import (
    ChatClientToolRequest,
    ChatStreamEvent,
    ChatStreamEventKind,
    ChatToolCall,
    ChatToolResult,
)


def stream_event_to_payload(
    event: ChatStreamEvent,
    *,
    usage_payload: dict[str, object] | None = None,
    context_tokens: int | None = None,
    context_tokens_estimated: bool = False,
) -> dict[str, object | None]:
    return {
        "kind": event.kind.value,
        "content": event.content,
        "finish_reason": event.finish_reason,
        "error": event.error,
        "error_code": event.error_code,
        "usage": usage_payload if event.kind == ChatStreamEventKind.USAGE else None,
        "context_tokens": context_tokens if event.kind == ChatStreamEventKind.USAGE else None,
        "context_tokens_estimated": (
            context_tokens_estimated
            if event.kind == ChatStreamEventKind.USAGE
            else None
        ),
        "tool_call": tool_call_to_payload(event.tool_call),
        "client_tool_request": client_tool_request_to_payload(event.client_tool_request),
        "tool_result": tool_result_to_payload(event.tool_result),
    }


def client_tool_request_to_payload(
    request: ChatClientToolRequest | None,
) -> dict[str, object] | None:
    if request is None:
        return None
    payload = {
        "request_id": request.request_id,
        "call_id": request.call_id,
        "name": request.name,
        "arguments": request.arguments,
        "project_id": request.project_id,
        "session_id": request.session_id,
        "timeout_seconds": request.timeout_seconds,
        "model_context": request.model_context,
    }
    if request.capability is not None:
        payload["client_capability"] = {
            "name": request.capability.name,
            "min_version": request.capability.version,
        }
    return payload


def tool_call_to_payload(tool_call: ChatToolCall | None) -> dict[str, object] | None:
    if tool_call is None:
        return None
    return {
        "call_id": tool_call.call_id,
        "name": tool_call.name,
        "arguments": tool_call.arguments,
    }


def tool_result_to_payload(tool_result: ChatToolResult | None) -> dict[str, object] | None:
    if tool_result is None:
        return None
    return {
        "call_id": tool_result.call_id,
        "name": tool_result.name,
        "arguments": tool_result.arguments,
        "ok": tool_result.ok,
        "content": tool_result.content,
        "error": tool_result.error,
        "tool_project_id": tool_result.tool_project_id,
        "elapsed_ms": tool_result.elapsed_ms,
        "dynamic": tool_result.dynamic,
    }


def tool_result_message_content(tool_result: ChatToolResult) -> str:
    payload = {
        "tool": tool_result.name,
        "call_id": tool_result.call_id,
        "ok": tool_result.ok,
        "arguments": tool_result.arguments,
        "result": tool_result.content,
    }
    if tool_result.tool_project_id:
        payload["tool_project_id"] = tool_result.tool_project_id
    if tool_result.error:
        payload["error"] = tool_result.error
    if tool_result.elapsed_ms is not None:
        payload["elapsed_ms"] = tool_result.elapsed_ms
    if tool_result.dynamic is not None:
        payload["dynamic"] = tool_result.dynamic
    return dumps(payload, ensure_ascii=False, separators=(",", ":"))


def tool_call_failure_result(tool_call: ChatToolCall, error: str) -> ChatToolResult:
    return ChatToolResult(
        call_id=tool_call.call_id,
        name=tool_call.name,
        arguments=tool_call.arguments,
        ok=False,
        content=dumps({"ok": False, "error": error}, ensure_ascii=False),
        error=error,
    )
