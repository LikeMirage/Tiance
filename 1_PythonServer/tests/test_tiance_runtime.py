from __future__ import annotations

import io
import json

import pytest

import tiance_runtime
from tiance_runtime import (
    call_host_capability,
    get_model_context,
    model_supports_input,
    run_tool,
)


def _run(handler, payload: str = "{}") -> tuple[int, dict, str]:
    output = io.StringIO()
    error = io.StringIO()
    code = run_tool(
        handler,
        input_stream=io.StringIO(payload),
        output_stream=output,
        error_stream=error,
        exit_process=False,
    )
    return code, json.loads(output.getvalue()), error.getvalue()


def test_run_tool_passes_json_payload_to_handler():
    code, result, error = _run(lambda payload: {"ok": True, "value": payload["value"]}, '{"value": 3}')

    assert code == 0
    assert result == {"ok": True, "value": 3}
    assert error == ""


def test_run_tool_uses_empty_object_for_empty_input():
    code, result, error = _run(lambda payload: {"ok": True, "payload": payload}, "")

    assert code == 0
    assert result == {"ok": True, "payload": {}}
    assert error == ""


def test_run_tool_rejects_non_object_input():
    code, result, error = _run(lambda payload: {"ok": True}, '["bad"]')

    assert code == 1
    assert result == {"ok": False, "error": "工具输入必须是 JSON 对象。"}
    assert error == ""


def test_run_tool_wraps_handler_exception():
    def handler(payload):
        raise RuntimeError("读取失败")

    code, result, error = _run(handler)

    assert code == 1
    assert result == {"ok": False, "error": "读取失败"}
    assert error == ""


def test_run_tool_rejects_non_dict_result():
    code, result, error = _run(lambda payload: "done")

    assert code == 1
    assert result == {"ok": False, "error": "工具返回值必须是 dict。"}
    assert error == ""


def test_run_tool_keeps_tool_stdout_out_of_json_result():
    def handler(payload):
        print("debug message")
        return {"ok": True}

    code, result, error = _run(handler)

    assert code == 0
    assert result == {"ok": True}
    assert error == "debug message\n"


def test_run_tool_exits_process_by_default():
    output = io.StringIO()

    with pytest.raises(SystemExit) as exc_info:
        run_tool(
            lambda payload: {"ok": False, "error": "失败"},
            input_stream=io.StringIO("{}"),
            output_stream=output,
            error_stream=io.StringIO(),
        )

    assert exc_info.value.code == 1
    assert json.loads(output.getvalue()) == {"ok": False, "error": "失败"}


def test_model_context_normalizes_generic_input_modalities(monkeypatch):
    monkeypatch.setenv(
        "TIANCE_MODEL_CONTEXT",
        '{"provider_id":"provider-1","model_id":"model-1","input_modalities":["Image","text","image"]}',
    )

    assert get_model_context() == {
        "provider_id": "provider-1",
        "model_id": "model-1",
        "input_modalities": ["image", "text"],
    }
    assert model_supports_input("IMAGE") is True
    assert model_supports_input("audio") is False


def test_model_context_is_empty_when_runtime_value_is_invalid(monkeypatch):
    monkeypatch.setenv("TIANCE_MODEL_CONTEXT", "not-json")

    assert get_model_context() == {}
    assert model_supports_input("image") is False


def test_host_capability_call_uses_scoped_token_and_preserves_full_response(monkeypatch):
    sources = [{"url": f"https://example.com/{index}"} for index in range(150)]
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"answer": "done", "sources": sources}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setenv("TIANCE_API_BASE_URL", "http://127.0.0.1:18000/api")
    monkeypatch.setenv("TIANCE_HOST_CAPABILITY_TOKEN", "scoped-token")
    monkeypatch.setattr(tiance_runtime, "urlopen", fake_urlopen)

    result = call_host_capability(
        "web_search",
        {"query": "latest update"},
        timeout_seconds=165,
    )

    assert result["sources"] == sources
    assert captured["timeout"] == 165
    request = captured["request"]
    assert request.full_url.endswith("/api/llm/provider-capabilities/web-search")
    assert request.headers["Authorization"] == "Bearer scoped-token"
    assert json.loads(request.data.decode("utf-8")) == {"query": "latest update"}


def test_host_capability_call_requires_backend_authorization(monkeypatch):
    monkeypatch.delenv("TIANCE_HOST_CAPABILITY_TOKEN", raising=False)
    monkeypatch.setenv("TIANCE_API_BASE_URL", "http://127.0.0.1:18000/api")

    with pytest.raises(RuntimeError, match="没有获得后端供应商能力授权"):
        call_host_capability("web_search", {"query": "test"}, timeout_seconds=10)
