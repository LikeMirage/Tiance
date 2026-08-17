from __future__ import annotations

from datetime import UTC, datetime
from json import dumps, loads

from app.core.errors import BadRequestError
from app.infra.tools.tool_project_config_constants import (
    TOOL_EXAMPLES_FILE,
    TOOL_INPUT_SCHEMA_FILE,
    TOOL_OUTPUT_SCHEMA_FILE,
)

def _normalize_schema_parameter_options(input_schema: dict[str, object]) -> bool:
    properties = input_schema.get("properties")
    if not isinstance(properties, dict):
        return False

    changed = False
    for schema in properties.values():
        if not isinstance(schema, dict):
            continue
        normalized = _normalize_parameter_options(schema.get("enum"), schema.get("options"))
        if normalized is None:
            if "options" in schema:
                schema.pop("options", None)
                changed = True
            continue
        enum_values, options = normalized
        if schema.get("enum") != enum_values:
            schema["enum"] = enum_values
            changed = True
        if schema.get("options") != options:
            schema["options"] = options
            changed = True

    return changed


def _normalize_tool_manifest_files(manifest: dict[str, object]) -> bool:
    next_files = {
        "input_schema": TOOL_INPUT_SCHEMA_FILE,
        "output_schema": TOOL_OUTPUT_SCHEMA_FILE,
        "examples": TOOL_EXAMPLES_FILE,
    }
    if manifest.get("files") != next_files:
        manifest["files"] = next_files
        return True
    return False


def _normalize_tool_runtime(manifest: dict[str, object]) -> bool:
    runtime = manifest.get("runtime")
    if not isinstance(runtime, dict):
        raise BadRequestError("tool.json 缺少 runtime。")

    changed = False
    if not isinstance(runtime.get("type"), str) or not str(runtime.get("type") or "").strip():
        raise BadRequestError("tool.json 的 runtime.type 不能为空。")
    runtime_type = str(runtime.get("type") or "").strip().lower()

    raw_entry = runtime.get("entry")
    entry = raw_entry if isinstance(raw_entry, str) else ""
    normalized_entry = entry.strip().replace("\\", "/").strip("/")
    if runtime_type == "python":
        if not normalized_entry:
            raise BadRequestError("Python 工具必须声明 runtime.entry。")
        if runtime.get("entry") != normalized_entry:
            runtime["entry"] = normalized_entry
            changed = True
    elif "entry" in runtime:
        runtime.pop("entry", None)
        changed = True

    timeout_seconds = runtime.get("timeout_seconds")
    if (
        not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or timeout_seconds <= 0
    ):
        raise BadRequestError("tool.json 的 runtime.timeout_seconds 必须是正整数。")

    if runtime_type == "client":
        capability = runtime.get("client_capability")
        if not isinstance(capability, dict):
            raise BadRequestError("客户端工具必须声明 runtime.client_capability。")
        name = capability.get("name")
        min_version = capability.get("min_version")
        if not isinstance(name, str) or not name.strip():
            raise BadRequestError("runtime.client_capability.name 不能为空。")
        if (
            not isinstance(min_version, int)
            or isinstance(min_version, bool)
            or min_version <= 0
        ):
            raise BadRequestError("runtime.client_capability.min_version 必须是正整数。")

    return changed


def _normalize_tool_standard_file_path(target_path: str) -> str:
    return target_path.strip().replace("\\", "/").strip("/")


def _load_json_content(content: str, *, filename: str) -> object:
    try:
        return loads(_strip_json_bom(content))
    except ValueError as exc:
        raise BadRequestError(f"{filename} 必须是合法 JSON。") from exc


def _strip_json_bom(content: str) -> str:
    return content[1:] if content.startswith("\ufeff") else content


def _normalize_input_schema_content(content: str) -> str:
    payload = _load_json_content(content, filename=TOOL_INPUT_SCHEMA_FILE)
    if not isinstance(payload, dict):
        raise BadRequestError("input.schema.json 必须是 JSON 对象。")
    if payload.get("type") is None:
        payload["type"] = "object"
    properties = payload.get("properties")
    if not isinstance(properties, dict):
        payload["properties"] = {}
    if not isinstance(payload.get("required"), list):
        payload["required"] = []
    _normalize_schema_parameter_options(payload)
    return dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _normalize_output_schema_content(content: str) -> str:
    payload = _load_json_content(content, filename=TOOL_OUTPUT_SCHEMA_FILE)
    if not isinstance(payload, dict):
        raise BadRequestError("output.schema.json 必须是 JSON 对象。")
    if payload.get("type") is None:
        payload["type"] = "object"
    properties = payload.get("properties")
    if not isinstance(properties, dict):
        payload["properties"] = {}
    if not isinstance(payload.get("required"), list):
        payload["required"] = []
    return dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _normalize_examples_content(content: str) -> str:
    payload = _load_json_content(content, filename=TOOL_EXAMPLES_FILE)
    if not isinstance(payload, list):
        raise BadRequestError("examples.json 必须是 JSON 数组。")
    examples = _normalize_tool_examples_value(payload)
    return dumps(examples, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _normalize_parameter_options(
    enum_value: object,
    options_value: object,
) -> tuple[list[str], list[dict[str, str]]] | None:
    enum_values = _normalize_string_list(enum_value)
    option_items = _normalize_parameter_option_items(options_value)
    descriptions = {item["value"]: item["description"] for item in option_items}

    ordered_values: list[str] = []
    seen_values: set[str] = set()
    for value in [*enum_values, *(item["value"] for item in option_items)]:
        if value in seen_values:
            continue
        seen_values.add(value)
        ordered_values.append(value)

    if not ordered_values:
        return None

    return (
        ordered_values,
        [
            {
                "value": value,
                "description": descriptions.get(value, ""),
            }
            for value in ordered_values
        ],
    )


def _normalize_parameter_option_items(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []

    options: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        option_value = ""
        description = ""
        raw_value = item.get("value")
        if isinstance(raw_value, str):
            option_value = raw_value.strip()
        raw_description = item.get("description")
        if isinstance(raw_description, str):
            description = raw_description.strip()
        if option_value:
            options.append(
                {
                    "value": option_value,
                    "description": description,
                }
            )

    return options


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []

    result: list[str] = []
    seen_values: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        normalized = item.strip()
        if not normalized or normalized in seen_values:
            continue
        seen_values.add(normalized)
        result.append(normalized)
    return result


def _normalize_tool_loading(manifest: dict[str, object]) -> bool:
    loading = manifest.get("loading")
    if not isinstance(loading, dict):
        manifest["loading"] = {
            "dynamic": True,
        }
        return True

    changed = False
    raw_dynamic = loading.get("dynamic")
    dynamic = raw_dynamic if isinstance(raw_dynamic, bool) else True
    if raw_dynamic is not dynamic:
        loading["dynamic"] = dynamic
        changed = True

    for key in list(loading.keys()):
        if key != "dynamic":
            loading.pop(key, None)
            changed = True

    return changed


def _normalize_tool_execution(manifest: dict[str, object]) -> bool:
    execution = manifest.get("execution")
    if not isinstance(execution, dict):
        raise BadRequestError("tool.json 缺少 execution.parallel。")

    raw_parallel = execution.get("parallel")
    if not isinstance(raw_parallel, bool):
        raise BadRequestError("tool.json 的 execution.parallel 必须是布尔值。")
    return False


def _normalize_tool_state(manifest: dict[str, object]) -> bool:
    state = manifest.get("state")
    if not isinstance(state, dict):
        manifest["state"] = {"enabled": True}
        return True

    changed = False
    enabled = state.get("enabled")
    if not isinstance(enabled, bool):
        state["enabled"] = True
        changed = True
    if "status" in state:
        state.pop("status", None)
        changed = True
    for key in list(state.keys()):
        if key != "enabled":
            state.pop(key, None)
            changed = True
    return changed


def _normalize_tool_examples_value(raw_examples: list[object]) -> list[dict[str, object]]:
    normalized_examples: list[dict[str, object]] = []
    for item in raw_examples:
        if not isinstance(item, dict):
            continue

        raw_title = item.get("title")
        raw_content = item.get("content")
        raw_enabled = item.get("enabled")
        raw_inject_content = item.get("inject_content")

        normalized_examples.append(
            {
                "title": raw_title if isinstance(raw_title, str) else "",
                "content": raw_content if isinstance(raw_content, str) else "",
                "enabled": raw_enabled if isinstance(raw_enabled, bool) else True,
                "inject_content": (
                    raw_inject_content if isinstance(raw_inject_content, bool) else False
                ),
            }
        )
    return normalized_examples


def _normalize_tool_call_name(name: str | None) -> str:
    normalized = (name or "").strip()
    if not normalized:
        return ""
    if not _is_tool_call_name(normalized):
        raise BadRequestError("工具调用名称只能使用小写英文、数字和下划线，并且必须以英文开头。")
    return normalized


def _is_tool_call_name(name: str) -> bool:
    if not name:
        return False
    if not ("a" <= name[0] <= "z"):
        return False
    return all(("a" <= char <= "z") or ("0" <= char <= "9") or char == "_" for char in name)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
