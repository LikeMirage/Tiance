from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any

from tiance_runtime import run_tool


CALL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
REQUIREMENT_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?P<extras>\[[A-Za-z0-9_,.\-\s]+\])?"
    r"(?P<specifier>.*)$"
)
SPECIFIER_RE = re.compile(r"^(==|!=|>=|<=|~=|>|<)\s*([^,\s]+)$")


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def ok(summary: str, data: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    return {"ok": True, "summary": summary, "data": data, "warnings": warnings or []}


def fail(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "error": f"{code}: {message}",
        "error_info": {"code": code, "message": message, "details": details or {}},
        "warnings": [],
    }


def workspace_root() -> Path:
    raw = os.environ.get("TIANCE_WORKSPACE_ROOT") or os.environ.get("WORKSPACE_ROOT") or os.getcwd()
    return Path(raw).expanduser().resolve(strict=False)


def read_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def read_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def resolve_tools_root(value: Any) -> Path:
    root = workspace_root()
    raw = str(value or "").strip()
    if raw:
        path = Path(raw).expanduser()
        candidate = path if path.is_absolute() else root / path
    else:
        configured = str(os.environ.get("TIANCE_TOOLS_ROOT") or "").strip()
        if not configured:
            raise ToolError(
                "TOOLS_ROOT_NOT_CONFIGURED",
                "宿主没有提供真实工具根目录。",
                {"workspace_root": str(root)},
            )
        candidate = Path(configured).expanduser()

    resolved = candidate.resolve(strict=False)
    if resolved.is_dir():
        return resolved
    raise ToolError(
        "TOOLS_ROOT_NOT_FOUND",
        "工具根目录不存在。",
        {
            "tools_root": str(resolved),
            "workspace_root": str(root),
        },
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def issue(
    issues: list[dict[str, Any]],
    severity: str,
    code: str,
    message: str,
    *,
    path: Path | None = None,
    tool_name: str | None = None,
) -> None:
    item: dict[str, Any] = {"severity": severity, "code": code, "message": message}
    if path is not None:
        item["path"] = str(path)
    if tool_name:
        item["tool_name"] = tool_name
    issues.append(item)


def validate_tool_folder(
    folder: Path,
    *,
    expected_toolset_id: str,
    include_disabled: bool,
    issues: list[dict[str, Any]],
) -> dict[str, Any] | None:
    tool_json_path = folder / ".tool" / "tool.json"
    registry_path = folder / ".tool" / "registry.json"
    input_schema_path = folder / ".tool" / "input.schema.json"
    output_schema_path = folder / ".tool" / "output.schema.json"
    examples_path = folder / ".tool" / "examples.json"
    requirements_path = folder / "program" / "requirements.txt"
    for required_path in (tool_json_path, registry_path, input_schema_path, output_schema_path, examples_path):
        if not required_path.exists():
            issue(issues, "error", "MISSING_FILE", "缺少标准工具文件。", path=required_path)

    try:
        manifest = read_json(tool_json_path)
    except Exception as exc:
        issue(issues, "error", "INVALID_TOOL_JSON", f"tool.json 不是合法 JSON：{exc}", path=tool_json_path)
        return None
    if not isinstance(manifest, dict):
        issue(issues, "error", "INVALID_TOOL_JSON", "tool.json 必须是 JSON 对象。", path=tool_json_path)
        return None

    tool_name = str(manifest.get("name") or "").strip()
    enabled = read_manifest_enabled(manifest)
    if not include_disabled and not enabled:
        return None

    if not CALL_NAME_RE.match(tool_name):
        issue(issues, "error", "INVALID_TOOL_NAME", "工具调用名必须是小写英文开头，只包含小写英文、数字和下划线。", path=tool_json_path, tool_name=tool_name)
    if not string_value(manifest.get("display_name")):
        issue(issues, "error", "MISSING_DISPLAY_NAME", "display_name 不能为空。", path=tool_json_path, tool_name=tool_name)
    if not string_value(manifest.get("description")):
        issue(issues, "warning", "MISSING_DESCRIPTION", "description 为空会降低工具可理解性。", path=tool_json_path, tool_name=tool_name)
    validate_execution(manifest, tool_json_path, tool_name, issues)
    validate_manifest_files(manifest, tool_json_path, tool_name, issues)
    validate_runtime(manifest, folder, tool_json_path, tool_name, issues)
    validate_registry(registry_path, folder.name, expected_toolset_id, tool_name, issues)
    validate_schema_file(input_schema_path, tool_name, issues, input_schema=True)
    validate_schema_file(output_schema_path, tool_name, issues, input_schema=False)
    validate_examples(examples_path, tool_name, issues)
    runtime = manifest.get("runtime")
    runtime_type = str(runtime.get("type") or "python").strip().lower() if isinstance(runtime, dict) else "python"
    if runtime_type == "python":
        if not requirements_path.exists():
            issue(issues, "error", "MISSING_FILE", "缺少标准工具文件。", path=requirements_path)
        validate_requirements(requirements_path, tool_name, issues)
        if not (folder / "assets").is_dir():
            issue(issues, "warning", "MISSING_ASSETS_DIR", "建议保留 assets 目录，即使当前为空。", path=folder / "assets", tool_name=tool_name)
    return {
        "name": tool_name,
        "display_name": string_value(manifest.get("display_name")),
        "enabled": enabled,
        "folder": folder.name,
    }


def read_manifest_enabled(manifest: dict[str, Any]) -> bool:
    state = manifest.get("state")
    if not isinstance(state, dict):
        return True
    value = state.get("enabled")
    return value if isinstance(value, bool) else True


def string_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def validate_execution(
    manifest: dict[str, Any],
    path: Path,
    tool_name: str,
    issues: list[dict[str, Any]],
) -> None:
    execution = manifest.get("execution")
    if not isinstance(execution, dict) or not isinstance(execution.get("parallel"), bool):
        issue(
            issues,
            "error",
            "INVALID_EXECUTION_PARALLEL",
            "tool.json 必须明确声明布尔值 execution.parallel。",
            path=path,
            tool_name=tool_name,
        )


def validate_manifest_files(manifest: dict[str, Any], path: Path, tool_name: str, issues: list[dict[str, Any]]) -> None:
    files = manifest.get("files")
    expected = {
        "input_schema": ".tool/input.schema.json",
        "output_schema": ".tool/output.schema.json",
        "examples": ".tool/examples.json",
    }
    if not isinstance(files, dict):
        issue(issues, "warning", "MISSING_FILES_MAP", "tool.json 建议包含 files 映射。", path=path, tool_name=tool_name)
        return
    for key, value in expected.items():
        if files.get(key) != value:
            issue(issues, "warning", "NONSTANDARD_FILES_MAP", f"files.{key} 建议为 {value}。", path=path, tool_name=tool_name)


def validate_runtime(manifest: dict[str, Any], folder: Path, path: Path, tool_name: str, issues: list[dict[str, Any]]) -> None:
    runtime = manifest.get("runtime")
    if not isinstance(runtime, dict):
        issue(issues, "error", "MISSING_RUNTIME", "tool.json 缺少 runtime。", path=path, tool_name=tool_name)
        return
    runtime_type = str(runtime.get("type") or "python").strip().lower()
    if runtime_type in {"client", "internal"}:
        return
    if runtime_type != "python":
        issue(issues, "error", "UNSUPPORTED_RUNTIME", "runtime.type 必须是 python、client 或 internal。", path=path, tool_name=tool_name)
        return
    entry = string_value(runtime.get("entry"))
    if not entry:
        issue(issues, "error", "MISSING_ENTRY", "runtime.entry 不能为空。", path=path, tool_name=tool_name)
        return
    entry_path = (folder / entry.replace("\\", "/").strip("/")).resolve(strict=False)
    try:
        entry_path.relative_to(folder.resolve(strict=False))
    except ValueError:
        issue(issues, "error", "ENTRY_OUTSIDE_TOOL", "runtime.entry 不能指向工具目录外。", path=path, tool_name=tool_name)
        return
    if not entry_path.is_file():
        issue(issues, "error", "ENTRY_NOT_FOUND", "runtime.entry 指向的入口文件不存在。", path=entry_path, tool_name=tool_name)


def validate_registry(path: Path, folder_id: str, toolset_id: str, tool_name: str, issues: list[dict[str, Any]]) -> None:
    try:
        registry = read_json(path)
    except Exception as exc:
        issue(issues, "error", "INVALID_REGISTRY_JSON", f"registry.json 不是合法 JSON：{exc}", path=path, tool_name=tool_name)
        return
    if not isinstance(registry, dict):
        issue(issues, "error", "INVALID_REGISTRY_JSON", "registry.json 必须是 JSON 对象。", path=path, tool_name=tool_name)
        return
    if registry.get("id") != folder_id:
        issue(issues, "error", "REGISTRY_ID_MISMATCH", "registry.json 的 id 和工具文件夹名不一致。", path=path, tool_name=tool_name)
    if registry.get("toolset_id") != toolset_id:
        issue(issues, "error", "REGISTRY_TOOLSET_MISMATCH", "registry.json 的 toolset_id 和所在工具集不一致。", path=path, tool_name=tool_name)


def validate_schema_file(path: Path, tool_name: str, issues: list[dict[str, Any]], *, input_schema: bool) -> None:
    try:
        schema = read_json(path)
    except Exception as exc:
        issue(issues, "error", "INVALID_SCHEMA_JSON", f"{path.name} 不是合法 JSON：{exc}", path=path, tool_name=tool_name)
        return
    if not isinstance(schema, dict):
        issue(issues, "error", "INVALID_SCHEMA_JSON", f"{path.name} 必须是 JSON 对象。", path=path, tool_name=tool_name)
        return
    if schema.get("type") != "object":
        issue(issues, "warning", "SCHEMA_TYPE_NOT_OBJECT", "工具输入输出 schema 根级建议使用 type=object。", path=path, tool_name=tool_name)
    props = schema.get("properties")
    if not isinstance(props, dict):
        issue(issues, "error", "SCHEMA_MISSING_PROPERTIES", "schema.properties 必须是对象。", path=path, tool_name=tool_name)
        return
    required = schema.get("required", [])
    if required is not None and not isinstance(required, list):
        issue(issues, "error", "INVALID_REQUIRED", "required 必须是数组。", path=path, tool_name=tool_name)
        required = []
    for name in required or []:
        if not isinstance(name, str) or name not in props:
            issue(issues, "error", "REQUIRED_FIELD_MISSING", f"required 字段 {name!r} 不存在于 properties。", path=path, tool_name=tool_name)
    if input_schema and schema.get("additionalProperties") is not False:
        issue(issues, "warning", "INPUT_ALLOWS_EXTRA_FIELDS", "输入 schema 建议设置 additionalProperties=false。", path=path, tool_name=tool_name)
    if not input_schema and "ok" not in props:
        issue(issues, "warning", "OUTPUT_MISSING_OK", "输出 schema 建议声明 ok 字段。", path=path, tool_name=tool_name)
    for prop_name, prop_schema in props.items():
        if not isinstance(prop_schema, dict):
            issue(issues, "error", "INVALID_PROPERTY_SCHEMA", f"参数 {prop_name} 的 schema 必须是对象。", path=path, tool_name=tool_name)
            continue
        validate_enum_options(prop_name, prop_schema, path, tool_name, issues)


def validate_enum_options(prop_name: str, schema: dict[str, Any], path: Path, tool_name: str, issues: list[dict[str, Any]]) -> None:
    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values:
        options = schema.get("options")
        if isinstance(options, list):
            option_values = [item.get("value") for item in options if isinstance(item, dict)]
            if option_values != enum_values:
                issue(issues, "warning", "ENUM_OPTIONS_MISMATCH", f"{prop_name} 的 enum 和 options.value 不一致。", path=path, tool_name=tool_name)
        else:
            issue(issues, "warning", "ENUM_WITHOUT_OPTIONS", f"{prop_name} 使用 enum 时建议提供 options 说明。", path=path, tool_name=tool_name)
        if "default" in schema and schema["default"] not in enum_values:
            issue(issues, "warning", "DEFAULT_NOT_IN_ENUM", f"{prop_name} 的 default 不在 enum 中。", path=path, tool_name=tool_name)
    items = schema.get("items")
    if isinstance(items, dict):
        validate_enum_options(f"{prop_name}[]", items, path, tool_name, issues)


def validate_examples(path: Path, tool_name: str, issues: list[dict[str, Any]]) -> None:
    try:
        examples = read_json(path)
    except Exception as exc:
        issue(issues, "error", "INVALID_EXAMPLES_JSON", f"examples.json 不是合法 JSON：{exc}", path=path, tool_name=tool_name)
        return
    if not isinstance(examples, list):
        issue(issues, "error", "INVALID_EXAMPLES_JSON", "examples.json 必须是数组。", path=path, tool_name=tool_name)
        return
    if not examples:
        issue(issues, "warning", "NO_EXAMPLES", "建议至少提供一个应用场景。", path=path, tool_name=tool_name)
    for index, example in enumerate(examples, start=1):
        if not isinstance(example, dict):
            issue(issues, "error", "INVALID_EXAMPLE", f"第 {index} 个示例必须是对象。", path=path, tool_name=tool_name)
            continue
        if not string_value(example.get("title")):
            issue(issues, "warning", "EXAMPLE_MISSING_TITLE", f"第 {index} 个示例缺少标题。", path=path, tool_name=tool_name)
        if not string_value(example.get("content")):
            issue(issues, "warning", "EXAMPLE_MISSING_CONTENT", f"第 {index} 个示例缺少内容。", path=path, tool_name=tool_name)


def validate_requirements(path: Path, tool_name: str, issues: list[dict[str, Any]]) -> None:
    if not path.exists():
        return
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = re.sub(r"\s+#.*$", "", raw_line).strip()
        if not line:
            continue
        if line.startswith("-") or "://" in line or "@" in line or ";" in line:
            issue(issues, "error", "UNSUPPORTED_REQUIREMENT", f"requirements.txt 第 {line_number} 行不是当前支持的普通依赖格式。", path=path, tool_name=tool_name)
            continue
        match = REQUIREMENT_RE.match(line)
        if match is None:
            issue(issues, "error", "INVALID_REQUIREMENT", f"requirements.txt 第 {line_number} 行格式无效。", path=path, tool_name=tool_name)
            continue
        specifier = re.sub(r"\s+", "", match.group("specifier") or "")
        if specifier and not all(SPECIFIER_RE.match(part) for part in specifier.split(",")):
            issue(issues, "error", "INVALID_REQUIREMENT_SPECIFIER", f"requirements.txt 第 {line_number} 行版本范围格式无效。", path=path, tool_name=tool_name)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        tools_root = resolve_tools_root(payload.get("tools_root"))
        target_tool_name = string_value(payload.get("tool_name"))
        include_disabled = read_bool(payload.get("include_disabled"), True)
        max_issues = read_int(payload.get("max_issues"), 200, 1, 1000)
        issues: list[dict[str, Any]] = []
        scanned: list[dict[str, Any]] = []
        names: dict[str, list[str]] = {}

        for toolset_root in sorted(path for path in tools_root.iterdir() if path.is_dir()):
            toolset_manifest_path = toolset_root / "toolset.json"
            try:
                toolset_manifest = read_json(toolset_manifest_path)
            except Exception as exc:
                issue(issues, "error", "INVALID_TOOLSET_JSON", f"toolset.json 无效：{exc}", path=toolset_manifest_path)
                continue
            if not isinstance(toolset_manifest, dict):
                issue(issues, "error", "INVALID_TOOLSET_JSON", "toolset.json 必须是 JSON 对象。", path=toolset_manifest_path)
                continue
            toolset_id = string_value(toolset_manifest.get("id")) or toolset_root.name
            folders_root = toolset_root / "folders"
            if not folders_root.is_dir():
                continue
            for folder in sorted(path for path in folders_root.iterdir() if path.is_dir()):
                if target_tool_name and not folder_matches_tool_name(folder, target_tool_name):
                    continue
                info = validate_tool_folder(
                    folder,
                    expected_toolset_id=toolset_id,
                    include_disabled=include_disabled,
                    issues=issues,
                )
                if info is None:
                    continue
                if target_tool_name and info["name"] != target_tool_name:
                    continue
                scanned.append(info)
                names.setdefault(info["name"], []).append(info["folder"])

        if target_tool_name and not scanned:
            issue(issues, "error", "TOOL_NOT_FOUND", f"没有找到工具 {target_tool_name}。", tool_name=target_tool_name)
        for name, folders in names.items():
            if name and len(folders) > 1:
                issue(issues, "error", "DUPLICATE_TOOL_NAME", f"工具调用名重复：{name}。", tool_name=name)

        error_count = sum(1 for item in issues if item["severity"] == "error")
        warning_count = sum(1 for item in issues if item["severity"] == "warning")
        status = "fail" if error_count else "warning" if warning_count else "pass"
        shown_issues = issues[:max_issues]
        summary = f"检查 {len(scanned)} 个工具：{error_count} 个错误，{warning_count} 个警告。"
        return ok(summary, {
            "status": status,
            "tools_root": str(tools_root),
            "scanned_tools": len(scanned),
            "tools": scanned,
            "error_count": error_count,
            "warning_count": warning_count,
            "issue_count": len(issues),
            "issues": shown_issues,
            "truncated": len(issues) > len(shown_issues),
        })
    except ToolError as exc:
        return fail(exc.code, exc.message, exc.details)


def folder_matches_tool_name(folder: Path, tool_name: str) -> bool:
    try:
        manifest = read_json(folder / ".tool" / "tool.json")
    except Exception:
        return False
    if not isinstance(manifest, dict):
        return False
    return string_value(manifest.get("name")) == tool_name


if __name__ == "__main__":
    run_tool(run)
