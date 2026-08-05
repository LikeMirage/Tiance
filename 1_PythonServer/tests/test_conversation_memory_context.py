from json import dumps

from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatImageRef,
    ChatMessage,
    ChatMessageContentPart,
    ChatMessageContentPartType,
    ChatMessageRole,
    ChatToolCall,
)
from app.infra.llm.chat_adapters.openai_responses_payloads import (
    _build_responses_body,
)
from app.services.project.conversation_memory_context import build_compressed_context_messages
from app.services.project.conversation_request_provenance import (
    conversation_message_id,
    tag_conversation_message,
)
from app.services.tools.tool_result_content import restore_tool_resource_messages


def test_compressed_context_keeps_same_text_user_message_with_different_content_parts():
    history_image_part = ChatMessageContentPart(
        type=ChatMessageContentPartType.IMAGE_REF,
        image_ref=ChatImageRef(path="images/history.png", mime_type="image/png"),
    )
    current_image_part = ChatMessageContentPart(
        type=ChatMessageContentPartType.IMAGE_REF,
        image_ref=ChatImageRef(path="images/current.png", mime_type="image/png"),
    )

    result = build_compressed_context_messages(
        messages=(
            _message("assistant-1", ChatMessageRole.ASSISTANT, "上一轮助手回复"),
            _message(
                "user-history",
                ChatMessageRole.USER,
                "看看这个",
                content_parts=(history_image_part,),
            ),
            ChatMessage(
                role=ChatMessageRole.USER,
                content="看看这个",
                content_parts=(current_image_part,),
            ),
        ),
        compression_records=[
            {
                "compression_id": "compression-1",
                "status": "completed",
                "source_type": "conversation_context",
                "source_message_ids": ["assistant-1"],
                "result": {
                    "items": [
                        {
                            "content": "上一轮助手回复已压缩。",
                            "keywords": [],
                        }
                    ],
                    "handoff": "继续查看当前图片。",
                },
            }
        ],
    )

    assert result is not None
    assert [message.content for message in result.messages] == [
        "历史累计摘要：\n- 上一轮助手回复已压缩。\n\n交接总结：\n继续查看当前图片。",
        "看看这个",
        "看看这个",
    ]
    assert result.messages[1].content_parts == (history_image_part,)
    assert result.messages[2].content_parts == (current_image_part,)
    assert conversation_message_id(result.messages[0]) is None
    assert conversation_message_id(result.messages[1]) == "user-history"


def test_compressed_context_updates_existing_summary_without_losing_live_request_fields():
    old_summary = ChatMessage(
        role=ChatMessageRole.ASSISTANT,
        content="历史摘要：旧摘要",
        preview_metadata={
            "memory_compression": {
                "compression_id": "compression-1",
                "source_type": "conversation_context",
            }
        },
    )
    recent_assistant = _message(
        "assistant-recent",
        ChatMessageRole.ASSISTANT,
        "近期回复",
    )
    recent_assistant = ChatMessage(
        role=recent_assistant.role,
        content=recent_assistant.content,
        provider_output_items=({"type": "reasoning", "id": "reasoning-1"},),
        internal_metadata=recent_assistant.internal_metadata,
    )
    live_resource = ChatMessage(
        role=ChatMessageRole.USER,
        content="",
        content_parts=(
            ChatMessageContentPart(
                type=ChatMessageContentPartType.IMAGE_REF,
                image_ref=ChatImageRef(path="images/live.png", mime_type="image/png"),
            ),
        ),
    )

    result = build_compressed_context_messages(
        messages=(
            old_summary,
            _message("assistant-new", ChatMessageRole.ASSISTANT, "新增历史"),
            recent_assistant,
            live_resource,
        ),
        compression_records=[
            {
                "compression_id": "compression-1",
                "status": "completed",
                "source_type": "conversation_context",
                "source_message_ids": ["assistant-old"],
                "result": {
                    "items": [{"content": "旧历史。", "keywords": []}],
                    "handoff": "旧交接。",
                },
            },
            {
                "compression_id": "compression-2",
                "status": "completed",
                "source_type": "conversation_context",
                "source_message_ids": ["assistant-old", "assistant-new"],
                "result": {
                    "items": [{"content": "新累计历史。", "keywords": []}],
                    "handoff": "继续近期工作。",
                },
            },
        ],
    )

    assert result is not None
    assert [message.content for message in result.messages] == [
        "历史累计摘要：\n- 新累计历史。\n\n交接总结：\n继续近期工作。",
        "近期回复",
        "",
    ]
    assert result.messages[1].provider_output_items == (
        {"type": "reasoning", "id": "reasoning-1"},
    )
    assert result.messages[2].content_parts == live_resource.content_parts


def test_compressed_context_rebuilds_images_only_from_tool_results_outside_summary():
    old_resource = _resource_result("images/old.png")
    recent_resource = _resource_result("images/recent.png")
    messages = restore_tool_resource_messages(
        (
            _message(
                "assistant-old",
                ChatMessageRole.ASSISTANT,
                "",
                tool_calls=(
                    ChatToolCall(
                        call_id="call-old",
                        name="capture_screen",
                        arguments="{}",
                    ),
                ),
            ),
            _message(
                "tool-old",
                ChatMessageRole.TOOL,
                old_resource,
                name="capture_screen",
                tool_call_id="call-old",
                content_parts=(_attachment_part("old", "images/old.png"),),
            ),
            _message(
                "assistant-recent",
                ChatMessageRole.ASSISTANT,
                "",
                tool_calls=(
                    ChatToolCall(
                        call_id="call-recent",
                        name="capture_screen",
                        arguments="{}",
                    ),
                ),
            ),
            _message(
                "tool-recent",
                ChatMessageRole.TOOL,
                recent_resource,
                name="capture_screen",
                tool_call_id="call-recent",
                content_parts=(_attachment_part("recent", "images/recent.png"),),
            ),
        )
    )

    result = build_compressed_context_messages(
        messages=messages,
        compression_records=[
            {
                "compression_id": "compression-1",
                "status": "completed",
                "source_type": "conversation_context",
                "source_message_ids": ["assistant-old", "tool-old"],
                "result": {
                    "items": [{"content": "旧截图任务已完成。", "keywords": []}],
                    "handoff": "继续近期截图任务。",
                },
            }
        ],
    )

    assert result is not None
    assert [message.role for message in result.messages] == [
        ChatMessageRole.ASSISTANT,
        ChatMessageRole.ASSISTANT,
        ChatMessageRole.TOOL,
        ChatMessageRole.USER,
    ]
    image_messages = [
        message
        for message in result.messages
        if message.internal_metadata.get("derived_tool_resource_message")
    ]
    assert len(image_messages) == 1
    assert image_messages[0].content_parts[0].image_ref is not None
    assert image_messages[0].content_parts[0].image_ref.path == (
        "tiance-attachment://att_recentrecentrecentrecentrecentre"
    )


def test_compressed_context_keeps_legacy_partial_tool_group_intact():
    messages = (
        _message("old-user", ChatMessageRole.USER, "旧请求"),
        _message(
            "assistant-call",
            ChatMessageRole.ASSISTANT,
            "",
            tool_calls=(
                ChatToolCall(
                    call_id="call-1",
                    name="read_file",
                    arguments="{}",
                ),
            ),
        ),
        _message(
            "tool-result",
            ChatMessageRole.TOOL,
            '{"ok":true}',
            name="read_file",
            tool_call_id="call-1",
        ),
        _message("recent-user", ChatMessageRole.USER, "近期请求"),
    )

    result = build_compressed_context_messages(
        messages=messages,
        compression_records=[
            {
                "compression_id": "legacy-partial",
                "status": "completed",
                "source_type": "conversation_context",
                "source_message_ids": ["old-user", "assistant-call"],
                "result": {
                    "items": [{"content": "旧请求已经摘要。", "keywords": []}],
                    "handoff": "继续近期请求。",
                },
            }
        ],
    )

    assert result is not None
    assert [message.role for message in result.messages] == [
        ChatMessageRole.ASSISTANT,
        ChatMessageRole.ASSISTANT,
        ChatMessageRole.TOOL,
        ChatMessageRole.USER,
    ]
    assert result.messages[1].tool_calls[0].call_id == "call-1"
    assert result.messages[2].tool_call_id == "call-1"
    assert result.replaced_message_ids == ("old-user",)
    payload = _build_responses_body(
        ChatCompletionRequest(
            provider_id="provider",
            model_id="model",
            messages=result.messages,
        ),
        stream=False,
    )
    function_call_index = next(
        index
        for index, item in enumerate(payload["input"])
        if item.get("type") == "function_call"
    )
    assert payload["input"][function_call_index]["call_id"] == "call-1"
    assert payload["input"][function_call_index + 1] == {
        "type": "function_call_output",
        "call_id": "call-1",
        "output": '{"ok":true}',
    }


def _message(
    message_id: str,
    role: ChatMessageRole,
    content: str,
    *,
    content_parts: tuple[ChatMessageContentPart, ...] = (),
    name: str | None = None,
    tool_call_id: str | None = None,
    tool_calls: tuple[ChatToolCall, ...] = (),
) -> ChatMessage:
    return tag_conversation_message(
        ChatMessage(
            role=role,
            content=content,
            content_parts=content_parts,
            name=name,
            tool_call_id=tool_call_id,
            tool_calls=tool_calls,
        ),
        message_id,
    )


def _resource_result(path: str) -> str:
    return dumps(
        {
            "ok": True,
            "content": [
                {
                    "type": "resource_link",
                    "uri": f"tiance-project:///{path}",
                    "name": path.rsplit("/", 1)[-1],
                    "mimeType": "image/png",
                    "size": 256,
                }
            ],
        },
        ensure_ascii=False,
    )


def _attachment_part(seed: str, source_path: str) -> ChatMessageContentPart:
    attachment_id = f"att_{(seed * 32)[:32]}"
    return ChatMessageContentPart(
        type=ChatMessageContentPartType.IMAGE_REF,
        image_ref=ChatImageRef(
            path=f"tiance-attachment://{attachment_id}",
            mime_type="image/png",
            attachment_id=attachment_id,
            source_path=source_path,
            source_kind="tool_artifact",
        ),
    )
