from app.services.tools.tool_execution_arguments import validate_tool_arguments


def test_validator_resolves_local_refs_and_one_of_strict_objects():
    schema = {
        "type": "object",
        "properties": {
            "operation": {"$ref": "#/$defs/operation"},
        },
        "required": ["operation"],
        "$defs": {
            "operation": {
                "oneOf": [
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "type": {"const": "format"},
                            "color": {"type": "string", "pattern": "^[0-9A-F]{6}$"},
                        },
                        "required": ["type", "color"],
                    },
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "type": {"const": "replace"},
                            "content": {"type": "string", "minLength": 1},
                        },
                        "required": ["type", "content"],
                    },
                ]
            }
        },
    }

    assert validate_tool_arguments({"operation": {"type": "format", "color": "FF0000"}}, schema) == []
    assert validate_tool_arguments(
        {"operation": {"type": "format", "color": "red", "content": "不允许"}}, schema
    )


def test_validator_applies_if_then_and_exclusive_minimum():
    schema = {
        "type": "object",
        "properties": {
            "action": {"enum": ["inspect", "edit"]},
            "size": {"type": "number", "exclusiveMinimum": 0},
            "token": {"type": "string"},
        },
        "required": ["action", "size"],
        "allOf": [{
            "if": {"properties": {"action": {"const": "edit"}}, "required": ["action"]},
            "then": {"required": ["token"]},
        }],
    }

    assert validate_tool_arguments({"action": "edit", "size": 1, "token": "ok"}, schema) == []
    assert validate_tool_arguments({"action": "edit", "size": 0}, schema)
