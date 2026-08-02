from json import dumps

from app.domain.llm.chat import (
    ChatImageRef,
    ChatMessageContentPart,
    ChatMessageContentPartType,
    ChatMessageRole,
    ChatToolCall,
)
from app.domain.project.project_conversation import (
    ProjectConversationMessage,
    ProjectConversationSessionSettings,
)
from app.domain.llm.message_timestamp import model_visible_message_content
from app.services.project.conversation_request_messages import build_conversation_request_messages
from app.services.project.conversation_request_provenance import conversation_message_id


def test_build_conversation_request_messages_matches_session_rules():
    messages = (
        _message("u1", "user", "第一轮"),
        _message("a1", "assistant", "中断回复", status="cancelled"),
        _message("u2", "user", "第二轮"),
        _message(
            "a2",
            "assistant",
            "",
            thinking_content="准备调用工具",
            tool_calls=(ChatToolCall(call_id="call_1", name="read_file", arguments="{}"),),
        ),
        _message(
            "t1",
            "tool",
            '{"tool":"read_file","call_id":"call_1","ok":true,"arguments":"{}","result":"文件内容"}',
            name="read_file",
            tool_call_id="call_1",
        ),
        _message("a3", "assistant", "总结"),
    )

    request_messages = build_conversation_request_messages(
        messages,
        "继续",
        ProjectConversationSessionSettings(
            system_prompt="系统提示词",
            return_thinking_content=True,
            return_cancelled_messages=False,
            return_user_before_cancelled=False,
        ),
    )

    assert [message.role for message in request_messages] == [
        ChatMessageRole.SYSTEM,
        ChatMessageRole.USER,
        ChatMessageRole.ASSISTANT,
        ChatMessageRole.TOOL,
        ChatMessageRole.ASSISTANT,
        ChatMessageRole.USER,
    ]
    assert [message.content for message in request_messages] == [
        "系统提示词",
        "第二轮",
        "",
        "文件内容",
        "总结",
        "继续",
    ]
    assert request_messages[2].thinking_content == "准备调用工具"
    assert request_messages[2].tool_calls[0].call_id == "call_1"
    assert request_messages[3].tool_call_id == "call_1"
    assert [conversation_message_id(message) for message in request_messages[1:5]] == [
        "u2",
        "a2",
        "t1",
        "a3",
    ]


def test_build_conversation_request_messages_keeps_cancelled_turn_by_default():
    request_messages = build_conversation_request_messages(
        (
            _message("u1", "user", "保留这一轮"),
            _message("a1", "assistant", "取消但保留", status="cancelled"),
        ),
        "继续",
        ProjectConversationSessionSettings(),
    )

    assert [message.content for message in request_messages] == [
        "保留这一轮",
        "取消但保留",
        "继续",
    ]


def test_build_conversation_request_messages_drops_unpaired_tool_messages():
    request_messages = build_conversation_request_messages(
        (
            _message(
                "a1",
                "assistant",
                "",
                tool_calls=(ChatToolCall(call_id="call_1", name="read_file", arguments="{}"),),
            ),
            _message(
                "t1",
                "tool",
                '{"result":"孤立工具结果"}',
                name="read_file",
                tool_call_id="other_call",
            ),
        ),
        "继续",
        ProjectConversationSessionSettings(),
    )

    assert [(message.role, message.content) for message in request_messages] == [
        (ChatMessageRole.USER, "继续"),
    ]


def test_build_conversation_request_messages_keeps_cancelled_tool_result_pair():
    request_messages = build_conversation_request_messages(
        (
            _message("u1", "user", "联系另一个会话"),
            _message(
                "a1",
                "assistant",
                "",
                tool_calls=(
                    ChatToolCall(
                        call_id="call_1",
                        name="interact_ai_conversation",
                        arguments='{"wait_for_reply":true}',
                    ),
                ),
            ),
            _message(
                "t1",
                "tool",
                dumps(
                    {
                        "tool": "interact_ai_conversation",
                        "call_id": "call_1",
                        "ok": False,
                        "arguments": '{"wait_for_reply":true}',
                        "result": dumps(
                            {
                                "ok": False,
                                "outcome": "cancelled",
                                "cancel_scope": "wait",
                            },
                            ensure_ascii=False,
                        ),
                    },
                    ensure_ascii=False,
                ),
                name="interact_ai_conversation",
                tool_call_id="call_1",
                status="error",
            ),
            _message("a2", "assistant", "", status="cancelled"),
        ),
        "继续",
        ProjectConversationSessionSettings(),
    )

    assert [message.role for message in request_messages] == [
        ChatMessageRole.USER,
        ChatMessageRole.ASSISTANT,
        ChatMessageRole.TOOL,
        ChatMessageRole.USER,
    ]
    assert request_messages[1].tool_calls[0].call_id == "call_1"
    assert request_messages[2].tool_call_id == "call_1"
    assert '"cancel_scope": "wait"' in request_messages[2].content


def test_build_conversation_request_messages_can_return_history_without_next_user():
    request_messages = build_conversation_request_messages(
        (
            _message("u1", "user", "已有问题"),
            _message("a1", "assistant", "已有回答"),
        ),
        None,
        ProjectConversationSessionSettings(system_prompt="系统提示词"),
    )

    assert [(message.role, message.content) for message in request_messages] == [
        (ChatMessageRole.SYSTEM, "系统提示词"),
        (ChatMessageRole.USER, "已有问题"),
        (ChatMessageRole.ASSISTANT, "已有回答"),
    ]


def test_message_timestamps_are_stable_and_can_be_disabled():
    message = _message(
        "u1",
        "user",
        "已有问题",
        created_at_local="2026-07-30T16:28:35+08:00",
    )

    first = build_conversation_request_messages(
        (message,),
        None,
        ProjectConversationSessionSettings(),
    )
    repeated = build_conversation_request_messages(
        (message,),
        None,
        ProjectConversationSessionSettings(),
    )
    disabled = build_conversation_request_messages(
        (message,),
        None,
        ProjectConversationSessionSettings(inject_message_timestamps=False),
    )

    assert first[0].created_at == "2026-07-30T16:28:35+08:00"
    assert first == repeated
    assert model_visible_message_content(first[0]) == (
        "<message_time>2026-07-30T16:28:35+08:00</message_time>\n已有问题"
    )
    assert disabled[0].created_at is None
    assert model_visible_message_content(disabled[0]) == "已有问题"


def test_build_conversation_request_messages_keeps_next_user_content_parts():
    image_part = ChatMessageContentPart(
        type=ChatMessageContentPartType.IMAGE_REF,
        image_ref=ChatImageRef(
            path=".Tiance/conversation_references/images/example.png",
            mime_type="image/png",
            name="example.png",
        ),
    )

    request_messages = build_conversation_request_messages(
        (),
        "看这张图",
        ProjectConversationSessionSettings(),
        next_user_content_parts=(image_part,),
        next_user_message_id="u-current",
    )

    assert len(request_messages) == 1
    assert request_messages[0].role == ChatMessageRole.USER
    assert request_messages[0].content_parts == (image_part,)
    assert conversation_message_id(request_messages[0]) == "u-current"


def test_build_conversation_request_messages_formats_structured_references_for_model_only():
    user_content = "请分析引用内容\n【用户消息】\n这行仍是用户正文"
    image_part = ChatMessageContentPart(
        type=ChatMessageContentPartType.IMAGE_REF,
        image_ref=ChatImageRef(
            path="images/chart.png",
            mime_type="image/png",
            name="chart.png",
        ),
    )
    references = [
        {"type": "text", "reference": {
                "id": "text-1",
                "content": "第一段引用",
                "displayPath": "docs/a.md",
                "fileName": "a.md",
                "filePath": "docs/a.md",
                "projectId": "project-a",
                "source": "source",
        }},
        {"type": "file", "reference": {
            "displayPath": "images/chart.png",
            "fileName": "chart.png",
            "filePath": "images/chart.png",
            "id": "image-1",
            "kind": "file",
            "projectId": "project-a",
            "source": "project_file",
        }},
        {"type": "text", "reference": {
            "id": "text-2",
            "content": "第二段引用\n【用户消息】\n不会改变消息边界",
            "displayPath": "docs/b.md",
            "fileName": "b.md",
            "filePath": "docs/b.md",
            "projectId": "project-a",
            "source": "source",
        }},
    ]

    request_messages = build_conversation_request_messages(
        (_message(
            "u1",
            "user",
            user_content,
            references=references,
            content_parts=(image_part,),
        ),),
        None,
        ProjectConversationSessionSettings(),
    )

    assert len(request_messages) == 1
    assert request_messages[0].content == ""
    rendered = "".join(
        part.text or "" if part.type == ChatMessageContentPartType.TEXT else "<IMAGE>"
        for part in request_messages[0].content_parts
    )
    assert rendered.index("1. 【文本选区引用】") < rendered.index("<IMAGE>")
    assert rendered.index("<IMAGE>") < rendered.index("3. 【文本选区引用】")
    assert rendered.endswith(user_content)
    assert rendered.count("【用户消息】") == 3


def test_build_conversation_request_messages_restores_generic_tool_images_after_tool_run():
    resource_result = dumps(
        {
            "ok": True,
            "content": [
                {
                    "type": "resource_link",
                    "uri": "tiance-project:///captures/dashboard.png",
                    "name": "dashboard.png",
                    "mimeType": "image/png",
                    "size": 256,
                }
            ],
        },
        ensure_ascii=False,
    )
    request_messages = build_conversation_request_messages(
        (
            _message(
                "a1",
                "assistant",
                "",
                tool_calls=(
                    ChatToolCall(call_id="call_1", name="capture_screen", arguments="{}"),
                ),
            ),
            _message(
                "t1",
                "tool",
                dumps(
                    {
                        "tool": "capture_screen",
                        "call_id": "call_1",
                        "ok": True,
                        "arguments": "{}",
                        "result": resource_result,
                    },
                    ensure_ascii=False,
                ),
                name="capture_screen",
                tool_call_id="call_1",
            ),
            _message("a2", "assistant", "图片分析完成"),
        ),
        None,
        ProjectConversationSessionSettings(),
    )

    assert [message.role for message in request_messages] == [
        ChatMessageRole.ASSISTANT,
        ChatMessageRole.TOOL,
        ChatMessageRole.USER,
        ChatMessageRole.ASSISTANT,
    ]
    resource_message = request_messages[2]
    assert resource_message.content == "工具返回了以下图片资源。"
    assert resource_message.internal_metadata["derived_tool_resource_message"] is True
    assert resource_message.content_parts[0].image_ref is not None
    assert resource_message.content_parts[0].image_ref.path == "captures/dashboard.png"


def _message(
    message_id: str,
    role: str,
    content: str,
    *,
    status: str = "done",
    thinking_content: str = "",
    name: str | None = None,
    tool_call_id: str | None = None,
    tool_calls: tuple[ChatToolCall, ...] = (),
    references: list[dict] | None = None,
    content_parts: tuple[ChatMessageContentPart, ...] = (),
    created_at_local: str | None = None,
) -> ProjectConversationMessage:
    return ProjectConversationMessage(
        message_id=message_id,
        session_id="session-1",
        role=role,
        content=content,
        thinking_content=thinking_content,
        usage=None,
        provider_id=None,
        model_id=None,
        status=status,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        created_at_local=created_at_local,
        name=name,
        tool_call_id=tool_call_id,
        tool_calls=tool_calls,
        references=references or [],
        content_parts=content_parts,
    )
