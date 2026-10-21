from __future__ import annotations

import importlib.util
import json

import pytest

from tests.formal_tool_paths import resolve_formal_tool_root


TOOL_ROOT = resolve_formal_tool_root("deepseek_official_web_search")


@pytest.fixture
def tool(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(TOOL_ROOT / "program"))
    spec = importlib.util.spec_from_file_location("deepseek_official_web_search_main", TOOL_ROOT / "program/main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.CONFIG_PATH = tmp_path / "config.json"
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))
    return module


def row(**updates):
    return {
        "title": "标题", "url": "https://example.com/a", "snippet": "短摘要",
        "summary": "摘要", "content": "", "date": None, "site_name": None,
        "site_icon": None, "rerank_score": 1.75, "authority": 3, **updates,
    }


def configure(tool, key="local-secret", limits=None):
    result = tool.run({"action": "configure", "api_key": key})
    assert result["ok"], result
    if limits is not None:
        config = json.loads(tool.CONFIG_PATH.read_text(encoding="utf-8"))
        config["output"] = limits
        tool.CONFIG_PATH.write_text(json.dumps(config), encoding="utf-8")


def test_configure_clear_and_inspect_never_echo_key(tool):
    configure(tool, "sk-test-do-not-echo")
    result = tool.run({"action": "config_info"})
    assert result["data"]["config_key_configured"] is True
    assert "sk-test-do-not-echo" not in str(result)
    assert set(json.loads(tool.CONFIG_PATH.read_text())["deepseek"]) == {"api_key"}
    configure(tool, "")
    assert tool.run({"action": "config_info"})["data"]["config_key_configured"] is False


def test_json_key_takes_priority_and_search_is_not_a_model_request(tool, monkeypatch):
    configure(tool)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ignored-environment-secret")
    calls = []
    def direct(action, body, key):
        calls.append((action, body, key))
        return {"results": [row()]}
    monkeypatch.setattr(tool, "post_direct", direct)
    monkeypatch.setattr(tool, "call_host_capability", lambda *a, **k: pytest.fail("must not consult provider"))
    result = tool.run({"query": "资料", "count": 3})
    assert result["ok"], result
    assert calls == [("search", {"query": "资料", "count": 3, "need_content": False}, "local-secret")]
    assert result["data"]["key_source"] == "config"
    assert result["data"]["results"] == [row()]
    assert not (tool.CONFIG_PATH.parent / "web_searches").exists()


@pytest.mark.parametrize("status", [401, 402, 429, 500])
def test_explicit_key_failure_never_falls_back(tool, monkeypatch, status):
    configure(tool)
    def fail(*args):
        raise tool.ToolError("DEEPSEEK_HTTP_ERROR", "local-secret was rejected", {"http_status": status})
    monkeypatch.setattr(tool, "post_direct", fail)
    monkeypatch.setattr(tool, "call_host_capability", lambda *a, **k: pytest.fail("must not switch account"))
    result = tool.run({"query": "test"})
    assert not result["ok"]
    assert result["error_info"]["details"]["http_status"] == status
    assert result["error_info"]["details"]["key_source"] == "config"
    assert "local-secret" not in str(result)


@pytest.mark.parametrize("local_config", [False, True])
def test_missing_or_blank_json_key_uses_scoped_bridge(tool, monkeypatch, local_config):
    if local_config:
        configure(tool, "  ")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-be-used")
    calls = []
    def bridge(capability, body, **kwargs):
        calls.append((capability, body, kwargs))
        return {"ok": True, "data": {"results": []}}
    monkeypatch.setattr(tool, "call_host_capability", bridge)
    monkeypatch.setattr(tool, "post_direct", lambda *a: pytest.fail("no direct call without JSON key"))
    result = tool.run({"action": "search", "query": "no results"})
    assert result["ok"]
    assert result["data"]["result_count"] == 0
    assert result["data"]["key_source"] == "provider"
    assert calls[0][0] == "deepseek_web"
    assert "api_key" not in calls[0][1]
    assert not (tool.CONFIG_PATH.parent / "web_searches").exists()


def test_no_provider_key_reports_both_configuration_paths(tool, monkeypatch):
    monkeypatch.setattr(tool, "call_host_capability", lambda *a, **k: {
        "ok": False, "error": "请在模型集 DeepSeek 填写 Key，或调用 action=configure。",
        "error_info": {"code": "DEEPSEEK_KEY_MISSING"},
    })
    result = tool.run({"query": "test"})
    assert not result["ok"]
    assert result["error_info"]["code"] == "DEEPSEEK_KEY_MISSING"
    assert "模型集" in result["error"] and "configure" in result["error"]
    assert result["error_info"]["details"]["config_path"] == str(tool.CONFIG_PATH)


def test_invalid_json_is_not_silently_ignored(tool, monkeypatch):
    tool.CONFIG_PATH.write_text("{", encoding="utf-8")
    monkeypatch.setattr(tool, "call_host_capability", lambda *a, **k: pytest.fail("invalid config is an error"))
    assert tool.run({"query": "test"})["error_info"]["code"] == "CONFIG_INVALID"


@pytest.mark.parametrize("body", [
    {"query": " "}, {"query": "中" * 129}, {"query": "test", "count": 0},
    {"query": "test", "count": 51}, {"query": "test", "count": True},
    {"query": "test", "count": 2.5}, {"query": "test", "need_content": "true"},
    {"query": "test", "ori_question": " "}, {"query": "test", "model": "old"},
    {"query": "test", "api_key": "not-allowed-in-search"},
    {"action": "fetch", "url": "file:///test"}, {"action": "fetch", "url": "https://user:pass@example.com"},
    {"action": "fetch", "url": "https://[invalid"}, {"action": "fetch", "url": "https://example.com", "count": 2},
    {"action": "configure"}, {"action": "other"}, {"action": []},
])
def test_invalid_parameters_fail_before_network(tool, monkeypatch, body):
    monkeypatch.setattr(tool, "post_direct", lambda *a: pytest.fail("invalid input must not reach upstream"))
    monkeypatch.setattr(tool, "call_host_capability", lambda *a, **k: pytest.fail("invalid input must not reach bridge"))
    assert tool.run(body)["error_info"]["code"] == "INVALID_ARGUMENT"


def test_parameter_boundaries_and_optional_question(tool):
    action, body = tool.normalize_request({
        "query": "😀" * 128, "count": 50, "need_content": True, "ori_question": None,
        "localization": "8.8.8.8",
    })
    assert action == "search" and body["count"] == 50
    assert len(body["query"]) == 128 and body["ori_question"] is None


def test_long_fields_saved_exactly_once_with_short_siblings_inline(tool, monkeypatch):
    configure(tool, limits={"inline_field_chars": 10, "inline_text_budget": 20})
    content = "正文😀\r\n" * 20
    summary = "长摘要内容" * 20
    original = [row(summary=summary, content=content), row(summary="短", url="https://example.com/b")]
    monkeypatch.setattr(tool, "post_direct", lambda *a: {"results": original})
    result = tool.run({"query": "test", "need_content": True})
    assert result["ok"], result
    data = result["data"]
    first, second = data["results"]
    assert first["snippet"] == "短摘要" and second["summary"] == "短"
    assert "content" not in first and "summary" not in first
    for field, text in (("content", content), ("summary", summary)):
        descriptor = first["text_files"][field]
        path = tool.CONFIG_PATH.parent / descriptor["path"]
        assert path.read_bytes() == text.encode("utf-8")
        assert descriptor["size_bytes"] == len(text.encode("utf-8"))
        assert descriptor["character_count"] == len(text)
    index = tool.CONFIG_PATH.parent / data["index_file"]["path"]
    saved = json.loads(index.read_text(encoding="utf-8"))
    assert "content" not in saved["results"][0]
    assert "summary" not in saved["results"][0]
    assert len(list(index.parent.iterdir())) == 3  # one copy of each long field plus metadata
    assert data["saved_text_file_count"] == 2
    assert original[0]["content"] == content  # no mutation of upstream response
    assert content not in str(result)


def test_total_text_budget_handles_many_individually_short_fields(tool, monkeypatch):
    configure(tool, limits={"inline_field_chars": 100, "inline_text_budget": 10})
    monkeypatch.setattr(tool, "post_direct", lambda *a: {"results": [row() for _ in range(10)]})
    result = tool.run({"query": "test", "count": 10})
    assert result["ok"], result
    inline = sum(len(r.get(field, "")) for r in result["data"]["results"]
                 for field in ("snippet", "summary", "content"))
    assert inline <= 10
    assert result["data"]["saved_text_file_count"] > 0
    assert len(result["data"]["results"]) == 10


@pytest.mark.parametrize("length, expected_files", [(5, 0), (5000, 1)])
def test_fetch_preserves_requested_url_and_uses_same_storage_rules(tool, monkeypatch, length, expected_files):
    configure(tool)
    text = "文" * length
    monkeypatch.setattr(tool, "post_direct", lambda *a: {"title": "Page", "content": text})
    result = tool.run({"action": "fetch", "url": "https://example.com/page"})
    assert result["ok"], result
    assert result["data"]["page"]["url"] == "https://example.com/page"
    assert result["data"]["saved_text_file_count"] == expected_files


def test_storage_failure_is_reported_without_truncating_or_claiming_success(tool, monkeypatch):
    configure(tool, limits={"inline_field_chars": 0, "inline_text_budget": 0})
    monkeypatch.setattr(tool, "post_direct", lambda *a: {"results": [row()]})
    (tool.CONFIG_PATH.parent / "web_searches").write_text("occupied", encoding="utf-8")
    result = tool.run({"query": "test"})
    assert not result["ok"]
    assert result["error_info"]["code"] == "RESULT_SAVE_FAILED"


@pytest.mark.parametrize("response", [{"results": None}, {"results": [{"title": "only"}]}, {"answer": "old format"}])
def test_malformed_response_is_not_reported_as_empty_search(tool, monkeypatch, response):
    configure(tool)
    monkeypatch.setattr(tool, "post_direct", lambda *a: response)
    assert tool.run({"query": "test"})["error_info"]["code"] == "DEEPSEEK_INVALID_RESPONSE"


def test_contract_and_examples_describe_independent_api():
    metadata = json.loads((TOOL_ROOT / ".tool/tool.json").read_text(encoding="utf-8"))
    schema = json.loads((TOOL_ROOT / ".tool/input.schema.json").read_text(encoding="utf-8"))
    assert metadata["name"] == "deepseek_official_web_search"
    assert isinstance(metadata["loading"]["dynamic"], bool)
    assert schema["properties"]["count"]["maximum"] == 50
    assert schema["properties"]["query"]["maxLength"] == 128
    assert schema["properties"]["query"]["permission_scope"] == "unresolved"
    assert schema["properties"]["api_key"]["permission_type"] == "credential_use"
    assert schema["properties"]["action"]["enum"] == ["search", "fetch", "configure", "config_info"]
    for path in (TOOL_ROOT / "program").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "/v1/responses" not in source and "reasoning_effort" not in source


def test_declared_schema_enforces_common_bounds_before_execution():
    from app.services.tools.tool_execution_arguments import validate_tool_arguments
    schema = json.loads((TOOL_ROOT / ".tool/input.schema.json").read_text(encoding="utf-8"))
    assert not validate_tool_arguments({"action": "configure", "api_key": ""}, schema)
    assert not validate_tool_arguments({"query": "test", "count": 50}, schema)
    assert validate_tool_arguments({"query": "test", "count": 51}, schema)
    assert validate_tool_arguments({"query": "test", "need_content": "true"}, schema)


def test_atomic_configure_failure_preserves_existing_key(tool, monkeypatch):
    from pathlib import Path
    configure(tool, "original-key")
    def fail_replace(*args):
        raise OSError("write denied")
    monkeypatch.setattr(Path, "replace", fail_replace)
    result = tool.run({"action": "configure", "api_key": "new-key"})
    assert result["error_info"]["code"] == "CONFIG_WRITE_FAILED"
    assert json.loads(tool.CONFIG_PATH.read_text())["deepseek"]["api_key"] == "original-key"
    assert "new-key" not in str(result)


@pytest.mark.parametrize("status", [200, 302, 401, 429])
def test_direct_transport_endpoint_errors_and_connection_cleanup(tool, monkeypatch, status):
    import deepseek_transport as transport
    seen = []
    closed = []
    response = {"results": []} if status == 200 else {"error": {"message": "private-key rejected"}}
    class Connection:
        def __init__(self, host, timeout):
            assert host == "api.deepseek.com" and timeout == 120
        def request(self, method, path, body, headers):
            seen.append((method, path, json.loads(body), headers))
        def getresponse(self):
            from types import SimpleNamespace
            return SimpleNamespace(status=status, read=lambda: json.dumps(response).encode())
        def close(self):
            closed.append(True)
    monkeypatch.setattr(transport.http.client, "HTTPSConnection", Connection)
    if status == 200:
        assert transport.post_direct("search", {"query": "test"}, "private-key") == {"results": []}
    else:
        with pytest.raises(tool.ToolError) as error:
            transport.post_direct("search", {"query": "test"}, "private-key")
        assert error.value.details["http_status"] == status
        assert "private-key" not in str(error.value)
    assert closed == [True]
    assert seen[0][:3] == ("POST", "/v1/tools/search", {"query": "test"})
