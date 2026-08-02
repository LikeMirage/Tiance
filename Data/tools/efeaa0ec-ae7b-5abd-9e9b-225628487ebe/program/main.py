from __future__ import annotations

from json import dumps, loads
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from typing import Any

from tiance_runtime import run_tool


OPERATIONS = {"get_parameters", "get_examples"}
API_TIMEOUT_SECONDS = 20


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def ok(
    summary: str,
    *,
    operation: str,
    tool_name: str,
    data: dict[str, Any],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "summary": summary,
        "operation": operation,
        "tool_name": tool_name,
        "data": data,
        "warnings": warnings or [],
    }


def fail(
    code: str,
    message: str,
    *,
    operation: str | None = None,
    tool_name: str | None = None,
    details: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "error": f"{code}: {message}",
        "error_info": {
            "code": code,
            "message": message,
            "details": details or {},
        },
        "warnings": [],
    }
    if operation:
        result["operation"] = operation
    if tool_name:
        result["tool_name"] = tool_name
    if data is not None:
        result["data"] = data
    return result


def run(payload: dict[str, Any]) -> dict[str, Any]:
    operation: str | None = None
    tool_name: str | None = None
    try:
        operation = _read_operation(payload.get("operation"))
        tool_name = _read_tool_name(payload.get("tool_name"))
        if operation == "get_parameters":
            return _get_parameters(tool_name)
        if operation == "get_examples":
            return _get_examples(
                tool_name,
                include_all=_read_bool(payload.get("include_all_examples"), False),
                indexes=_read_int_list(payload.get("example_indexes")),
                titles=_read_string_list(payload.get("example_titles")),
            )
        raise ToolError("INVALID_OPERATION", "operation 不在支持范围内。", {"operation": operation})
    except ToolError as exc:
        return fail(exc.code, exc.message, operation=operation, tool_name=tool_name, details=exc.details)
    except Exception as exc:
        return fail(
            "UNEXPECTED_ERROR",
            str(exc) or exc.__class__.__name__,
            operation=operation,
            tool_name=tool_name,
        )


def _get_parameters(tool_name: str) -> dict[str, Any]:
    detail = _request_json(
        "GET",
        f"/tools/catalog/{quote(tool_name)}/parameters",
        query=_session_query(),
    )
    summary = _get_summary(tool_name)
    input_schema = detail.get("input_schema") if isinstance(detail, dict) else {}
    if not isinstance(input_schema, dict):
        input_schema = {}
    data = {
        "name": summary["name"],
        "display_name": summary["display_name"],
        "description": summary["description"],
        "category": summary["category"],
        "keywords": list(summary["keywords"]),
        "dynamic": summary["dynamic"],
        "parallel": summary["parallel"],
        "parameter_names": list(summary["parameter_names"]),
        "example_titles": list(summary["example_titles"]),
        "required": input_schema.get("required") if isinstance(input_schema, dict) else [],
        "input_schema": input_schema,
    }
    return ok(f"已读取 {tool_name} 的完整输入参数。", operation="get_parameters", tool_name=tool_name, data=data)


def _get_examples(
    tool_name: str,
    *,
    include_all: bool,
    indexes: tuple[int, ...],
    titles: tuple[str, ...],
) -> dict[str, Any]:
    should_include_all = include_all or (not indexes and not titles)
    response = _request_json(
        "POST",
        f"/tools/catalog/{quote(tool_name)}/examples/query",
        query=_session_query(),
        payload={
            "indexes": list(indexes),
            "titles": list(titles),
            "include_all": should_include_all,
        },
    )
    examples = response.get("items") if isinstance(response, dict) else []
    if not isinstance(examples, list):
        examples = []
    data = {
        "tool_name": tool_name,
        "returned_examples": len(examples),
        "examples": [
            {
                "index": example.get("index"),
                "title": example.get("title"),
                "content": example.get("content"),
            }
            for example in examples
            if isinstance(example, dict)
        ],
    }
    return ok(f"已读取 {tool_name} 的 {len(examples)} 条应用示例。", operation="get_examples", tool_name=tool_name, data=data)


def _get_summary(tool_name: str) -> dict[str, Any]:
    response = _request_json("GET", "/tools/catalog/summaries")
    items = response.get("items") if isinstance(response, dict) else []
    if not isinstance(items, list):
        raise ToolError("INVALID_CATALOG_RESPONSE", "工具目录响应格式无效。")
    for item in items:
        if isinstance(item, dict) and item.get("name") == tool_name:
            return {
                "name": _read_response_string(item, "name"),
                "display_name": _read_response_string(item, "display_name"),
                "description": _read_response_string(item, "description"),
                "category": _read_response_string(item, "category"),
                "keywords": _read_response_string_list(item.get("keywords")),
                "dynamic": item.get("dynamic") is True,
                "parallel": item.get("parallel") is True,
                "parameter_names": _read_response_string_list(item.get("parameter_names")),
                "example_titles": _read_response_string_list(item.get("example_titles")),
            }
    raise ToolError("TOOL_NOT_FOUND", f"工具 '{tool_name}' 不存在。", {"tool_name": tool_name})


def _request_json(
    method: str,
    path: str,
    *,
    query: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = _build_url(path, query=query)
    data = None if payload is None else dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=API_TIMEOUT_SECONDS) as response:
            raw_payload = response.read().decode("utf-8")
    except HTTPError as exc:
        raw_payload = exc.read().decode("utf-8", errors="replace")
        error_payload = _loads_json_object(raw_payload)
        raise _to_tool_error(exc.code, error_payload, url=url) from exc
    except URLError as exc:
        raise ToolError(
            "BACKEND_UNAVAILABLE",
            "无法连接天策后端工具目录接口。",
            {"url": url, "reason": str(exc.reason)},
        ) from exc

    response_payload = _loads_json_object(raw_payload)
    if response_payload is None:
        raise ToolError("INVALID_CATALOG_RESPONSE", "工具目录接口没有返回 JSON 对象。", {"url": url})
    return response_payload


def _build_url(path: str, *, query: dict[str, str] | None = None) -> str:
    base_url = _api_base_url().rstrip("/")
    normalized_path = "/" + path.strip().lstrip("/")
    url = f"{base_url}{normalized_path}"
    query_items = {key: value for key, value in (query or {}).items() if value}
    if query_items:
        url = f"{url}?{urlencode(query_items)}"
    return url


def _api_base_url() -> str:
    configured = os.environ.get("TIANCE_API_BASE_URL")
    if configured and configured.strip():
        return configured.strip()
    host = _connect_host(os.environ.get("TIANCE_API_HOST", "127.0.0.1"))
    port = os.environ.get("TIANCE_API_PORT", "18000").strip() or "18000"
    return f"http://{host}:{port}/api"


def _session_query() -> dict[str, str]:
    query: dict[str, str] = {}
    project_id = os.environ.get("TIANCE_PROJECT_ID")
    session_id = os.environ.get("TIANCE_SESSION_ID")
    if project_id:
        query["project_id"] = project_id
    if session_id:
        query["session_id"] = session_id
    return query


def _loads_json_object(raw_payload: str) -> dict[str, Any] | None:
    try:
        payload = loads(raw_payload)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _to_tool_error(status_code: int, payload: dict[str, Any] | None, *, url: str) -> ToolError:
    message = _read_error_message(payload) or f"工具目录接口返回 HTTP {status_code}。"
    code = _read_error_code(payload, status_code=status_code, message=message)
    return ToolError(
        code,
        message,
        {
            "status_code": status_code,
            "url": url,
        },
    )


def _read_error_message(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    error_payload = payload.get("error")
    if isinstance(error_payload, dict):
        message = error_payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    detail = payload.get("detail")
    return detail.strip() if isinstance(detail, str) else ""


def _read_error_code(payload: dict[str, Any] | None, *, status_code: int, message: str) -> str:
    if message == "此工具已关闭。":
        return "TOOL_CLOSED"
    if "当前会话不存在" in message:
        return "SESSION_NOT_FOUND"
    if "工具" in message and "不存在" in message:
        return "TOOL_NOT_FOUND"
    if not isinstance(payload, dict):
        return "BACKEND_REQUEST_FAILED"
    error_payload = payload.get("error")
    if isinstance(error_payload, dict):
        code = error_payload.get("code")
        if isinstance(code, str) and code.strip():
            return code.strip().upper()
    if status_code == 400:
        return "BAD_REQUEST"
    if status_code == 404:
        return "NOT_FOUND"
    return "BACKEND_REQUEST_FAILED"


def _read_operation(value: Any) -> str:
    operation = value.strip() if isinstance(value, str) else ""
    if operation not in OPERATIONS:
        raise ToolError("INVALID_OPERATION", "operation 必须是 get_parameters 或 get_examples。", {"operation": value})
    return operation


def _read_tool_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolError("INVALID_TOOL_NAME", "tool_name 必须是非空字符串。")
    return value.strip()


def _read_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def _read_int_list(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    items: list[int] = []
    for item in value:
        if isinstance(item, bool):
            continue
        try:
            parsed = int(item)
        except (TypeError, ValueError):
            continue
        if parsed >= 1 and parsed not in items:
            items.append(parsed)
    return tuple(items)


def _read_string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        normalized = item.strip()
        if normalized and normalized not in items:
            items.append(normalized)
    return tuple(items)


def _read_response_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) else ""


def _read_response_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _connect_host(value: str | None) -> str:
    host = (value or "").strip() or "127.0.0.1"
    if host in {"0.0.0.0", "::"}:
        return "127.0.0.1"
    return host


if __name__ == "__main__":
    run_tool(run)
