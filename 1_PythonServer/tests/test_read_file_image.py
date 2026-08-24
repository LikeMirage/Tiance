from __future__ import annotations

import base64
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from urllib.parse import quote

from tests.formal_tool_paths import resolve_formal_tool_root


_READ_FILE_MAIN = (
    resolve_formal_tool_root("read_file")
    / "program/main.py"
)

_VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_read_file_returns_image_reference(monkeypatch, tmp_path):
    module = _load_read_file_module()
    image_path = tmp_path / "interface.png"
    image_path.write_bytes(_VALID_PNG)
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "TIANCE_MODEL_CONTEXT",
        '{"provider_id":"provider-1","model_id":"vision-model","input_modalities":["text","image"]}',
    )

    result = module.run({"file_path": "interface.png", "image_scale_percent": 100})

    assert result["ok"] is True
    assert result["data"]["file_type"] == "image"
    assert result["data"]["source_mime_type"] == "image/png"
    assert result["data"]["returned_mime_type"] == "image/png"
    assert result["data"]["image_scale_percent"] == 100
    assert result["data"]["optimized"] is False
    assert result["content"] == [{
        "type": "resource_link",
        "uri": f"tiance-project:///{quote('interface.png', safe='/')}",
        "name": "interface.png",
        "mimeType": "image/png",
        "size": image_path.stat().st_size,
        "annotations": {"audience": ["assistant"], "priority": 1.0},
    }]
    assert result["structuredContent"] == result["data"]


def test_read_file_rejects_image_for_non_visual_model(monkeypatch, tmp_path):
    module = _load_read_file_module()
    (tmp_path / "interface.png").write_bytes(b"\x89PNG\r\n\x1a\nimage-data")
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "TIANCE_MODEL_CONTEXT",
        '{"provider_id":"provider-1","model_id":"text-model","input_modalities":["text"]}',
    )

    result = module.run({"file_path": "interface.png"})

    assert result["ok"] is False
    assert result["error_info"]["code"] == "MODEL_INPUT_UNSUPPORTED"
    assert "doubao_vision_parse" in result["error"]


def test_read_file_rejects_mismatched_image_content(monkeypatch, tmp_path):
    module = _load_read_file_module()
    (tmp_path / "fake.png").write_text("not an image", encoding="utf-8")
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "TIANCE_MODEL_CONTEXT",
        '{"input_modalities":["image"]}',
    )

    result = module.run({"file_path": "fake.png"})

    assert result["ok"] is False
    assert result["error_info"]["code"] == "IMAGE_CONTENT_MISMATCH"


def test_read_file_keeps_text_reading_behavior(monkeypatch, tmp_path):
    module = _load_read_file_module()
    (tmp_path / "notes.md").write_text("first\nsecond\nthird", encoding="utf-8")
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))

    result = module.run(
        {
            "file_path": "notes.md",
            "start_line": 2,
            "max_lines": 1,
            "include_line_numbers": True,
        }
    )

    assert result["ok"] is True
    assert result["data"]["content"] == "2 | second"
    assert result["data"]["start_line"] == 2
    assert result["data"]["end_line"] == 2


def test_read_file_allows_text_outside_workspace(monkeypatch, tmp_path):
    module = _load_read_file_module()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external_file = tmp_path / "outside.txt"
    external_file.write_text("outside content", encoding="utf-8")
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(workspace))

    result = module.run({"file_path": str(external_file)})

    assert result["ok"] is True
    assert result["data"]["content"] == "outside content"
    assert result["data"]["path_scope"] == "local"
    assert "relative_path" not in result["data"]


def test_read_file_returns_local_resource_for_image_outside_workspace(monkeypatch, tmp_path):
    module = _load_read_file_module()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external_image = tmp_path / "outside.png"
    external_image.write_bytes(_VALID_PNG)
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("TIANCE_MODEL_CONTEXT", '{"input_modalities":["image"]}')

    result = module.run({"file_path": str(external_image), "image_scale_percent": 100})

    assert result["ok"] is True
    assert result["data"]["path_scope"] == "local"
    assert "relative_path" not in result["data"]
    assert result["content"][0]["uri"].startswith("tiance-local:")


def test_read_file_defaults_to_scaled_image_reference(monkeypatch, tmp_path):
    module = _load_read_file_module()
    image_path = tmp_path / "interface.png"
    image_path.write_bytes(_VALID_PNG)
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("TIANCE_MODEL_CONTEXT", '{"input_modalities":["image"]}')

    result = module.run({"file_path": "interface.png"})

    assert result["ok"] is True
    assert result["data"]["image_scale_percent"] == 60
    assert result["data"]["optimized"] is True
    assert result["data"]["returned_file_path"] != str(image_path)
    assert result["content"][0]["uri"].startswith("tiance-local:")


def _load_read_file_module() -> ModuleType:
    spec = spec_from_file_location("read_file_main_under_test", _READ_FILE_MAIN)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 read_file 工具脚本。")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
