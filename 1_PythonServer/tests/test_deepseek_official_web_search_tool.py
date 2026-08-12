from __future__ import annotations

import importlib.util
from json import loads
import sys

from tests.formal_tool_paths import resolve_formal_tool_root


TOOL_ROOT = resolve_formal_tool_root("deepseek_official_web_search")
MAIN_PATH = TOOL_ROOT / "program" / "main.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("deepseek_official_web_search_main", MAIN_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_deepseek_search_is_standalone_dynamic_python_tool():
    manifest = loads((TOOL_ROOT / ".tool" / "tool.json").read_text(encoding="utf-8"))
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert manifest["name"] == "deepseek_official_web_search"
    assert manifest["loading"]["dynamic"] is True
    assert "call_host_capability" not in source
    assert "tiance_runtime" not in source
    assert "Data/providers" not in source


def test_request_forces_deepseek_server_side_web_search():
    module = _load_module()
    config = module.ToolConfig(
        responses_url="https://api.deepseek.com/v1/responses",
        api_key="secret",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        max_output_tokens=32768,
        request_timeout_seconds=165,
    )

    request = module.build_request("latest news", config)

    assert request["model"] == "deepseek-v4-flash"
    assert request["tools"] == [{"type": "web_search"}]
    assert request["tool_choice"] == {"type": "web_search"}
    assert request["max_output_tokens"] == 32768
    assert "include" not in request


def test_config_info_returns_path_and_schema_accepts_api_key_parameter():
    module = _load_module()
    input_schema = loads(
        (TOOL_ROOT / ".tool" / "input.schema.json").read_text(encoding="utf-8")
    )

    result = module.run({"action": "config_info"})

    assert result["ok"] is True
    assert result["data"]["config_path"].endswith("program\\config.json")
    assert result["data"]["configuration_steps"]
    assert "configure" in input_schema["properties"]["action"]["enum"]
    assert "api_key" in input_schema["properties"]


def test_configure_writes_key_without_echoing_it(tmp_path):
    module = _load_module()
    module.CONFIG_PATH = tmp_path / "config.json"
    secret = "sk-test-never-echo-this"

    result = module.run({"action": "configure", "api_key": secret})
    saved = loads(module.CONFIG_PATH.read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert saved["deepseek"]["api_key"] == secret
    assert secret not in str(result)


def test_response_parser_requires_search_and_preserves_citations():
    module = _load_module()
    result = module.parse_response({
        "id": "resp-1",
        "model": "deepseek-v4-flash",
        "status": "completed",
        "output": [
            {
                "type": "web_search_call",
                "action": {"type": "search", "query": "latest news"},
            },
            {
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": "answer",
                    "annotations": [{
                        "type": "url_citation",
                        "url": "https://example.com/source",
                        "title": "Source",
                    }],
                }],
            },
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    })

    assert result["answer"] == "answer"
    assert result["search_queries"] == ["latest news"]
    assert result["sources"][0]["url"] == "https://example.com/source"
    assert result["usage"]["input_tokens"] == 10
