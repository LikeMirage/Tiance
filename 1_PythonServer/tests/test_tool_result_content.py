from __future__ import annotations

from json import dumps

from app.domain.llm.chat import ChatMessageContentPartType, ChatToolResult
from app.services.tools.tool_result_content import image_parts_from_tool_results


def test_generic_tool_resource_link_becomes_image_reference():
    result = _result(
        "capture_screen",
        {
            "ok": True,
            "content": [
                {
                    "type": "resource_link",
                    "uri": "tiance-project:///captures/%E9%A6%96%E9%A1%B5.png",
                    "name": "首页.png",
                    "mimeType": "image/png",
                    "size": 128,
                    "annotations": {"audience": ["assistant"]},
                }
            ],
        },
    )

    parts = image_parts_from_tool_results((result,))

    assert len(parts) == 1
    assert parts[0].type == ChatMessageContentPartType.IMAGE_REF
    assert parts[0].image_ref is not None
    assert parts[0].image_ref.path == "captures/首页.png"
    assert parts[0].image_ref.mime_type == "image/png"
    assert parts[0].image_ref.size_bytes == 128


def test_generic_local_resource_link_becomes_image_reference(tmp_path):
    image_path = tmp_path / "outside.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nimage")
    local_uri = f"tiance-local:{image_path.as_uri().removeprefix('file:')}"
    result = _result(
        "any_image_tool",
        {
            "ok": True,
            "content": [
                {
                    "type": "resource_link",
                    "uri": local_uri,
                    "name": "outside.png",
                    "mimeType": "image/png",
                    "size": image_path.stat().st_size,
                }
            ],
        },
    )

    parts = image_parts_from_tool_results((result,))

    assert len(parts) == 1
    assert parts[0].image_ref is not None
    assert parts[0].image_ref.path == local_uri


def test_generic_tool_resource_parser_rejects_unsafe_or_non_assistant_links():
    result = _result(
        "diagram_export",
        {
            "ok": True,
            "content": [
                {
                    "type": "resource_link",
                    "uri": "tiance-project:///../secret.png",
                    "mimeType": "image/png",
                },
                {
                    "type": "resource_link",
                    "uri": "file:///C:/secret.png",
                    "mimeType": "image/png",
                },
                {
                    "type": "resource_link",
                    "uri": "tiance-project:///exports/private.png",
                    "mimeType": "image/png",
                    "annotations": {"audience": ["user"]},
                },
            ],
        },
    )

    assert image_parts_from_tool_results((result,)) == ()


def test_failed_tool_result_never_attaches_resources():
    result = _result(
        "capture_screen",
        {
            "ok": False,
            "content": [
                {
                    "type": "resource_link",
                    "uri": "tiance-project:///captures/error.png",
                    "mimeType": "image/png",
                }
            ],
        },
        ok=False,
    )

    assert image_parts_from_tool_results((result,)) == ()


def _result(name: str, payload: dict, *, ok: bool = True) -> ChatToolResult:
    return ChatToolResult(
        call_id="call-1",
        name=name,
        arguments="{}",
        ok=ok,
        content=dumps(payload, ensure_ascii=False),
    )
