from __future__ import annotations

from typing import Any

from tiance_runtime import call_host_capability, run_tool


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
    detail = call_host_capability("tool_catalog", {"operation": "get_parameters", "tool_name": tool_name}, timeout_seconds=API_TIMEOUT_SECONDS)
    summary = detail["summary"]
    input_schema = detail.get("input_schema") if isinstance(detail, dict) else {}
    if not isinstance(input_schema, dict):
        input_schema = {}
    data = {
        "name": summary["name"],
        "display_name": summary["display_name"],
        "description": summary["description"],
        "category": summary["category"],
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
    response = call_host_capability("tool_catalog", {
        "operation": "get_examples", "tool_name": tool_name,
        "indexes": list(indexes), "titles": list(titles), "include_all": should_include_all,
    }, timeout_seconds=API_TIMEOUT_SECONDS)
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


if __name__ == "__main__":
    run_tool(run)
