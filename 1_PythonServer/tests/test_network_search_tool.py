from __future__ import annotations

from json import loads

from tests.formal_tool_paths import resolve_formal_tool_root


TOOL_ROOT = resolve_formal_tool_root("network_search")


def _read_json(relative_path: str):
    return loads((TOOL_ROOT / relative_path).read_text(encoding="utf-8"))


def test_network_search_remains_an_ordinary_eager_python_tool():
    manifest = _read_json(".tool/tool.json")

    assert manifest["name"] == "network_search"
    assert manifest["runtime"]["type"] == "python"
    assert manifest["loading"]["dynamic"] is False


def test_network_search_accepts_only_query_and_has_no_hidden_collection_limits():
    input_schema = _read_json(".tool/input.schema.json")
    output_schema = _read_json(".tool/output.schema.json")

    assert set(input_schema["properties"]) == {"query"}
    assert input_schema["required"] == ["query"]
    assert "maxLength" not in input_schema["properties"]["query"]
    assert "maxItems" not in str(output_schema)


def test_network_search_tool_has_no_api_key_configuration():
    assert not (TOOL_ROOT / "config.json").exists()
    assert "api_key" not in (TOOL_ROOT / "program" / "main.py").read_text(
        encoding="utf-8"
    ).casefold()
