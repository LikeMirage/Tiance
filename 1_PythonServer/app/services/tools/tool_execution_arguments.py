from __future__ import annotations

from json import dumps, loads
import re
from typing import Any


def parse_tool_arguments(arguments: str) -> dict[str, Any]:
    raw = arguments.strip() if isinstance(arguments, str) else ""
    if not raw:
        return {}
    try:
        payload = loads(raw)
    except ValueError as exc:
        raise ValueError(f"工具参数不是合法 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("工具参数必须是 JSON 对象。")
    return payload


def validate_tool_arguments(arguments: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    if not isinstance(schema, dict) or not schema:
        return []
    errors: list[str] = []
    _validate_schema_value(arguments, schema, path="参数", errors=errors, root_schema=schema)
    return errors


def _validate_schema_value(
    value: Any,
    schema: dict[str, Any],
    *,
    path: str,
    errors: list[str],
    root_schema: dict[str, Any],
) -> None:
    reference = schema.get("$ref")
    if isinstance(reference, str):
        resolved = _resolve_local_reference(reference, root_schema)
        if resolved is None:
            errors.append(f"{path} 使用了无法解析的 schema 引用：{reference}。")
        else:
            _validate_schema_value(value, resolved, path=path, errors=errors, root_schema=root_schema)
        return

    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for branch in all_of:
            if isinstance(branch, dict):
                _validate_schema_value(value, branch, path=path, errors=errors, root_schema=root_schema)

    condition = schema.get("if")
    if isinstance(condition, dict):
        branch_key = "then" if _schema_matches(value, condition, root_schema) else "else"
        branch = schema.get(branch_key)
        if isinstance(branch, dict):
            _validate_schema_value(value, branch, path=path, errors=errors, root_schema=root_schema)

    one_of = schema.get("oneOf")
    if isinstance(one_of, list):
        matches = [branch for branch in one_of if isinstance(branch, dict) and _schema_matches(value, branch, root_schema)]
        if len(matches) != 1:
            errors.append(f"{path} 必须且只能匹配一种参数结构。")
            return
        _validate_schema_value(value, matches[0], path=path, errors=errors, root_schema=root_schema)
        return

    any_of = schema.get("anyOf")
    if isinstance(any_of, list) and not any(
        isinstance(branch, dict) and _schema_matches(value, branch, root_schema)
        for branch in any_of
    ):
        errors.append(f"{path} 不符合任何允许的参数结构。")
        return

    denied = schema.get("not")
    if isinstance(denied, dict) and _schema_matches(value, denied, root_schema):
        errors.append(f"{path} 包含互斥参数。")
        return

    expected_types = _schema_types(schema.get("type"))
    if expected_types and not _matches_schema_type(value, expected_types):
        errors.append(f"{path} 类型应为 {_format_schema_types(expected_types)}。")
        return

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values and value not in enum_values:
        errors.append(f"{path} 必须是 {', '.join(map(str, enum_values))} 之一。")
        return

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path} 必须是 {schema['const']}。")
        return

    if isinstance(value, dict):
        _validate_object_value(value, schema, path=path, errors=errors, root_schema=root_schema)
    elif isinstance(value, list):
        _validate_array_value(value, schema, path=path, errors=errors, root_schema=root_schema)
    elif isinstance(value, str):
        _validate_string_value(value, schema, path=path, errors=errors)
    elif _is_number(value):
        _validate_number_value(value, schema, path=path, errors=errors)


def _validate_object_value(
    value: dict[str, Any],
    schema: dict[str, Any],
    *,
    path: str,
    errors: list[str],
    root_schema: dict[str, Any],
) -> None:
    min_properties = _optional_int(schema.get("minProperties"))
    max_properties = _optional_int(schema.get("maxProperties"))
    if min_properties is not None and len(value) < min_properties:
        errors.append(f"{path} 至少需要 {min_properties} 个字段。")
    if max_properties is not None and len(value) > max_properties:
        errors.append(f"{path} 最多允许 {max_properties} 个字段。")
    properties = schema.get("properties")
    properties = properties if isinstance(properties, dict) else {}
    required = schema.get("required")
    required_names = [item for item in required if isinstance(item, str)] if isinstance(required, list) else []
    for name in required_names:
        if name not in value:
            errors.append(f"{path}.{name} 为必填参数。")

    additional_properties = schema.get("additionalProperties")
    if additional_properties is False:
        for name in value:
            if name not in properties:
                errors.append(f"{path}.{name} 不是允许的参数。")

    for name, child_schema in properties.items():
        if name not in value or not isinstance(child_schema, dict):
            continue
        _validate_schema_value(
            value[name], child_schema, path=f"{path}.{name}", errors=errors, root_schema=root_schema
        )


def _validate_array_value(
    value: list[Any],
    schema: dict[str, Any],
    *,
    path: str,
    errors: list[str],
    root_schema: dict[str, Any],
) -> None:
    min_items = _optional_int(schema.get("minItems"))
    max_items = _optional_int(schema.get("maxItems"))
    if min_items is not None and len(value) < min_items:
        errors.append(f"{path} 至少需要 {min_items} 项。")
    if max_items is not None and len(value) > max_items:
        errors.append(f"{path} 最多允许 {max_items} 项。")
    if schema.get("uniqueItems") is True:
        normalized_items = [dumps(item, ensure_ascii=False, sort_keys=True) for item in value]
        if len(normalized_items) != len(set(normalized_items)):
            errors.append(f"{path} 不允许重复项。")

    item_schema = schema.get("items")
    if isinstance(item_schema, dict):
        for index, item in enumerate(value):
            _validate_schema_value(
                item, item_schema, path=f"{path}[{index}]", errors=errors, root_schema=root_schema
            )


def _validate_string_value(
    value: str,
    schema: dict[str, Any],
    *,
    path: str,
    errors: list[str],
) -> None:
    min_length = _optional_int(schema.get("minLength"))
    max_length = _optional_int(schema.get("maxLength"))
    if min_length is not None and len(value) < min_length:
        errors.append(f"{path} 长度不能小于 {min_length}。")
    if max_length is not None and len(value) > max_length:
        errors.append(f"{path} 长度不能大于 {max_length}。")
    pattern = schema.get("pattern")
    if isinstance(pattern, str):
        try:
            if re.search(pattern, value) is None:
                errors.append(f"{path} 格式不正确。")
        except re.error:
            errors.append(f"{path} 的 schema pattern 无效。")


def _validate_number_value(
    value: int | float,
    schema: dict[str, Any],
    *,
    path: str,
    errors: list[str],
) -> None:
    minimum = _optional_float(schema.get("minimum"))
    maximum = _optional_float(schema.get("maximum"))
    exclusive_minimum = _optional_float(schema.get("exclusiveMinimum"))
    if minimum is not None and value < minimum:
        errors.append(f"{path} 不能小于 {minimum:g}。")
    if maximum is not None and value > maximum:
        errors.append(f"{path} 不能大于 {maximum:g}。")
    if exclusive_minimum is not None and value <= exclusive_minimum:
        errors.append(f"{path} 必须大于 {exclusive_minimum:g}。")


def _schema_matches(value: Any, schema: dict[str, Any], root_schema: dict[str, Any]) -> bool:
    branch_errors: list[str] = []
    _validate_schema_value(
        value,
        schema,
        path="参数",
        errors=branch_errors,
        root_schema=root_schema,
    )
    return not branch_errors


def _resolve_local_reference(reference: str, root_schema: dict[str, Any]) -> dict[str, Any] | None:
    if not reference.startswith("#/"):
        return None
    current: Any = root_schema
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current if isinstance(current, dict) else None


def _schema_types(value: object) -> tuple[str, ...]:
    if isinstance(value, str) and value:
        return (value,)
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, str) and item)
    return ()


def _matches_schema_type(value: Any, schema_types: tuple[str, ...]) -> bool:
    if "null" in schema_types and value is None:
        return True
    return any(
        (schema_type == "object" and isinstance(value, dict))
        or (schema_type == "array" and isinstance(value, list))
        or (schema_type == "string" and isinstance(value, str))
        or (schema_type == "boolean" and isinstance(value, bool))
        or (schema_type == "integer" and isinstance(value, int) and not isinstance(value, bool))
        or (schema_type == "number" and _is_number(value))
        for schema_type in schema_types
    )


def _format_schema_types(schema_types: tuple[str, ...]) -> str:
    return " 或 ".join(schema_types)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
