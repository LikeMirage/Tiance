from __future__ import annotations

from json import dumps, loads
from functools import lru_cache

from app.core.errors import BadRequestError
from app.infra.tools.tool_project_config_constants import (
    TOOL_EXAMPLES_FILE,
    TOOL_FOLDER_MANIFEST_FILE,
    TOOL_INPUT_SCHEMA_FILE,
    TOOL_OUTPUT_SCHEMA_FILE,
    TOOL_PERMISSIONS_FILE,
)
from app.infra.tools.tool_project_config_helpers import (
    _normalize_examples_content,
    _normalize_input_schema_content,
    _normalize_output_schema_content,
    _normalize_permissions_content,
    _normalize_string_list,
    _normalize_tool_call_name,
    _normalize_tool_execution,
    _normalize_tool_loading,
    _normalize_tool_manifest_files,
    _normalize_tool_runtime,
    _normalize_tool_standard_file_path,
    _normalize_tool_state,
    _strip_json_bom,
)


class ToolProjectConfigStorage:
    """只管理单个工具项目中的标准配置文件，不负责项目或分类生命周期。"""

    def normalize_standard_file_content(
        self,
        target_path: str,
        content: str,
    ) -> str:
        normalized_path = _normalize_tool_standard_file_path(target_path)
        if normalized_path == TOOL_FOLDER_MANIFEST_FILE:
            return self._normalize_manifest_content(
                content=content,
            )
        if normalized_path == TOOL_INPUT_SCHEMA_FILE:
            return _normalize_input_schema_content(content)
        if normalized_path == TOOL_OUTPUT_SCHEMA_FILE:
            return _normalize_output_schema_content(content)
        if normalized_path == TOOL_EXAMPLES_FILE:
            return _normalize_examples_content(content)
        if normalized_path == TOOL_PERMISSIONS_FILE:
            return _normalize_permissions_content(content)
        return content

    def _normalize_manifest_content(
        self,
        *,
        content: str,
    ) -> str:
        try:
            payload = loads(_strip_json_bom(content))
        except ValueError as exc:
            raise BadRequestError("tool.json 必须是合法 JSON。") from exc
        if not isinstance(payload, dict):
            raise BadRequestError("tool.json 必须是 JSON 对象。")

        registration_name = payload.get("registration_name")
        if not isinstance(registration_name, str) or not registration_name.strip():
            raise BadRequestError("工具注册名称不能为空。")
        call_name = _normalize_tool_call_name(
            payload.get("name") if isinstance(payload.get("name"), str) else None
        )
        if not call_name:
            raise BadRequestError("工具调用名称不能为空。")
        if call_name == "tool_load_error":
            raise BadRequestError("工具读取失败占位内容不能保存为真实 tool.json。")

        for removed_key in (
            "summary",
            "tags",
            "permissions",
            "error",
            "context",
            "capabilities",
            "ui",
            "input_schema",
            "output_schema",
            "examples",
        ):
            payload.pop(removed_key, None)
        if not isinstance(payload.get("description"), str):
            payload["description"] = ""
        payload["name"] = call_name
        payload["registration_name"] = registration_name.strip()
        payload["keywords"] = _normalize_string_list(payload.get("keywords"))
        _normalize_tool_loading(payload)
        _normalize_tool_execution(payload)
        _normalize_tool_state(payload)
        _normalize_tool_manifest_files(payload)
        _normalize_tool_runtime(payload)
        return dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


@lru_cache
def get_tool_project_config_storage() -> ToolProjectConfigStorage:
    return ToolProjectConfigStorage()
