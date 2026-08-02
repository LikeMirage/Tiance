from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatMessage,
    ChatMessageRole,
    ChatToolCall,
    ChatToolDefinition,
)
from app.schemas.llm.chat import ChatCompletionRequestBody, ChatMessageRequest
from app.services.project.conversation_injection_preview import (
    build_conversation_injection_preview,
)


def test_chat_completion_request_uses_current_tool_call_default():
    payload = ChatCompletionRequestBody(
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
    )

    assert payload.max_tool_calls == 99999
    assert payload.to_domain().max_tool_calls == 99999


def test_conversation_injection_preview_records_complete_request_snapshot():
    request = ChatCompletionRequest(
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
        project_id="project_1",
        session_id="session_1",
        messages=(
            ChatMessage(role=ChatMessageRole.SYSTEM, content="主 Agent 系统提示词"),
            ChatMessage(
                role=ChatMessageRole.SYSTEM,
                content="当前项目的工作区：\n- 项目名称：测试\n- 工作区根路径：C:/work",
            ),
            ChatMessage(
                role=ChatMessageRole.SYSTEM,
                content="【动态加载工具目录】\n\n工具：read_file",
            ),
            ChatMessage(role=ChatMessageRole.USER, content="读取文件"),
            ChatMessage(
                role=ChatMessageRole.ASSISTANT,
                content="",
                tool_calls=(
                    ChatToolCall(
                        call_id="call_1",
                        name="read_file",
                        arguments='{"file_path":"README.md"}',
                    ),
                ),
            ),
            ChatMessage(
                role=ChatMessageRole.TOOL,
                content='{"ok":true,"content":"hello"}',
                name="read_file",
                tool_call_id="call_1",
            ),
        ),
        tools=(
            ChatToolDefinition(
                name="load_tool_info",
                description="工具信息加载",
                parameters={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string"},
                    },
                },
            ),
        ),
        return_thinking_content=True,
        max_tool_calls=30,
    )

    preview = build_conversation_injection_preview(request)

    assert preview["schema_version"] == 3
    assert "memory" not in preview
    assert "hidden_head" not in preview
    assert preview["request"]["preview_source"] == "real_request"
    assert preview["request"]["system_message_count"] == 3
    assert preview["request"]["tool_count"] == 1
    assert preview["request"]["ends_with_tool_result"] is True
    assert list(preview["request_snapshot"].keys()) == ["tools", "messages"]
    snapshot_messages = preview["request_snapshot"]["messages"]
    assert [message["role"] for message in snapshot_messages] == [
        "system",
        "system",
        "system",
        "user",
        "assistant",
        "tool",
    ]
    assert snapshot_messages[4]["tool_calls"] == [
        {
            "call_id": "call_1",
            "name": "read_file",
            "arguments": '{"file_path":"README.md"}',
        },
    ]
    assert snapshot_messages[5]["tool_call_id"] == "call_1"
    assert [
        message["source"]
        for message in snapshot_messages[:3]
    ] == [
        "system_prompt",
        "workspace_info",
        "dynamic_tool_directory",
    ]
    assert preview["request_snapshot"]["tools"][0]["name"] == "load_tool_info"
    assert preview["request_snapshot"]["tools"][0]["parameters"]["properties"] == {
        "operation": {"type": "string"},
    }


def test_chat_completion_request_accepts_tool_call_limit_above_old_cap():
    payload = ChatCompletionRequestBody(
        provider_id="deepseek",
        model_id="deepseek-v4",
        messages=[
            ChatMessageRequest(role="user", content="需要大量工具调用"),
        ],
        max_tool_calls=400,
    )

    assert payload.to_domain().max_tool_calls == 400


def test_conversation_injection_preview_marks_draft_source():
    request = ChatCompletionRequest(
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
        project_id="project_1",
        session_id="session_1",
        messages=(
            ChatMessage(role=ChatMessageRole.USER, content="输入框草稿"),
        ),
    )

    preview = build_conversation_injection_preview(
        request,
        preview_source="draft_request",
    )

    assert preview["schema_version"] == 3
    assert preview["request"]["preview_source"] == "draft_request"
    assert "下一次 AI 请求预览" in preview["description"]
    assert preview["request_snapshot"]["messages"][-1]["content"] == "输入框草稿"


def test_conversation_injection_preview_keeps_memory_metadata_outside_content():
    request = ChatCompletionRequest(
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
        messages=(
            ChatMessage(
                role=ChatMessageRole.ASSISTANT,
                content="- 旧对话已经压缩为摘要。",
                preview_metadata={
                    "memory_compression": {
                        "compression_id": "cmp_1",
                        "source_type": "conversation_context",
                        "source_message_count": 12,
                        "item_count": 1,
                    },
                },
            ),
        ),
    )

    preview = build_conversation_injection_preview(request)
    message = preview["request_snapshot"]["messages"][0]

    assert message["content"] == "- 旧对话已经压缩为摘要。"
    metadata = message["preview_metadata"]["memory_compression"]
    assert metadata["source_type"] == "conversation_context"
    assert metadata["source_message_count"] == 12
    assert metadata["item_count"] == 1
