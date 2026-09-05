from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from tiance_runtime import run_tool


BACKEND_BASE_URL = os.environ.get(
    "TIANCE_BACKEND_URL",
    "http://127.0.0.1:18000/api",
).rstrip("/")
DEFAULT_TIMEOUT_SECONDS = 600


class BridgeError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def success(summary: str, data: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    return {"ok": True, "summary": summary, "data": data, "warnings": warnings or []}


def failure(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "error": f"{code}: {message}",
        "error_info": {"code": code, "message": message, "details": details or {}},
        "warnings": [],
    }


def required_text(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise BridgeError("INVALID_ARGUMENT", f"{key} 不能为空。")
    return value


def read_limit(value: Any) -> int:
    try:
        parsed = int(value if value is not None else 20)
    except (TypeError, ValueError) as exc:
        raise BridgeError("INVALID_ARGUMENT", "limit 必须是整数。") from exc
    if parsed < 1 or parsed > 100:
        raise BridgeError("INVALID_ARGUMENT", "limit 必须在 1 到 100 之间。")
    return parsed


def _json_request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    timeout: int = 30,
) -> dict[str, Any]:
    url = BACKEND_BASE_URL + path
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:
            detail = ""
        raise BridgeError(
            "BACKEND_HTTP_ERROR",
            f"Tiance 后端返回 HTTP {exc.code}。",
            {"path": path, "body": detail[:4000]},
        ) from exc
    except URLError as exc:
        raise BridgeError(
            "BACKEND_UNREACHABLE",
            "无法连接本机 Tiance 后端。",
            {"url": url, "reason": str(exc.reason)},
        ) from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BridgeError(
            "BACKEND_INVALID_JSON",
            "Tiance 后端返回了无效 JSON。",
            {"path": path, "body": raw[:2000]},
        ) from exc
    if not isinstance(payload, dict):
        raise BridgeError("BACKEND_INVALID_RESPONSE", "Tiance 后端返回值不是 JSON 对象。")
    return payload


def list_sessions(project_id: str) -> dict[str, Any]:
    pid = quote(project_id, safe="")
    payload = _json_request("GET", f"/projects/{pid}/conversations")
    raw_items = payload.get("items")
    items = raw_items if isinstance(raw_items, list) else []
    raw_states = payload.get("session_states")
    states = raw_states if isinstance(raw_states, dict) else {}
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        session_id = str(item.get("session_id") or "")
        state = states.get(session_id)
        runtime_status = state.get("runtime_status") if isinstance(state, dict) else None
        result.append({
            "session_id": session_id,
            "title": item.get("title"),
            "provider_id": item.get("provider_id"),
            "model_id": item.get("model_id"),
            "reasoning_mode": item.get("reasoning_mode"),
            "message_count": item.get("message_count"),
            "runtime_status": runtime_status,
            "updated_at": item.get("updated_at"),
            "role_project_id": item.get("role_project_id"),
            "role_status": item.get("role_status"),
        })
    return success(
        f"列出项目 {project_id} 的 {len(result)} 个 AI 会话。",
        {
            "project_id": project_id,
            "active_session_id": payload.get("active_session_id"),
            "count": len(result),
            "items": result,
        },
    )


def get_messages(project_id: str, session_id: str, limit: int) -> dict[str, Any]:
    pid = quote(project_id, safe="")
    sid = quote(session_id, safe="")
    payload = _json_request(
        "GET",
        f"/projects/{pid}/conversations/{sid}/messages?limit={limit}",
    )
    raw_items = payload.get("items")
    items = raw_items if isinstance(raw_items, list) else []
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        result.append({
            "message_id": item.get("message_id"),
            "role": item.get("role"),
            "content": item.get("content"),
            "status": item.get("status"),
            "created_at": item.get("created_at_local") or item.get("created_at"),
            "provider_id": item.get("provider_id"),
            "model_id": item.get("model_id"),
        })
    return success(
        f"读取会话 {session_id} 最近 {len(result)} 条消息。",
        {
            "project_id": project_id,
            "session_id": session_id,
            "count": len(result),
            "total_count": payload.get("total_count"),
            "has_more": payload.get("has_more"),
            "items": result,
        },
    )


def _find_session(project_id: str, session_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    pid = quote(project_id, safe="")
    payload = _json_request("GET", f"/projects/{pid}/conversations")
    raw_items = payload.get("items")
    items = raw_items if isinstance(raw_items, list) else []
    session = next(
        (
            item
            for item in items
            if isinstance(item, dict) and str(item.get("session_id") or "") == session_id
        ),
        None,
    )
    if session is None:
        raise BridgeError(
            "SESSION_NOT_FOUND",
            "目标会话不存在或不属于指定项目。",
            {"project_id": project_id, "session_id": session_id},
        )
    raw_states = payload.get("session_states")
    states = raw_states if isinstance(raw_states, dict) else {}
    state = states.get(session_id)
    return session, state if isinstance(state, dict) else None


def _completion_request(
    project_id: str,
    session_id: str,
    message: str,
    session: dict[str, Any],
) -> dict[str, Any]:
    provider_id = str(session.get("provider_id") or "").strip()
    model_id = str(session.get("model_id") or "").strip()
    if not provider_id or not model_id:
        raise BridgeError("SESSION_NOT_CONFIGURED", "目标会话没有可用的 provider_id/model_id。")
    raw_settings = session.get("settings")
    settings = raw_settings if isinstance(raw_settings, dict) else {}
    body: dict[str, Any] = {
        "provider_id": provider_id,
        "model_id": model_id,
        "project_id": project_id,
        "session_id": session_id,
        "messages": [{"role": "user", "content": message}],
        "malformed_tool_call_recovery_enabled": bool(
            settings.get("malformed_tool_call_recovery_enabled", True)
        ),
        "upstream_retry_count": int(settings.get("upstream_retry_count", 1)),
        "max_tool_calls": int(settings.get("max_tool_calls", 99999)),
        # 不声明桌面 client capability：目标 AI 仍可使用后端 Python/内部工具，
        # 但不会注入必须由桌面前端回执的 client-only 工具。
        "client_capabilities": [],
    }
    generation: dict[str, Any] = {}
    for key in ("temperature", "top_p", "max_output_tokens"):
        value = settings.get(key)
        if value is not None:
            generation[key] = value
    reasoning_mode = session.get("reasoning_mode")
    if reasoning_mode:
        generation["reasoning"] = {"mode": reasoning_mode}
    if generation:
        body["generation"] = generation
    return body


def send_message(project_id: str, session_id: str, message: str) -> dict[str, Any]:
    session, state = _find_session(project_id, session_id)
    if state and state.get("runtime_status") == "running":
        raise BridgeError(
            "SESSION_BUSY",
            "目标会话正在运行，未发送新消息。请等待完成或先执行 stop。",
            {"project_id": project_id, "session_id": session_id},
        )
    body = _completion_request(project_id, session_id, message, session)
    url = BACKEND_BASE_URL + "/llm/chat/completions/stream"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=data, method="POST")
    req.add_header("Accept", "text/event-stream")
    req.add_header("Content-Type", "application/json")

    answer_parts: list[str] = []
    user_message_id: str | None = None
    assistant_message_id: str | None = None
    settled_status: str | None = None
    finish_reason: str | None = None
    stream_error: str | None = None
    try:
        with urlopen(req, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                kind = str(event.get("kind") or "")
                if kind == "conversation_run_started":
                    value = event.get("user_message_id")
                    if isinstance(value, str):
                        user_message_id = value
                elif kind == "conversation_run_settled":
                    value = event.get("assistant_message_id")
                    if isinstance(value, str):
                        assistant_message_id = value
                    settled_status = str(event.get("status") or "") or None
                elif kind == "delta":
                    value = event.get("content")
                    if isinstance(value, str):
                        answer_parts.append(value)
                elif kind == "done":
                    finish_reason = str(event.get("finish_reason") or "") or None
                elif kind == "error":
                    stream_error = str(event.get("error") or "Tiance 会话生成失败。")
    except HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:
            detail = ""
        raise BridgeError(
            "BACKEND_HTTP_ERROR",
            f"Tiance 会话接口返回 HTTP {exc.code}。",
            {"body": detail[:4000]},
        ) from exc
    except URLError as exc:
        raise BridgeError("BACKEND_UNREACHABLE", "无法连接本机 Tiance 会话接口。", {"reason": str(exc.reason)}) from exc

    durable_reply: str | None = None
    durable_role: str | None = None
    if user_message_id:
        pid = quote(project_id, safe="")
        sid = quote(session_id, safe="")
        uid = quote(user_message_id, safe="")
        turn = _json_request(
            "GET",
            f"/projects/{pid}/conversations/{sid}/messages/{uid}/turn",
        )
        raw_items = turn.get("items")
        if isinstance(raw_items, list):
            for item in reversed(raw_items):
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role") or "")
                if role in {"assistant", "error"}:
                    durable_role = role
                    value = item.get("content")
                    durable_reply = value if isinstance(value, str) else ""
                    if not assistant_message_id:
                        mid = item.get("message_id")
                        if isinstance(mid, str):
                            assistant_message_id = mid
                    break

    reply = durable_reply if durable_reply is not None else "".join(answer_parts)
    if stream_error or durable_role == "error" or settled_status == "error":
        raise BridgeError(
            "SESSION_RUN_ERROR",
            stream_error or reply or "目标会话生成失败。",
            {
                "project_id": project_id,
                "session_id": session_id,
                "user_message_id": user_message_id,
                "assistant_message_id": assistant_message_id,
            },
        )
    return success(
        f"已向会话 {session_id} 发送消息并取得本次回复。",
        {
            "project_id": project_id,
            "session_id": session_id,
            "session_title": session.get("title"),
            "provider_id": session.get("provider_id"),
            "model_id": session.get("model_id"),
            "user_message_id": user_message_id,
            "assistant_message_id": assistant_message_id,
            "runtime_status": "idle",
            "outcome": settled_status or "done",
            "finish_reason": finish_reason,
            "reply": reply,
            "history_locator": {
                "tool_name": "conversation_history_search",
                "session_id": session_id,
            },
        },
    )


def stop_session(project_id: str, session_id: str) -> dict[str, Any]:
    payload = _json_request(
        "POST",
        "/llm/chat/completions/stream/stop",
        {"project_id": project_id, "session_id": session_id},
    )
    stopped = bool(payload.get("stopped"))
    return success(
        "已请求停止目标会话。" if stopped else "目标会话当前没有可停止的运行任务。",
        {"project_id": project_id, "session_id": session_id, "stopped": stopped},
    )


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        action = required_text(payload, "action")
        project_id = required_text(payload, "project_id")
        if action == "list_sessions":
            return list_sessions(project_id)
        session_id = required_text(payload, "session_id")
        if action == "get_messages":
            return get_messages(project_id, session_id, read_limit(payload.get("limit")))
        if action == "send":
            return send_message(project_id, session_id, required_text(payload, "message"))
        if action == "stop":
            return stop_session(project_id, session_id)
        raise BridgeError("INVALID_ARGUMENT", f"不支持的 action：{action}")
    except BridgeError as exc:
        return failure(exc.code, exc.message, exc.details)
    except Exception as exc:
        return failure("UNEXPECTED_ERROR", "AI 会话桥执行失败。", {"reason": str(exc)})


if __name__ == "__main__":
    run_tool(run)
