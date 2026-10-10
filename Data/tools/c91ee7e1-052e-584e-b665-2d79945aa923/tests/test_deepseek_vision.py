from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


PROGRAM_ROOT = Path(__file__).resolve().parents[1] / "program"
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@pytest.fixture
def tool(monkeypatch):
    monkeypatch.syspath_prepend(str(PROGRAM_ROOT))
    monkeypatch.syspath_prepend(str(REPOSITORY_ROOT / "1_PythonServer"))
    spec = importlib.util.spec_from_file_location("mineru_deepseek_vision_test", PROGRAM_ROOT / "main.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def configure(tool, monkeypatch, tmp_path, *, vision_key="fixture-key", thinking_enabled=False, thinking_type="disabled"):
    config = tool.default_config_payload()
    config["mineru"]["api_key"] = "fixture-mineru-key"
    config["deepseek"]["api_key"] = vision_key
    config["deepseek"]["thinking"] = {"enabled": thinking_enabled, "type": thinking_type}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(tool, "CONFIG_PATH", path)
    return tool.load_tool_config()


def test_missing_config_creates_empty_key_deepseek_template(tool, monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    monkeypatch.setattr(tool, "CONFIG_PATH", path)
    tool.ensure_config_file_exists()
    config = json.loads(path.read_text(encoding="utf-8"))
    assert "dmxapi" not in config
    assert config["deepseek"]["base_url"] == "https://api.deepseek.com"
    assert config["deepseek"]["model"] == "deepseek-flash"
    assert config["deepseek"]["api_key"] == ""
    assert config["mineru"]["api_key"] == ""


@pytest.mark.parametrize("thinking_enabled,thinking_type", [(False, "disabled"), (True, "enabled")])
def test_vision_request_uses_official_image_and_generation_parameters(tool, monkeypatch, tmp_path, thinking_enabled, thinking_type):
    config = configure(tool, monkeypatch, tmp_path, thinking_enabled=thinking_enabled, thinking_type=thinking_type)
    image = tmp_path / "figure.png"
    image.write_bytes(PNG_BYTES)
    captured = {}

    def request(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return 200, json.dumps({
            "choices": [{"message": {"content": "| 标题 | 数值 |", "reasoning_content": "internal reasoning"}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
        })

    monkeypatch.setattr(tool, "http_request", request)
    result = tool.analyze_single_image(image, tmp_path, 30, config)
    payload = json.loads(captured["body"])
    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer fixture-key"
    assert captured["service_name"] == "DeepSeek"
    assert captured["timeout"] == 30
    assert payload["model"] == "deepseek-flash"
    assert payload["max_tokens"] == 1200
    assert "max_completion_tokens" not in payload
    assert payload["thinking"] == {"type": thinking_type}
    image_part = payload["messages"][1]["content"][1]
    assert image_part["type"] == "image_url"
    prefix, encoded = image_part["image_url"]["url"].split(",", 1)
    assert prefix == "data:image/png;base64"
    assert base64.b64decode(encoded) == PNG_BYTES
    assert result["analysis"] == "| 标题 | 数值 |"
    assert result["model"] == "deepseek-flash"
    assert result["usage"]["completion_tokens"] == 10


def test_vision_retries_transient_error(tool, monkeypatch, tmp_path):
    config = configure(tool, monkeypatch, tmp_path)
    image = tmp_path / "figure.png"
    image.write_bytes(PNG_BYTES)
    responses = iter([
        (429, '{"error":{"message":"rate limit"}}'),
        (200, '{"choices":[{"message":{"content":"识别结果"}}]}'),
    ])
    monkeypatch.setattr(tool, "http_request", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(tool.time, "sleep", lambda _: None)
    result = tool.analyze_single_image(image, tmp_path, 30, config)
    assert result["analysis"] == "识别结果"
    assert result["retry_count"] == 1


def test_vision_authentication_error_guides_deepseek_configuration(tool, monkeypatch, tmp_path):
    config = configure(tool, monkeypatch, tmp_path)
    image = tmp_path / "figure.png"
    image.write_bytes(PNG_BYTES)
    monkeypatch.setattr(tool, "http_request", lambda *args, **kwargs: (401, '{"error":{"message":"invalid key"}}'))
    with pytest.raises(tool.ToolError) as error:
        tool.analyze_single_image(image, tmp_path, 30, config)
    assert error.value.code == "DEEPSEEK_HTTP_ERROR"
    assert "deepseek.api_key" in error.value.details["fields"]
    assert "dmxapi" not in error.value.details["expected_config"]


def test_network_error_preserves_deepseek_configuration_guidance(tool, monkeypatch):
    class BrokenConnection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            raise OSError("connection failed")

    monkeypatch.setattr(tool.http.client, "HTTPSConnection", BrokenConnection)
    with pytest.raises(tool.ToolError) as error:
        tool.http_request(
            "POST", "https://api.deepseek.com/chat/completions",
            headers={}, body=b"{}", timeout=30, service_name="DeepSeek",
        )
    assert error.value.code == "HTTP_REQUEST_FAILED"
    assert "deepseek.api_key" in error.value.details["fields"]


def test_mineru_without_visual_analysis_does_not_require_deepseek_key(tool, monkeypatch, tmp_path):
    configure(tool, monkeypatch, tmp_path, vision_key="")
    options = SimpleNamespace(source_file=tmp_path / "report.pdf", analyze_images=False)
    assert tool.ensure_tool_config(options).deepseek_api_key == ""
    options.analyze_images = True
    with pytest.raises(tool.ToolError) as error:
        tool.ensure_tool_config(options)
    assert error.value.code == "CONFIG_MISSING"
    assert error.value.details["fields"] == ["deepseek.api_key"]


def test_doubao_auto_thinking_is_rejected_for_deepseek(tool, monkeypatch, tmp_path):
    configure(tool, monkeypatch, tmp_path, thinking_enabled=True, thinking_type="auto")
    options = SimpleNamespace(source_file=tmp_path / "report.pdf", analyze_images=True)
    with pytest.raises(tool.ToolError) as error:
        tool.ensure_tool_config(options)
    assert error.value.code == "CONFIG_INVALID"
    assert error.value.details["fields"] == ["deepseek.thinking.type"]


def test_unsupported_image_format_does_not_send_a_request(tool, monkeypatch, tmp_path):
    config = configure(tool, monkeypatch, tmp_path)
    image = tmp_path / "figure.bmp"
    image.write_bytes(b"BMfixture")
    monkeypatch.setattr(tool, "http_request", lambda *args, **kwargs: pytest.fail("Unsupported image must not be sent"))
    result = tool.analyze_single_image(image, tmp_path, 30, config)
    assert result["ok"] is False
    assert "JPEG、PNG、GIF 和 WebP" in result["error"]
