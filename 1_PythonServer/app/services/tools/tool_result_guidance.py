from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from json import dumps, loads
from typing import Any

from app.core.errors import BadRequestError
from app.domain.llm.chat import ChatToolResult
from app.domain.tools import ToolRegistryEntry
from app.services.tools.dynamic_tool_contract import DYNAMIC_TOOL_EXECUTOR_NAME
from app.services.tools.tool_execution_results import TOOL_ARGUMENT_VALIDATION_FAILED
from app.services.tools.tool_metadata import normalize_tool_name
from app.services.tools.tool_registry import ToolRegistryService, get_tool_registry_service


class ToolResultGuidanceService:
    def __init__(self, registry_service: ToolRegistryService) -> None:
        self._registry_service = registry_service

    def add_failure_guidance(self, result: ChatToolResult) -> ChatToolResult:
        if result.ok:
            return result
        payload = _read_result_payload(result)
        tool_name, guidance_payload = _guidance_target(result.name, payload)
        entry = self._registry_service.get_enabled_entry(tool_name) if tool_name else None
        guidance_payload.pop("assistant_hint", None)
        payload["assistant_hint"] = _build_assistant_hint(
            tool_name=tool_name,
            entry=entry,
            error=_read_error(guidance_payload, fallback=result.error),
            error_code=_read_error_code(guidance_payload),
        )
        return replace(
            result,
            content=dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )


def _read_result_payload(result: ChatToolResult) -> dict[str, Any]:
    try:
        payload = loads(result.content)
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("ok", False)
    if result.error and not isinstance(payload.get("error"), str):
        payload["error"] = result.error
    return payload


def _guidance_target(
    result_name: str,
    payload: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    tool_name = _normalize_tool_name_or_empty(result_name)
    if tool_name != DYNAMIC_TOOL_EXECUTOR_NAME:
        return tool_name, payload

    data = payload.get("data")
    if not isinstance(data, dict):
        return tool_name, payload
    target_name = data.get("tool_name")
    target_payload = data.get("result")
    if not isinstance(target_name, str) or not isinstance(target_payload, dict):
        return tool_name, payload
    normalized_target_name = _normalize_tool_name_or_empty(target_name)
    if not normalized_target_name:
        return tool_name, payload
    return normalized_target_name, target_payload


def _build_assistant_hint(
    *,
    tool_name: str,
    entry: ToolRegistryEntry | None,
    error: str,
    error_code: str,
) -> dict[str, Any]:
    if entry is None:
        return {
            "type": "tool_call_failure_guidance",
            "tool_name": tool_name,
            "message": "工具调用失败，且当前启用工具注册表中没有找到该工具。检查工具名称、工具自身启用状态和当前会话工具设置。",
            "next_step": "确认工具名称和启用状态后再重试。",
        }

    hint: dict[str, Any] = {
        "type": "tool_call_failure_guidance",
        "tool_name": entry.tool_name,
        "display_name": entry.display_name,
        "dynamic": entry.dynamic,
        "error": error,
    }
    if entry.dynamic:
        if error_code != TOOL_ARGUMENT_VALIDATION_FAILED:
            hint.update(
                {
                    "message": "动态工具执行失败。",
                    "next_step": "根据目标工具返回的错误处理；需要重试时，通过 execute_dynamic_tool 调用该工具。",
                }
            )
            return hint
        hint.update(
            {
                "message": "动态工具参数校验失败。",
                "next_step": "调用 load_tool_info 读取完整参数定义，修正 arguments 后通过 execute_dynamic_tool 重试。",
                "suggested_tool": "load_tool_info",
                "suggested_arguments": {
                    "operation": "get_parameters",
                    "tool_name": entry.tool_name,
                },
            }
        )
        return hint

    hint.update(
        {
            "message": "工具调用失败。该工具已完整注入参数定义。",
            "next_step": "根据错误原因修正参数后重试；如果需要典型用法，可读取该工具的应用示例。",
        }
    )
    if entry.example_titles:
        hint.update(
            {
                "suggested_tool": "load_tool_info",
                "suggested_arguments": {
                    "operation": "get_examples",
                    "tool_name": entry.tool_name,
                    "include_all_examples": True,
                },
                "example_titles": list(entry.example_titles),
            }
        )
    return hint


def _read_error(payload: dict[str, Any], *, fallback: str | None) -> str:
    error = payload.get("error")
    if isinstance(error, str):
        return error
    return fallback or ""


def _read_error_code(payload: dict[str, Any]) -> str:
    error_info = payload.get("error_info")
    if not isinstance(error_info, dict):
        return ""
    code = error_info.get("code")
    return code if isinstance(code, str) else ""


def _normalize_tool_name_or_empty(tool_name: str) -> str:
    try:
        return normalize_tool_name(tool_name)
    except BadRequestError:
        return ""


@lru_cache
def get_tool_result_guidance_service() -> ToolResultGuidanceService:
    return ToolResultGuidanceService(get_tool_registry_service())
