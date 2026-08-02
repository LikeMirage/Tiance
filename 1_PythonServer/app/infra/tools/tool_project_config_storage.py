from __future__ import annotations

from contextlib import suppress
from json import dumps, loads
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from functools import lru_cache

from app.core.atomic_replace import atomic_replace_path
from app.core.errors import BadRequestError
from app.infra.tools.tool_project_config_constants import (
    TOOL_EXAMPLES_FILE,
    TOOL_FOLDER_MANIFEST_FILE,
    TOOL_INPUT_SCHEMA_FILE,
    TOOL_OUTPUT_SCHEMA_FILE,
)
from app.infra.tools.tool_project_config_helpers import (
    _normalize_examples_content,
    _normalize_input_schema_content,
    _normalize_output_schema_content,
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

    def __init__(self) -> None:
        self._write_lock = RLock()

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
        return content

    def update_manifest_display_name(
        self,
        project_root: str | Path,
        *,
        display_name: str,
    ) -> None:
        manifest_path = Path(project_root) / TOOL_FOLDER_MANIFEST_FILE
        if not manifest_path.is_file():
            return
        with self._write_lock:
            manifest = self._read_object(manifest_path)
            manifest["display_name"] = display_name
            self._write_object(manifest_path, manifest)

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

        display_name = payload.get("display_name")
        if not isinstance(display_name, str) or not display_name.strip():
            raise BadRequestError("工具显示名称不能为空。")
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
        payload["display_name"] = display_name.strip()
        payload["keywords"] = _normalize_string_list(payload.get("keywords"))
        _normalize_tool_loading(payload)
        _normalize_tool_execution(payload)
        _normalize_tool_state(payload)
        _normalize_tool_manifest_files(payload)
        _normalize_tool_runtime(payload)
        return dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    @staticmethod
    def _read_object(path: Path) -> dict[str, object]:
        payload = loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError("工具配置必须是 JSON 对象。")
        return payload

    @staticmethod
    def _write_object(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                delete=False,
                prefix=f".{path.name}.",
                suffix=".tmp",
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(text)
            atomic_replace_path(temporary_path, path)
        except Exception:
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink()
            raise


@lru_cache
def get_tool_project_config_storage() -> ToolProjectConfigStorage:
    return ToolProjectConfigStorage()
