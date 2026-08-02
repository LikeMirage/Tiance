from __future__ import annotations

from json import dumps, loads
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
    _validate_schema_value(arguments, schema, path="参数", errors=errors)
    return errors


def _validate_schema_value(
    value: Any,
    schema: dict[str, Any],
    *,
    path: str,
    errors: list[str],
) -> None:
    expected_types = _schema_types(schema.get("type"))
    if expected_types and not _matches_schema_type(value, expected_types):
        errors.append(f"{path} 类型应为 {_format_schema_types(expected_types)}。")
        return

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values and value not in enum_values:
        errors.append(f"{path} 必须是 {', '.join(map(str, enum_values))} 之一。")
        return

    if isinstance(value, dict):
        _validate_object_value(value, schema, path=path, errors=errors)
    elif isinstance(value, list):
        _validate_array_value(value, schema, path=path, errors=errors)
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
) -> None:
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
        _validate_schema_value(value[name], child_schema, path=f"{path}.{name}", errors=errors)


def _validate_array_value(
    value: list[Any],
    schema: dict[str, Any],
    *,
    path: str,
    errors: list[str],
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
            _validate_schema_value(item, item_schema, path=f"{path}[{index}]", errors=errors)


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


def _validate_number_value(
    value: int | float,
    schema: dict[str, Any],
    *,
    path: str,
    errors: list[str],
) -> None:
    minimum = _optional_float(schema.get("minimum"))
    maximum = _optional_float(schema.get("maximum"))
    if minimum is not None and value < minimum:
        errors.append(f"{path} 不能小于 {minimum:g}。")
    if maximum is not None and value > maximum:
        errors.append(f"{path} 不能大于 {maximum:g}。")


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
