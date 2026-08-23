from __future__ import annotations

from copy import deepcopy

TOOL_PARAMETER_PERMISSION_TYPE_KEY = "permission_type"

TOOL_PARAMETER_PERMISSION_TYPES = frozenset(
    {
        "none",
        "filesystem_read",
        "filesystem_write",
        "filesystem_delete",
        "program_execute",
        "process_control",
        "runtime_modify",
        "network_access",
        "credential_use",
        "external_data_read",
        "external_data_modify",
        "tiance_data_read",
        "tiance_data_write",
        "tiance_data_delete",
        "ui_control",
    }
)


def schema_without_parameter_permission_types(
    input_schema: dict[str, object],
) -> dict[str, object]:
    """Return the provider-facing JSON Schema without Tiance-only metadata."""
    result = deepcopy(input_schema)
    properties = result.get("properties")
    if not isinstance(properties, dict):
        return result
    for schema in properties.values():
        if isinstance(schema, dict):
            schema.pop(TOOL_PARAMETER_PERMISSION_TYPE_KEY, None)
    return result
