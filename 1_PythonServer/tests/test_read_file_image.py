from __future__ import annotations

import base64
import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from urllib.parse import quote

import pytest
from PIL import Image

from tests.formal_tool_paths import resolve_formal_tool_root


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
    assert "支持图片输入的模型" in result["error"]
    assert "parse_document_mineru_dmx" in result["error"]


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


@pytest.mark.parametrize("tool", ["read_file", "read_many_files"])
def test_scale_and_model_limit_are_applied_together(monkeypatch, tmp_path, tool):
    image = tmp_path / "diagram.png"
    Image.new("RGB", (160, 100)).save(image)
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))
    module = _load_read_file_module(tool)
    for percent, limit, expected in ((60, 40, (40, 25)), (60, 120, (96, 60)), (100, 32, (32, 20))):
        monkeypatch.setenv("TIANCE_MODEL_CONTEXT", json.dumps({"input_modalities": ["image"], "image_max_long_edge_px": limit}))
        item = {"file_path": "diagram.png", "image_scale_percent": percent}
        result = module.run(item if tool == "read_file" else {"files": [item]})
        data = result["data"] if tool == "read_file" else result["data"]["files"][0]
        assert (data["source_width"], data["source_height"]) == (160, 100)
        assert (data["returned_width"], data["returned_height"]) == expected
        with Image.open(data["returned_file_path"]) as sent:
            assert sent.size == expected


def test_tool_thumbnail_replays_from_snapshot_at_requested_scale_after_model_switch(monkeypatch, tmp_path):
    from app.domain.llm.chat import ChatCompletionRequest, ChatMessage, ChatMessageRole
    from app.infra.file_workspace import FileWorkspaceStorage
    from app.repositories.project.conversation_attachment_repository import ConversationAttachmentRepository
    from app.repositories.project.conversation_repository import ProjectConversationRepository
    from app.services.llm.chat.prompt_images import prepare_request_images
    from app.services.project.conversation_attachments import ConversationAttachmentService
    from app.services.tools.tool_result_content import image_parts_from_tool_content
    from tests.test_conversation_database import _Projects

    projects = _Projects(tmp_path)
    sessions = ProjectConversationRepository(projects)
    session = sessions.create_session("project-1", title="Replay", provider_id="p", model_id="m", reasoning_mode=None)
    attachments = ConversationAttachmentService(ConversationAttachmentRepository(projects), projects, FileWorkspaceStorage())
    def snapshot(ref, digest):
        return attachments.snapshot_image_ref("project-1", session.session_id, ref, source_kind="tool_artifact", expected_sha256=digest)

    path = tmp_path / "diagram.png"
    Image.new("RGB", (200, 100)).save(path)
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("TIANCE_MODEL_CONTEXT", '{"input_modalities":["image"],"image_max_long_edge_px":40}')
    result = _load_read_file_module().run({"file_path": path.name, "image_scale_percent": 60})
    assert result["data"]["returned_width"] == 40
    content = json.dumps(result)
    parts = image_parts_from_tool_content(content, snapshot=snapshot)
    stored = sessions.append_message("project-1", session.session_id, role="tool", content="read", content_parts=parts)
    path.unlink()
    saved = sessions.get_message("project-1", session.session_id, stored.message_id).content_parts
    msg = ChatMessage(role=ChatMessageRole.USER, content="image", content_parts=saved)
    request = ChatCompletionRequest("p", "m", (msg,))
    def read(ref):
        return attachments.read_image("project-1", session.session_id, ref)[0]
    for limit, expected in [(40, (40, 20)), (180, (120, 60))]:
        delivery, = prepare_request_images(request, limit, read_ref=read).image_deliveries
        assert (delivery.source_width, delivery.source_height) == (200, 100)
        assert (delivery.sent_width, delivery.sent_height) == expected

    # A source that changed between reading and snapshotting falls back to the delivered thumbnail.
    Image.new("RGB", (90, 50)).save(path)
    fallback, = image_parts_from_tool_content(content, snapshot=snapshot)
    assert fallback.image_ref.scale_percent == 100
    from io import BytesIO
    with Image.open(BytesIO(read(fallback.image_ref))) as image:
        assert image.size == (40, 20)


def test_batch_reader_accounts_for_the_number_of_images(monkeypatch, tmp_path):
    tool = _load_read_file_module("read_many_files")
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("TIANCE_MODEL_CONTEXT", json.dumps({
        "input_modalities": ["image"], "image_max_long_edge_px": 80,
        "multi_image_limit": {"min_images": 15, "max_long_edge_px": 40},
    }))
    filenames = [f"{index}.png" for index in range(15)]
    for index, filename in enumerate(filenames):
        Image.new("RGB", (120, 50), (index, 0, 0)).save(tmp_path / filename)
    (tmp_path / "note.txt").write_text("ok", encoding="utf-8")
    for count, width in ((14, 80), (15, 40)):
        result = tool.run({"files": [*filenames[:count], "note.txt"], "image_scale_percent": 100})
        assert [row["returned_width"] for row in result["data"]["files"][:-1]] == [width] * count


def _load_read_file_module(tool: str = "read_file") -> ModuleType:
    spec = spec_from_file_location(f"{tool}_main_under_test", resolve_formal_tool_root(tool) / "program/main.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 read_file 工具脚本。")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
