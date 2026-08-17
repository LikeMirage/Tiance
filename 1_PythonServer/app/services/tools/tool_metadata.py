from __future__ import annotations

from json import loads
from pathlib import Path
from typing import Any

from app.core.errors import BadRequestError
from app.domain.tools import (
    ToolExampleDetail,
    ToolExampleSummary,
    ToolSummary,
)
from app.infra.tools.tool_project_config_constants import (
    TOOL_EXAMPLES_FILE,
    TOOL_FOLDER_MANIFEST_FILE,
    TOOL_INPUT_SCHEMA_FILE,
    TOOL_OUTPUT_SCHEMA_FILE,
)


class LoadedTool:
    def __init__(
        self,
        *,
        name: str,
        manifest: dict[str, Any],
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
        examples: tuple[tuple[int, dict[str, Any]], ...],
    ) -> None:
        self.name = name
        self.manifest = manifest
        self.input_schema = input_schema
        self.output_schema = output_schema
        self.examples = examples


def load_tool(folder_root: str) -> LoadedTool:
    root = Path(folder_root)
    manifest = _read_json_object(root / TOOL_FOLDER_MANIFEST_FILE)
    _read_parallel_flag(manifest.get("execution"))
    _validate_runtime(manifest.get("runtime"))
    input_schema = _read_json_object(root / TOOL_INPUT_SCHEMA_FILE)
    output_schema = _read_json_object(root / TOOL_OUTPUT_SCHEMA_FILE)
    examples = _read_examples(root / TOOL_EXAMPLES_FILE)
    name = normalize_tool_name(_read_string(manifest, "name"))
    return LoadedTool(
        name=name,
        manifest=manifest,
        input_schema=input_schema,
        output_schema=output_schema,
        examples=examples,
    )


def build_summary(loaded_tool: LoadedTool, *, category: str) -> ToolSummary:
    manifest = loaded_tool.manifest
    loading = manifest.get("loading")
    execution = manifest.get("execution")
    client_capability = _read_client_capability(manifest.get("runtime"))
    return ToolSummary(
        name=loaded_tool.name,
        display_name=_read_string(manifest, "display_name"),
        description=_read_string(manifest, "description"),
        keywords=tuple(_read_string_list(manifest.get("keywords"))),
        category=category,
        dynamic=_read_dynamic_flag(loading),
        parameter_names=tuple(_read_parameter_names(loaded_tool.input_schema)),
        example_titles=tuple(
            example_title(example)
            for _, example in loaded_tool.examples
            if example_enabled(example)
        ),
        parallel=_read_parallel_flag(execution),
        client_capability_name=(client_capability[0] if client_capability else None),
        client_capability_min_version=(client_capability[1] if client_capability else None),
    )


def is_enabled(manifest: dict[str, Any]) -> bool:
    state = manifest.get("state")
    if not isinstance(state, dict):
        return True
    enabled = state.get("enabled")
    return enabled if isinstance(enabled, bool) else True


def example_summary(index: int, example: dict[str, Any]) -> ToolExampleSummary:
    return ToolExampleSummary(
        index=index,
        title=example_title(example),
        inject_content=example_inject_content(example),
    )


def example_detail(index: int, example: dict[str, Any]) -> ToolExampleDetail:
    return ToolExampleDetail(
        index=index,
        title=example_title(example),
        content=example_content(example),
        inject_content=example_inject_content(example),
    )


def example_title(example: dict[str, Any]) -> str:
    return _read_string(example, "title")


def example_content(example: dict[str, Any]) -> str:
    return _read_string(example, "content")


def example_enabled(example: dict[str, Any]) -> bool:
    value = example.get("enabled")
    return value if isinstance(value, bool) else True


def example_inject_content(example: dict[str, Any]) -> bool:
    value = example.get("inject_content")
    return value if isinstance(value, bool) else False


def standard_tool_description(
    description: str,
    examples: tuple[ToolExampleDetail, ...],
) -> str:
    if not examples:
        return description
    lines = [description, "", "应用示例："]
    for index, example in enumerate(examples, start=1):
        heading = f"{index}. {example.title}" if example.title else f"{index}."
        lines.append(heading)
        if example.inject_content and example.content:
            lines.append(example.content)
    return "\n".join(lines)


def normalize_tool_name(tool_name: str) -> str:
    normalized = tool_name.strip()
    if not normalized:
        raise BadRequestError("工具调用名称不能为空。")
    return normalized


def _read_json_object(file_path: Path) -> dict[str, Any]:
    payload = loads(file_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("JSON file must be an object.")
    return payload


def _read_examples(file_path: Path) -> tuple[tuple[int, dict[str, Any]], ...]:
    payload = loads(file_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list):
        raise ValueError("examples.json must be an array.")

    examples: list[tuple[int, dict[str, Any]]] = []
    for index, item in enumerate(payload, start=1):
        if isinstance(item, dict):
            examples.append((index, item))
    return tuple(examples)


def _read_dynamic_flag(loading: object) -> bool:
    if not isinstance(loading, dict):
        return True
    dynamic = loading.get("dynamic")
    return dynamic if isinstance(dynamic, bool) else True


def _read_parallel_flag(execution: object) -> bool:
    if not isinstance(execution, dict):
        raise BadRequestError("tool.json 缺少 execution.parallel。")
    parallel = execution.get("parallel")
    if not isinstance(parallel, bool):
        raise BadRequestError("tool.json 的 execution.parallel 必须是布尔值。")
    return parallel


def _validate_runtime(runtime: object) -> None:
    if not isinstance(runtime, dict):
        raise BadRequestError("tool.json 缺少 runtime。")
    runtime_type = runtime.get("type")
    if not isinstance(runtime_type, str) or not runtime_type.strip():
        raise BadRequestError("tool.json 的 runtime.type 不能为空。")
    timeout_seconds = runtime.get("timeout_seconds")
    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
        raise BadRequestError("tool.json 的 runtime.timeout_seconds 必须是正整数。")
    if runtime_type.strip().lower() == "client":
        _require_client_capability(runtime.get("client_capability"))
        return
    entry = runtime.get("entry")
    if not isinstance(entry, str) or not entry.strip():
        raise BadRequestError("Python 工具必须声明 runtime.entry。")


def _read_client_capability(runtime: object) -> tuple[str, int] | None:
    if not isinstance(runtime, dict):
        return None
    if str(runtime.get("type") or "").strip().lower() != "client":
        return None
    return _require_client_capability(runtime.get("client_capability"))


def _require_client_capability(value: object) -> tuple[str, int]:
    if not isinstance(value, dict):
        raise BadRequestError("客户端工具必须声明 runtime.client_capability。")
    name = value.get("name")
    min_version = value.get("min_version")
    if not isinstance(name, str) or not name.strip():
        raise BadRequestError("runtime.client_capability.name 不能为空。")
    if not isinstance(min_version, int) or isinstance(min_version, bool) or min_version <= 0:
        raise BadRequestError("runtime.client_capability.min_version 必须是正整数。")
    return name.strip(), min_version


def _read_parameter_names(input_schema: dict[str, Any]) -> list[str]:
    properties = input_schema.get("properties")
    if not isinstance(properties, dict):
        return []
    return [key for key in properties.keys() if isinstance(key, str)]


def _read_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) else ""


def _read_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]
