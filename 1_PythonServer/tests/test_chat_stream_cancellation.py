import asyncio
import json
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from app.core.errors import BadRequestError, NotFoundError
from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatClientToolRequest,
    ChatMessage,
    ChatMessageRole,
    ChatStreamEvent,
    ChatStreamEventKind,
    ChatToolCall,
    ChatToolDefinition,
    ChatToolResult,
    ChatUsage,
)
from app.domain.project.project_conversation import (
    ProjectConversationMessage,
    ProjectConversationSession,
    ProjectConversationSessionSettings,
)
from app.services.project.conversation_stream import ProjectConversationStreamService
from app.services.project.conversation_background_tasks import (
    ConversationBackgroundTaskRegistry,
)
from app.services.project.conversation_tool_loop import _normalize_tool_call_limit
from app.services.tools.tool_execution import PreparedClientToolExecution


def test_stream_close_persists_partial_assistant_without_rebinding_session_model():
    conversation_service = _FakeConversationService()
    service = ProjectConversationStreamService(
        _NeverEndingChatService(),
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
    )

    initial_payloads = asyncio.run(_close_after_first_content_payload(service))

    assert [payload["kind"] for payload in initial_payloads] == [
        "conversation_run_started",
        "delta",
    ]
    assert initial_payloads[1]["content"] == "partial"
    assert conversation_service.runtime_statuses[-1] == ("project-1", "session-1", "idle")
    assert conversation_service.appended[-1]["role"] == "assistant"
    assert conversation_service.appended[-1]["content"] == "partial"
    assert conversation_service.appended[-1]["status"] == "cancelled"
    assert conversation_service.appended[-1]["provider_id"] == "deepseek"
    assert conversation_service.appended[-1]["model_id"] == "deepseek-v4"
    assert conversation_service.appended[-1]["sync_session_model"] is False


@pytest.mark.parametrize(
    ("partial_content", "expected_kinds", "expected_assistant_message_id"),
    [
        (
            "partial",
            ["conversation_run_started", "delta", "conversation_run_settled"],
            "msg-2",
        ),
        (
            "",
            ["conversation_run_started", "conversation_run_settled"],
            "msg-2",
        ),
    ],
)
def test_stream_task_cancellation_emits_settled_marker_with_or_without_partial_content(
    partial_content: str,
    expected_kinds: list[str],
    expected_assistant_message_id: str | None,
):
    conversation_service = _FakeConversationService()
    chat_service = _CancellableChatService(partial_content=partial_content)
    service = ProjectConversationStreamService(
        chat_service,
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
    )

    payloads = asyncio.run(_cancel_stream_task(service, chat_service.waiting))

    assert [payload["kind"] for payload in payloads] == expected_kinds
    assert payloads[-1] == {
        "kind": "conversation_run_settled",
        "user_message_id": "msg-1",
        "assistant_message_id": expected_assistant_message_id,
        "status": "cancelled",
    }
    if partial_content:
        assert payloads[1]["content"] == partial_content
        assert conversation_service.appended[-1]["status"] == "cancelled"
    else:
        assert [item["role"] for item in conversation_service.appended] == [
            "user",
            "assistant",
        ]
        assert conversation_service.appended[-1]["content"] == ""
        assert conversation_service.appended[-1]["status"] == "cancelled"
    assert len(conversation_service.ai_run_records) == 1
    assert conversation_service.ai_run_records[0]["user_message"].message_id == "msg-1"
    assert conversation_service.ai_run_records[0]["elapsed_ms"] >= 0


def test_stream_task_cancellation_estimates_missing_usage_and_context_tokens():
    conversation_service = _FakeConversationService()
    usage_service = _RecordingUsageService()
    chat_service = _CancellableChatService(partial_content="partial")
    service = ProjectConversationStreamService(
        chat_service,
        conversation_service,
        usage_service,
        _FakeNamingService(),
        _FakeMemoryService(),
    )

    asyncio.run(_cancel_stream_task(service, chat_service.waiting))

    interrupted_message = conversation_service.appended[-1]
    usage = interrupted_message["usage"]
    assert usage["prompt_tokens"] > 0
    assert usage["completion_tokens"] > 0
    assert usage["total_tokens"] == (
        usage["prompt_tokens"] + usage["completion_tokens"]
    )
    assert set(usage["estimated_fields"]) == {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    }
    assert interrupted_message["context_tokens"] == usage["prompt_tokens"]
    assert interrupted_message["context_tokens_estimated"] is True
    assert usage_service.records[0]["message_id"] == "msg-2"
    assert usage_service.records[0]["usage"].total_tokens == usage["total_tokens"]


def test_stream_completion_persists_assistant_without_rebinding_session_model():
    conversation_service = _FakeConversationService()
    service = ProjectConversationStreamService(
        _CompletingChatService(),
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
    )

    payloads = asyncio.run(_collect_payloads(service))

    assistant_messages = [
        item for item in conversation_service.appended
        if item["role"] == "assistant"
    ]
    assert [payload["kind"] for payload in payloads] == [
        "conversation_run_started",
        "delta",
        "conversation_run_settled",
    ]
    assert payloads[1]["content"] == "complete"
    assert payloads[-1]["status"] == "done"
    assert assistant_messages[-1]["content"] == "complete"
    assert assistant_messages[-1]["status"] == "done"
    assert assistant_messages[-1]["provider_id"] == "deepseek"
    assert assistant_messages[-1]["model_id"] == "deepseek-v4"
    assert assistant_messages[-1]["sync_session_model"] is False
    assert len(conversation_service.ai_run_records) == 1
    assert conversation_service.ai_run_records[0]["user_message"].message_id == "msg-1"


def test_empty_successful_response_persists_error_and_emits_one_error_terminal():
    conversation_service = _FakeConversationService()
    service = ProjectConversationStreamService(
        _EmptyDoneChatService(),
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
    )

    payloads = asyncio.run(_collect_payloads(service))

    assert payloads == [
        {
            "kind": "conversation_run_started",
            "user_message_id": "msg-1",
        },
        {
            "kind": "conversation_run_settled",
            "user_message_id": "msg-1",
            "assistant_message_id": "msg-2",
            "status": "error",
        },
        {
            "kind": "error",
            "error": "模型未返回可持久化的回复内容。",
            "error_code": "empty_model_response",
        },
    ]
    assert [item["role"] for item in conversation_service.appended] == [
        "user",
        "error",
    ]
    assert conversation_service.appended[-1]["status"] == "error"
    assert conversation_service.appended[-1]["content"] == "模型未返回可持久化的回复内容。"
    assert conversation_service.runtime_statuses[-1] == (
        "project-1",
        "session-1",
        "error",
    )


def test_stream_discards_completion_when_conversation_was_removed_externally():
    conversation_service = _FakeConversationService()
    memory_service = _FakeMemoryService()
    service = ProjectConversationStreamService(
        _ConversationRemovingChatService(conversation_service),
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        memory_service,
        background_task_registry=ConversationBackgroundTaskRegistry(),
    )

    payloads = asyncio.run(_collect_payloads(service))

    assert [payload["kind"] for payload in payloads] == [
        "conversation_run_started",
        "delta",
    ]
    assert payloads[1]["content"] == "discard me"
    assert not any(item["role"] == "assistant" for item in conversation_service.appended)
    assert memory_service.compression_calls == []


def test_stream_schedules_memory_compression_before_done_payload():
    conversation_service = _FakeConversationService()
    memory_service = _FakeMemoryService()
    service = ProjectConversationStreamService(
        _DoneCompletingChatService(),
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        memory_service,
    )

    async def collect_payloads():
        payloads = []
        async for payload in service.stream_payloads(_request()):
            if payload["kind"] == "done":
                assert memory_service.compression_calls == [("project-1", "session-1")]
                assert conversation_service.runtime_statuses[-1] == (
                    "project-1",
                    "session-1",
                    "idle",
                )
            payloads.append(payload)
        return payloads

    payloads = asyncio.run(collect_payloads())

    assert [payload["kind"] for payload in payloads] == [
        "conversation_run_started",
        "delta",
        "conversation_run_settled",
        "done",
    ]
    assert payloads[1]["content"] == "complete"
    assert payloads[2]["status"] == "done"


def test_stream_can_await_background_tasks_before_done_payload():
    conversation_service = _FakeConversationService()
    memory_service = _DelayedMemoryService()
    service = ProjectConversationStreamService(
        _DoneCompletingChatService(),
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        memory_service,
    )

    async def collect_payloads():
        payloads = []
        async for payload in service.stream_payloads(_request(), await_background_tasks=True):
            if payload["kind"] == "done":
                assert memory_service.finished is True
            payloads.append(payload)
        return payloads

    payloads = asyncio.run(collect_payloads())

    assert [payload["kind"] for payload in payloads] == [
        "conversation_run_started",
        "delta",
        "conversation_run_settled",
        "done",
    ]
    assert payloads[1]["content"] == "complete"
    assert payloads[2]["status"] == "done"


def test_blocking_memory_compression_finishes_before_stream_settles():
    conversation_service = _FakeConversationService()
    memory_service = _BlockingModeMemoryService()
    service = ProjectConversationStreamService(
        _DoneCompletingChatService(),
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        memory_service,
    )

    async def collect_payloads():
        payloads = []
        async for payload in service.stream_payloads(_request()):
            if payload["kind"] == "conversation_run_settled":
                assert memory_service.finished is True
            payloads.append(payload)
        return payloads

    payloads = asyncio.run(collect_payloads())

    assert [payload["kind"] for payload in payloads] == [
        "conversation_run_started",
        "delta",
        "conversation_run_settled",
        "done",
    ]
    assert memory_service.request_checks == 1
    assert memory_service.compression_calls == [("project-1", "session-1")]
    assert memory_service.blocking_values == [True, True]


def test_session_background_tasks_can_be_cancelled_after_main_response_finishes():
    conversation_service = _FakeConversationService()
    naming_service = _BlockingNamingService()
    memory_service = _BlockingMemoryService()
    registry = ConversationBackgroundTaskRegistry()
    service = ProjectConversationStreamService(
        _DoneCompletingChatService(),
        conversation_service,
        _FakeUsageService(),
        naming_service,
        memory_service,
        background_task_registry=registry,
    )

    async def run_test():
        payloads = await _collect_payloads(service)
        assert [payload["kind"] for payload in payloads] == [
            "conversation_run_started",
            "delta",
            "conversation_run_settled",
            "done",
        ]
        assert payloads[1]["content"] == "complete"
        assert payloads[2]["status"] == "done"
        await asyncio.gather(naming_service.started.wait(), memory_service.started.wait())

        await registry.cancel_session("project-1", "session-1")

        assert naming_service.cancelled.is_set()
        assert memory_service.cancelled.is_set()

    asyncio.run(run_test())


def test_stream_completion_survives_usage_recording_failure():
    conversation_service = _FakeConversationService()
    service = ProjectConversationStreamService(
        _CompletingChatService(),
        conversation_service,
        _FailingUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
    )

    payloads: list[dict[str, object | None]] = []

    asyncio.run(_append_stream_payloads(service, payloads))

    assert [item["role"] for item in conversation_service.appended] == [
        "user",
        "assistant",
    ]
    assert conversation_service.appended[-1]["content"] == "complete"
    assert not any(item["role"] == "error" for item in conversation_service.appended)
    assert payloads[-1]["kind"] == "conversation_run_settled"
    assert payloads[-1]["status"] == "done"


def test_stream_does_not_append_error_when_usage_record_fails_after_assistant_persistence():
    conversation_service = _FakeConversationService()
    service = ProjectConversationStreamService(
        _UsageCompletingChatService(),
        conversation_service,
        _FailingRecordUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
    )

    payloads: list[dict[str, object | None]] = []

    asyncio.run(_append_stream_payloads(service, payloads))

    assert [item["role"] for item in conversation_service.appended] == [
        "user",
        "assistant",
    ]
    assert conversation_service.appended[-1]["content"] == "complete"
    assert conversation_service.appended[-1]["usage"]["total_tokens"] == 18
    assert payloads[-2]["kind"] == "conversation_run_settled"
    assert payloads[-2]["status"] == "done"
    assert payloads[-1]["kind"] == "done"


def test_stream_persists_client_message_id_and_replays_completed_request_idempotently():
    conversation_service = _StatefulFakeConversationService()
    chat_service = _CountingDoneChatService()
    service = ProjectConversationStreamService(
        chat_service,
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
    )
    request = _request_with_client_message_id("client-user-1")

    first_payloads = asyncio.run(_collect_payloads(service, request=request))
    persisted_count = len(conversation_service.persisted_messages)
    replay_payloads = asyncio.run(_collect_payloads(service, request=request))

    assert [payload["kind"] for payload in first_payloads] == [
        "conversation_run_started",
        "delta",
        "conversation_run_settled",
        "done",
    ]
    assert conversation_service.persisted_messages[0].message_id == "client-user-1"
    assert conversation_service.appended[0]["message_id"] == "client-user-1"
    assert replay_payloads == [
        {
            "kind": "conversation_run_started",
            "user_message_id": "client-user-1",
        },
        {
            "kind": "conversation_run_settled",
            "user_message_id": "client-user-1",
            "assistant_message_id": conversation_service.persisted_messages[1].message_id,
            "status": "done",
        },
        {"kind": "done", "finish_reason": "replayed"},
    ]
    assert len(conversation_service.persisted_messages) == persisted_count
    assert chat_service.calls == 1


def test_stream_rejects_reused_client_message_id_with_different_content_without_side_effects():
    conversation_service = _StatefulFakeConversationService()
    chat_service = _CountingDoneChatService()
    service = ProjectConversationStreamService(
        chat_service,
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
    )
    request = _request_with_client_message_id("client-user-1")
    asyncio.run(_collect_payloads(service, request=request))
    persisted_count = len(conversation_service.persisted_messages)
    runtime_statuses = tuple(conversation_service.runtime_statuses)
    conflicting_request = replace(
        request,
        messages=(
            ChatMessage(
                role=ChatMessageRole.USER,
                content="different content",
                message_id="client-user-1",
            ),
        ),
    )

    payloads = asyncio.run(_collect_payloads(service, request=conflicting_request))

    assert payloads == [
        {
            "kind": "error",
            "error": (
                "Conversation message 'client-user-1' already exists with different content."
            ),
            "error_code": "conflict",
        }
    ]
    assert len(conversation_service.persisted_messages) == persisted_count
    assert tuple(conversation_service.runtime_statuses) == runtime_statuses
    assert not any(message.role == "error" for message in conversation_service.persisted_messages)
    assert chat_service.calls == 1


@pytest.mark.parametrize(
    ("reply_role", "reply_status", "expected_runtime_status"),
    [
        ("assistant", "done", "idle"),
        ("assistant", "cancelled", "idle"),
        ("error", "error", "error"),
    ],
)
def test_completed_request_replay_repairs_runtime_without_model_or_memory_side_effects(
    reply_role: str,
    reply_status: str,
    expected_runtime_status: str,
):
    existing_user = _persisted_user_message("client-user-1")
    existing_reply = _persisted_reply_message(
        role=reply_role,
        status=reply_status,
    )
    conversation_service = _StatefulFakeConversationService(
        persisted_messages=(existing_user, existing_reply),
        runtime_status="running",
    )
    chat_service = _CountingDoneChatService()
    memory_service = _FakeMemoryService()
    service = ProjectConversationStreamService(
        chat_service,
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        memory_service,
    )

    payloads = asyncio.run(
        _collect_payloads(
            service,
            request=_request_with_client_message_id("client-user-1"),
        )
    )

    assert payloads == [
        {
            "kind": "conversation_run_started",
            "user_message_id": "client-user-1",
        },
        {
            "kind": "conversation_run_settled",
            "user_message_id": "client-user-1",
            "assistant_message_id": "assistant-message-1",
            "status": reply_status,
        },
        {"kind": "done", "finish_reason": "replayed"},
    ]
    assert conversation_service.runtime_status == expected_runtime_status
    assert conversation_service.runtime_statuses == [
        ("project-1", "session-1", expected_runtime_status)
    ]
    assert conversation_service.appended == []
    assert conversation_service.update_session_calls == []
    assert memory_service.long_term_delivery_calls == []
    assert memory_service.compression_calls == []
    assert chat_service.calls == 0


def test_pending_existing_user_resume_reuses_user_for_memory_and_generates_one_reply():
    existing_user = _persisted_user_message("client-user-1")
    conversation_service = _StatefulFakeConversationService(
        persisted_messages=(existing_user,),
        runtime_status="running",
    )
    chat_service = _CountingDoneChatService()
    memory_service = _FakeMemoryService()
    service = ProjectConversationStreamService(
        chat_service,
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        memory_service,
    )

    payloads = asyncio.run(
        _collect_payloads(
            service,
            request=_request_with_client_message_id("client-user-1"),
        )
    )

    assert [payload["kind"] for payload in payloads] == [
        "conversation_run_started",
        "delta",
        "conversation_run_settled",
        "done",
    ]
    assert payloads[0]["user_message_id"] == "client-user-1"
    assert payloads[2]["status"] == "done"
    assert memory_service.long_term_delivery_calls == [
        ("project-1", "session-1", "client-user-1")
    ]
    assert [message.message_id for message in conversation_service.persisted_messages] == [
        "client-user-1",
        "msg-1",
    ]
    assert [message.role for message in conversation_service.persisted_messages] == [
        "user",
        "assistant",
    ]
    assert [item["role"] for item in conversation_service.appended] == ["assistant"]
    assert chat_service.calls == 1


def test_stream_keeps_system_prompt_out_of_messages_jsonl():
    conversation_service = _FakeConversationService()
    service = ProjectConversationStreamService(
        _CompletingChatService(),
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
    )

    asyncio.run(_collect_payloads(service, request=_request(system_prompt="当前提示词")))

    assert [item["role"] for item in conversation_service.appended] == [
        "user",
        "assistant",
    ]


def test_stream_sends_memory_rewritten_request_without_changing_persisted_user_message():
    conversation_service = _FakeConversationService()
    chat_service = _CapturingCompletingChatService()
    memory_service = _RewritingMemoryService()
    service = ProjectConversationStreamService(
        chat_service,
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        memory_service,
    )

    asyncio.run(_collect_payloads(service))

    assert [message.content for message in chat_service.requests[0].messages] == [
        "compressed context",
    ]
    assert conversation_service.appended[0]["role"] == "user"
    assert conversation_service.appended[0]["content"] == "hi"


def test_stream_injects_session_tools_before_calling_chat_service():
    conversation_service = _FakeConversationService(
        settings=ProjectConversationSessionSettings(
            enabled_tool_names=("read_text_file",),
        )
    )
    chat_service = _CapturingCompletingChatService()
    tool_injection_service = _FakeToolInjectionService()
    service = ProjectConversationStreamService(
        chat_service,
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
        tool_injection_service,
    )

    asyncio.run(_collect_payloads(service))

    assert tool_injection_service.enabled_tool_names == ("read_text_file",)
    assert len(chat_service.requests) == 1
    assert [tool.name for tool in chat_service.requests[0].tools] == ["read_text_file"]


def test_stream_does_not_inject_tools_when_session_tool_master_switch_is_off():
    conversation_service = _FakeConversationService(
        settings=ProjectConversationSessionSettings(
            tools_enabled=False,
            enabled_tool_names=("read_text_file",),
        )
    )
    chat_service = _CapturingCompletingChatService()
    tool_injection_service = _FakeToolInjectionService()
    service = ProjectConversationStreamService(
        chat_service,
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
        tool_injection_service,
    )

    request = replace(
        _request(),
        tools=(_tool_definition("read_text_file"),),
    )
    asyncio.run(_collect_payloads(service, request=request))

    assert tool_injection_service.enabled_tool_names is None
    assert chat_service.requests[0].tools == ()


def test_stream_executes_tool_call_and_feeds_result_back_to_model():
    conversation_service = _FakeConversationService()
    chat_service = _ToolCallingChatService()
    memory_service = _FakeMemoryService()
    service = ProjectConversationStreamService(
        chat_service,
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        memory_service,
        tool_injection_service=None,
        tool_execution_service=_FakeToolExecutionService(),
        project_service=_FakeProjectService(),
        tool_call_record_service=_FakeToolCallRecordService(),
    )
    request = _request()
    request = replace(
        request,
        return_thinking_content=True,
        tools=(
            ChatToolDefinition(
                name="read_text_file",
                description="读取本地纯文本文件。",
                parameters={"type": "object", "properties": {}},
            ),
        ),
    )

    payloads = asyncio.run(_collect_payloads(service, request=request))

    assert [payload["kind"] for payload in payloads] == [
        "conversation_run_started",
        "thinking_delta",
        "tool_call",
        "tool_result",
        "delta",
        "conversation_run_settled",
    ]
    assert payloads[1]["content"] == "需要读取文件。"
    assert payloads[-2]["content"] == "final answer"
    assert payloads[-1]["status"] == "done"
    assert len(chat_service.requests) == 2
    assert len(memory_service.run_snapshots) == 2
    assert [
        snapshot.model_request
        for snapshot in memory_service.run_snapshots
    ] == chat_service.requests
    second_messages = chat_service.requests[1].messages
    assert second_messages[-2].role == ChatMessageRole.ASSISTANT
    assert second_messages[-2].created_at is None
    assert second_messages[-2].tool_calls[0].name == "read_text_file"
    assert second_messages[-2].thinking_content == "需要读取文件。"
    assert second_messages[-2].provider_output_items == (
        {
            "id": "rs-1",
            "type": "reasoning",
            "encrypted_content": "encrypted",
            "summary": [],
        },
    )
    assert second_messages[-1].role == ChatMessageRole.TOOL
    assert second_messages[-1].created_at is None
    assert second_messages[-1].tool_call_id == "call-1"
    assert [item["role"] for item in conversation_service.appended] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert conversation_service.appended[1]["thinking_content"] == "需要读取文件。"
    assert conversation_service.appended[1]["tool_calls"][0].name == "read_text_file"
    assert conversation_service.appended[2]["tool_call_id"] == "call-1"
    assert conversation_service.appended[-1]["thinking_content"] == ""
    assert service._tool_call_record_service.records[0][0].name == "read_text_file"
    assert service._tool_call_record_service.records[0][1] == {
        "project_id": "project-1",
        "session_id": "session-1",
    }
    assert conversation_service.injection_preview[0:2] == ("project-1", "session-1")
    preview_messages = conversation_service.injection_preview[2]["request_snapshot"]["messages"]
    assert [message["role"] for message in preview_messages[-2:]] == [
        "assistant",
        "tool",
    ]
    assert preview_messages[-1]["tool_call_id"] == "call-1"
    assert preview_messages[-1]["content"] == '{"ok":true,"content":"hello"}'


def test_tool_loop_uses_async_memory_result_in_a_later_model_request():
    conversation_service = _FakeConversationService()
    chat_service = _ToolCallingChatService()
    memory_service = _AfterRoundRewritingMemoryService()
    service = ProjectConversationStreamService(
        chat_service,
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        memory_service,
        tool_execution_service=_FakeToolExecutionService(),
        project_service=_FakeProjectService(),
    )
    request = replace(
        _request(),
        tools=(
            ChatToolDefinition(
                name="read_text_file",
                description="读取本地纯文本文件。",
                parameters={"type": "object", "properties": {}},
            ),
        ),
    )

    asyncio.run(_collect_payloads(service, request=request))

    assert len(chat_service.requests) == 2
    assert [message.content for message in chat_service.requests[1].messages] == [
        "compressed live context",
    ]


def test_stream_feeds_generic_tool_image_after_all_tool_results():
    conversation_service = _FakeConversationService()
    chat_service = _RichToolCallingChatService()
    service = ProjectConversationStreamService(
        chat_service,
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
        tool_execution_service=_RichToolExecutionService(),
        project_service=_FakeProjectService(),
        runtime_capabilities_service=_FakeRuntimeCapabilitiesService(),
        attachment_service=_PassthroughAttachmentService(),
    )
    request = replace(
        _request(),
        project_id="00000000-0000-0000-0000-000000000001",
        provider_id="provider-1",
        model_id="model-1",
        tools=(
            ChatToolDefinition(
                name="capture_screen",
                description="截取当前界面。",
                parameters={"type": "object", "properties": {}},
            ),
        ),
    )

    asyncio.run(_collect_payloads(service, request=request))

    second_messages = chat_service.requests[1].messages
    assert [message.role for message in second_messages[-3:]] == [
        ChatMessageRole.ASSISTANT,
        ChatMessageRole.TOOL,
        ChatMessageRole.USER,
    ]
    assert second_messages[-2].tool_call_id == "capture-1"
    assert second_messages[-1].content_parts[0].image_ref is not None
    assert second_messages[-1].content_parts[0].image_ref.path == "captures/dashboard.png"


def test_stream_emits_internal_checkpoints_for_persisted_tool_turns():
    service = ProjectConversationStreamService(
        _ToolCallingChatService(),
        _FakeConversationService(),
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
        tool_execution_service=_FakeToolExecutionService(),
        project_service=_FakeProjectService(),
    )
    request = replace(
        _request(),
        return_thinking_content=True,
        tools=(_tool_definition("read_text_file"),),
    )

    async def collect_payloads():
        return [
            payload
            async for payload in service.stream_payloads(
                request,
                include_persistence_checkpoints=True,
            )
        ]

    payloads = asyncio.run(collect_payloads())
    checkpoints = [
        payload["checkpoint_message_id"]
        for payload in payloads
        if payload["kind"] == "_conversation_persistence_checkpoint"
    ]

    assert checkpoints == ["msg-2", "msg-3", "msg-4"]


def test_stream_rejects_direct_tool_call_when_tool_is_not_enabled_for_session():
    conversation_service = _FakeConversationService(
        settings=ProjectConversationSessionSettings(
            enabled_tool_names=("inspect_workspace",),
        )
    )
    chat_service = _ToolCallingChatService()
    service = ProjectConversationStreamService(
        chat_service,
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
        tool_execution_service=_FakeToolExecutionService(),
        project_service=_FakeProjectService(),
        tool_call_record_service=_FakeToolCallRecordService(),
    )
    request = replace(
        _request(),
        tools=(_tool_definition("load_tool_info"),),
    )

    payloads = asyncio.run(_collect_payloads(service, request=request))

    tool_result_payload = next(payload for payload in payloads if payload["kind"] == "tool_result")
    assert tool_result_payload["tool_result"]["ok"] is False
    assert tool_result_payload["tool_result"]["name"] == "read_text_file"
    assert tool_result_payload["tool_result"]["error"] == "此工具已关闭。"
    assert service._tool_call_record_service.records[0][0].ok is False


def test_stream_rejects_direct_tool_call_when_session_tool_master_switch_is_off():
    conversation_service = _FakeConversationService(
        settings=ProjectConversationSessionSettings(
            tools_enabled=False,
            enabled_tool_names=None,
        )
    )
    service = ProjectConversationStreamService(
        _ToolCallingChatService(),
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
        tool_execution_service=_FakeToolExecutionService(),
        project_service=_FakeProjectService(),
        tool_call_record_service=_FakeToolCallRecordService(),
    )
    request = replace(
        _request(),
        tools=(_tool_definition("load_tool_info"),),
    )

    payloads = asyncio.run(_collect_payloads(service, request=request))

    tool_result_payload = next(payload for payload in payloads if payload["kind"] == "tool_result")
    assert tool_result_payload["tool_result"]["ok"] is False
    assert tool_result_payload["tool_result"]["error"] == "会话工具总开关已关闭。"


def test_stream_tool_execution_does_not_block_event_loop():
    asyncio.run(_assert_tool_execution_does_not_block_event_loop())


def test_task_cancellation_during_tool_execution_settles_persisted_tool_round():
    conversation_service = _FakeConversationService()
    tool_execution_service = _BlockingToolExecutionService(delay_seconds=0.1)
    service = ProjectConversationStreamService(
        _ToolCallingChatService(),
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
        tool_execution_service=tool_execution_service,
        project_service=_FakeProjectService(),
    )
    request = replace(
        _request(),
        tools=(_tool_definition("read_text_file"),),
    )

    payloads = asyncio.run(
        _cancel_stream_during_tool_execution(
            service,
            request,
            tool_execution_service.started,
        )
    )

    assert payloads[-1] == {
        "kind": "conversation_run_settled",
        "user_message_id": "msg-1",
        "assistant_message_id": "msg-4",
        "status": "cancelled",
    }
    assert [item["role"] for item in conversation_service.appended] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert conversation_service.appended[1]["tool_calls"][0].call_id == "call-1"
    cancelled_tool_payload = json.loads(conversation_service.appended[2]["content"])
    cancelled_result = json.loads(cancelled_tool_payload["result"])
    assert cancelled_result["outcome"] == "cancelled"
    assert cancelled_result["cancel_scope"] == "execution"
    assert conversation_service.appended[2]["status"] == "cancelled"
    assert conversation_service.appended[3]["status"] == "cancelled"
    assert conversation_service.cancelled_messages == []


def test_task_cancellation_during_client_tool_wait_preserves_wait_scope():
    conversation_service = _FakeConversationService()
    tool_execution_service = _ClientToolExecutionService()
    client_tool_bridge = _WaitingClientToolBridge()
    service = ProjectConversationStreamService(
        _ClientToolCallingChatService(),
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
        tool_execution_service=tool_execution_service,
        project_service=_FakeProjectService(),
        client_tool_bridge_service=client_tool_bridge,
    )
    request = replace(
        _request(),
        tools=(_tool_definition("interact_ai_conversation"),),
    )

    payloads = asyncio.run(
        _cancel_stream_task(service, client_tool_bridge.waiting, request=request)
    )

    assert payloads[-1]["status"] == "cancelled"
    assert [item["role"] for item in conversation_service.appended] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    cancelled_tool_payload = json.loads(conversation_service.appended[2]["content"])
    cancelled_result = json.loads(cancelled_tool_payload["result"])
    assert cancelled_result["cancel_scope"] == "wait"
    assert "被等待的任务未被取消" in cancelled_result["reason"]
    assert conversation_service.appended[2]["status"] == "cancelled"


def test_parallel_tool_cancellation_completes_every_call_id():
    conversation_service = _FakeConversationService()
    tool_execution_service = _ParallelBlockingToolExecutionService()
    service = ProjectConversationStreamService(
        _ParallelToolCallingChatService(),
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
        tool_execution_service=tool_execution_service,
        project_service=_FakeProjectService(),
    )
    request = replace(
        _request(),
        tools=(_tool_definition("parallel_tool"),),
    )

    asyncio.run(
        _cancel_stream_during_tool_execution(
            service,
            request,
            tool_execution_service.started,
        )
    )

    tool_messages = [
        item for item in conversation_service.appended if item["role"] == "tool"
    ]
    assert [item["tool_call_id"] for item in tool_messages] == ["call-1", "call-2"]
    assert all(item["status"] == "cancelled" for item in tool_messages)


def test_task_cancellation_after_tool_results_appends_one_empty_terminal_message():
    conversation_service = _FakeConversationService()
    chat_service = _ToolCallingThenCancellableChatService()
    service = ProjectConversationStreamService(
        chat_service,
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
        tool_execution_service=_FakeToolExecutionService(),
        project_service=_FakeProjectService(),
    )
    request = replace(
        _request(),
        tools=(_tool_definition("read_text_file"),),
    )

    payloads = asyncio.run(
        _cancel_stream_task(service, chat_service.waiting, request=request)
    )

    assert payloads[-1] == {
        "kind": "conversation_run_settled",
        "user_message_id": "msg-1",
        "assistant_message_id": "msg-4",
        "status": "cancelled",
    }
    assert [item["role"] for item in conversation_service.appended] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert conversation_service.appended[-1]["content"] == ""
    assert conversation_service.appended[-1]["status"] == "cancelled"
    assert conversation_service.cancelled_messages == []


def test_multiround_tool_cancellation_keeps_each_completed_model_round_usage():
    conversation_service = _FakeConversationService()
    usage_service = _RecordingUsageService()
    tool_execution_service = _BlockSecondToolExecutionService(delay_seconds=0.1)
    service = ProjectConversationStreamService(
        _TwoToolRoundChatService(),
        conversation_service,
        usage_service,
        _FakeNamingService(),
        _FakeMemoryService(),
        tool_execution_service=tool_execution_service,
        project_service=_FakeProjectService(),
    )
    request = replace(
        _request(),
        tools=(_tool_definition("read_text_file"),),
    )

    payloads = asyncio.run(
        _cancel_stream_during_tool_execution(
            service,
            request,
            tool_execution_service.started,
        )
    )

    assert payloads[-1]["status"] == "cancelled"
    assert conversation_service.cancelled_messages == []
    assert [item["role"] for item in conversation_service.appended[-3:]] == [
        "assistant",
        "tool",
        "assistant",
    ]
    cancelled_tool_payload = json.loads(conversation_service.appended[-2]["content"])
    cancelled_result = json.loads(cancelled_tool_payload["result"])
    assert cancelled_result["cancel_scope"] == "execution"
    assert conversation_service.appended[-1]["status"] == "cancelled"
    assert [
        (record["message_id"], record["usage"].total_tokens)
        for record in usage_service.records
    ] == [
        ("msg-2", 12),
        ("msg-4", 23),
    ]


def test_stream_batches_parallel_tool_calls_without_reordering():
    conversation_service = _FakeConversationService()
    chat_service = _MixedToolBatchChatService()
    tool_execution_service = _TimedToolExecutionService(
        parallel_tool_names={"parallel_a", "parallel_b", "parallel_d"},
        delay_seconds=0.05,
    )
    service = ProjectConversationStreamService(
        chat_service,
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
        tool_execution_service=tool_execution_service,
        project_service=_FakeProjectService(),
    )
    request = replace(
        _request(),
        tools=(
            _tool_definition("parallel_a"),
            _tool_definition("parallel_b"),
            _tool_definition("sequential_c"),
            _tool_definition("parallel_d"),
            _tool_definition("sequential_e"),
        ),
    )

    payloads = asyncio.run(_collect_payloads(service, request=request))

    assert [payload["kind"] for payload in payloads] == [
        "conversation_run_started",
        "tool_call",
        "tool_call",
        "tool_result",
        "tool_result",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "delta",
        "conversation_run_settled",
    ]
    assert payloads[-2]["content"] == "final answer"
    assert payloads[-1]["status"] == "done"
    assert [
        payload["tool_call"]["name"]
        for payload in payloads
        if payload["kind"] == "tool_call"
    ] == [
        "parallel_a",
        "parallel_b",
        "sequential_c",
        "parallel_d",
        "sequential_e",
    ]
    assert [
        payload["tool_result"]["name"]
        for payload in payloads
        if payload["kind"] == "tool_result"
    ] == [
        "parallel_a",
        "parallel_b",
        "sequential_c",
        "parallel_d",
        "sequential_e",
    ]

    event_time = {
        (kind, name): timestamp
        for kind, name, timestamp in tool_execution_service.events
    }
    first_finish_time = min(
        timestamp
        for kind, _name, timestamp in tool_execution_service.events
        if kind == "finish"
    )
    assert event_time[("start", "parallel_a")] < first_finish_time
    assert event_time[("start", "parallel_b")] < first_finish_time
    assert event_time[("start", "sequential_c")] >= max(
        event_time[("finish", "parallel_a")],
        event_time[("finish", "parallel_b")],
    )
    assert event_time[("start", "parallel_d")] >= event_time[("finish", "sequential_c")]
    assert event_time[("start", "sequential_e")] >= event_time[("finish", "parallel_d")]


def test_stream_message_persistence_does_not_block_event_loop():
    asyncio.run(_assert_message_persistence_does_not_block_event_loop())


def test_stream_persists_usage_for_each_tool_loop_model_round():
    conversation_service = _FakeConversationService()
    chat_service = _UsageToolLoopChatService()
    memory_service = _FakeMemoryService()
    usage_service = _RecordingUsageService()
    service = ProjectConversationStreamService(
        chat_service,
        conversation_service,
        usage_service,
        _FakeNamingService(),
        memory_service,
        tool_execution_service=_FakeToolExecutionService(),
        project_service=_FakeProjectService(),
    )
    request = replace(
        _request(),
        tools=(
            ChatToolDefinition(
                name="read_text_file",
                description="读取本地纯文本文件。",
                parameters={"type": "object", "properties": {}},
            ),
        ),
    )

    payloads = asyncio.run(_collect_payloads(service, request=request))

    usage_payloads = [
        payload["usage"]
        for payload in payloads
        if payload["kind"] == "usage"
    ]
    assert usage_payloads == [
        {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "prompt_cache_hit_tokens": 80,
            "prompt_cache_miss_tokens": 20,
            "reasoning_tokens": 5,
        },
        {
            "prompt_tokens": 200,
            "completion_tokens": 30,
            "total_tokens": 230,
            "prompt_cache_hit_tokens": 150,
            "prompt_cache_miss_tokens": 50,
            "reasoning_tokens": 10,
        },
    ]
    assert [
        payload["context_tokens"]
        for payload in payloads
        if payload["kind"] == "usage"
    ] == [100, 200]
    assert conversation_service.appended[1]["context_tokens"] == 100
    assert conversation_service.appended[1]["usage"] == usage_payloads[0]
    assert conversation_service.appended[-1]["usage"] == usage_payloads[-1]
    assert conversation_service.appended[-1]["context_tokens"] == 200
    assert [
        (record["message_id"], record["usage"].total_tokens)
        for record in usage_service.records
    ] == [
        ("msg-2", 120),
        ("msg-4", 230),
    ]
    assert memory_service.run_snapshots[-1].context_tokens == 200
    assert memory_service.run_snapshots[-1].model_request is chat_service.requests[-1]


def test_stream_keeps_completed_round_usage_when_later_model_round_connection_fails():
    conversation_service = _FakeConversationService()
    usage_service = _RecordingUsageService()
    chat_service = _UsageThenConnectionFailureToolLoopChatService()
    service = ProjectConversationStreamService(
        chat_service,
        conversation_service,
        usage_service,
        _FakeNamingService(),
        _FakeMemoryService(),
        tool_execution_service=_FakeToolExecutionService(),
        project_service=_FakeProjectService(),
    )
    request = replace(_request(), tools=(_tool_definition("read_text_file"),))

    payloads = asyncio.run(_collect_payloads(service, request=request))

    completed_round_usage = ChatUsage(
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        prompt_cache_hit_tokens=80,
        prompt_cache_miss_tokens=20,
        reasoning_tokens=5,
    )
    error_message = conversation_service.appended[-1]
    assert payloads[-1]["kind"] == "error"
    assert error_message["role"] == "error"
    assert error_message["usage"] is None
    assert error_message["context_tokens"] is None
    assert usage_service.records == [
        {
            "project_id": "project-1",
            "session_id": "session-1",
            "message_id": "msg-2",
            "provider_id": "deepseek",
            "model_id": "deepseek-v4",
            "usage": completed_round_usage,
            "usage_feature_key": "main_chat",
        }
    ]


def test_stream_preserves_usage_when_provider_emits_error_event():
    conversation_service = _FakeConversationService()
    usage_service = _RecordingUsageService()
    service = ProjectConversationStreamService(
        _UsageThenErrorChatService(),
        conversation_service,
        usage_service,
        _FakeNamingService(),
        _FakeMemoryService(),
    )

    payloads = asyncio.run(_collect_payloads(service))

    error_message = conversation_service.appended[-1]
    assert payloads[-1] == {"kind": "error", "error": "provider failed"}
    assert error_message["role"] == "error"
    assert error_message["usage"]["total_tokens"] == 18
    assert usage_service.records[0]["usage"].total_tokens == 18


def test_provider_error_usage_record_failure_keeps_original_terminal_events_and_one_error():
    conversation_service = _FakeConversationService()
    service = ProjectConversationStreamService(
        _UsageThenErrorChatService(),
        conversation_service,
        _FailingRecordUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
    )

    payloads = asyncio.run(_collect_payloads(service))

    assert [payload["kind"] for payload in payloads] == [
        "conversation_run_started",
        "usage",
        "conversation_run_settled",
        "error",
    ]
    assert payloads[-2] == {
        "kind": "conversation_run_settled",
        "user_message_id": "msg-1",
        "assistant_message_id": "msg-2",
        "status": "error",
    }
    assert payloads[-1] == {"kind": "error", "error": "provider failed"}
    assert [item["role"] for item in conversation_service.appended] == [
        "user",
        "error",
    ]
    assert conversation_service.appended[-1]["content"] == "provider failed"
    assert conversation_service.runtime_statuses[-1] == (
        "project-1",
        "session-1",
        "error",
    )


def test_task_cancellation_usage_failures_preserve_cancelled_terminal_event():
    conversation_service = _FakeConversationService()
    chat_service = _CancellableUsageChatService()
    service = ProjectConversationStreamService(
        chat_service,
        conversation_service,
        _FailingUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
    )

    payloads = asyncio.run(_cancel_stream_task(service, chat_service.waiting))

    assert [payload["kind"] for payload in payloads] == [
        "conversation_run_started",
        "delta",
        "usage",
        "conversation_run_settled",
    ]
    assert payloads[-1] == {
        "kind": "conversation_run_settled",
        "user_message_id": "msg-1",
        "assistant_message_id": "msg-2",
        "status": "cancelled",
    }
    assert [item["role"] for item in conversation_service.appended] == [
        "user",
        "assistant",
    ]
    assert conversation_service.appended[-1]["status"] == "cancelled"
    assert conversation_service.runtime_statuses[-1] == (
        "project-1",
        "session-1",
        "idle",
    )


def test_stream_keeps_tool_thinking_for_display_but_omits_it_from_model_history():
    conversation_service = _FakeConversationService()
    chat_service = _ToolCallingChatService()
    service = ProjectConversationStreamService(
        chat_service,
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
        tool_execution_service=_FakeToolExecutionService(),
        project_service=_FakeProjectService(),
    )
    request = replace(
        _request(),
        return_thinking_content=False,
        tools=(
            ChatToolDefinition(
                name="read_text_file",
                description="读取本地纯文本文件。",
                parameters={"type": "object", "properties": {}},
            ),
        ),
    )

    asyncio.run(_collect_payloads(service, request=request))

    assert chat_service.requests[1].messages[-2].thinking_content == ""
    assert conversation_service.appended[1]["thinking_content"] == "需要读取文件。"


def test_stream_forwards_tool_call_deltas_before_complete_tool_call():
    conversation_service = _FakeConversationService()
    service = ProjectConversationStreamService(
        _ToolCallDeltaChatService(),
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
        tool_execution_service=_FakeToolExecutionService(),
        project_service=_FakeProjectService(),
    )
    request = replace(
        _request(),
        tools=(
            ChatToolDefinition(
                name="read_text_file",
                description="读取本地纯文本文件。",
                parameters={"type": "object", "properties": {}},
            ),
        ),
    )

    payloads = asyncio.run(_collect_payloads(service, request=request))
    visible_events = [
        payload
        for payload in payloads
        if payload["kind"] in {"thinking_delta", "tool_call_delta", "tool_call"}
    ]

    assert [payload["kind"] for payload in visible_events] == [
        "thinking_delta",
        "tool_call_delta",
        "tool_call_delta",
        "tool_call",
    ]
    assert visible_events[1]["tool_call"] == {
        "call_id": "call-1",
        "name": "read_text_file",
        "arguments": "",
    }
    assert visible_events[2]["tool_call"]["arguments"] == (
        '{"file_path":"C:/work/app.py"}'
    )
    assert visible_events[3]["tool_call"]["arguments"] == (
        '{"file_path":"C:/work/app.py"}'
    )


def test_stream_persists_tool_round_thinking_separately_from_final_answer():
    conversation_service = _FakeConversationService()
    chat_service = _TwoRoundToolCallingChatService()
    service = ProjectConversationStreamService(
        chat_service,
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
        tool_execution_service=_FakeToolExecutionService(),
        project_service=_FakeProjectService(),
    )
    request = replace(
        _request(),
        return_thinking_content=True,
        tools=(
            ChatToolDefinition(
                name="read_text_file",
                description="读取本地纯文本文件。",
                parameters={"type": "object", "properties": {}},
            ),
        ),
    )

    asyncio.run(_collect_payloads(service, request=request))

    assistant_messages = [
        item for item in conversation_service.appended
        if item["role"] == "assistant"
    ]
    assert [item["thinking_content"] for item in assistant_messages] == [
        "第一步先看工作区。",
        "看到工作区后再读文件。",
        "最后整理答案。",
    ]
    assert assistant_messages[0]["tool_calls"][0].call_id == "call-1"
    assert assistant_messages[1]["tool_calls"][0].call_id == "call-2"
    assert assistant_messages[2]["content"] == "final answer"


def test_stream_stops_when_configured_tool_call_limit_is_exceeded():
    conversation_service = _FakeConversationService()
    chat_service = _RepeatingToolCallingChatService()
    service = ProjectConversationStreamService(
        chat_service,
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
        tool_execution_service=_FakeToolExecutionService(),
        project_service=_FakeProjectService(),
    )
    request = replace(
        _request(),
        max_tool_calls=1,
        tools=(
            ChatToolDefinition(
                name="read_text_file",
                description="读取本地纯文本文件。",
                parameters={"type": "object", "properties": {}},
            ),
        ),
    )

    payloads = asyncio.run(_collect_payloads(service, request=request))

    assert [payload["kind"] for payload in payloads] == [
        "conversation_run_started",
        "tool_call",
        "tool_result",
        "conversation_run_settled",
        "error",
    ]
    assert payloads[-2]["status"] == "error"
    assert "上限 1 次" in payloads[-1]["error"]
    assert len(chat_service.requests) == 2


def test_tool_call_limit_above_old_cap_is_preserved():
    assert _normalize_tool_call_limit(400) == 400


async def _close_after_first_content_payload(service: ProjectConversationStreamService):
    generator = service.stream_payloads(_request())
    payloads = [
        await generator.__anext__(),
        await generator.__anext__(),
    ]
    await generator.aclose()
    return payloads


async def _collect_payloads(
    service: ProjectConversationStreamService,
    *,
    request: ChatCompletionRequest | None = None,
):
    return [payload async for payload in service.stream_payloads(request or _request())]


async def _append_stream_payloads(
    service: ProjectConversationStreamService,
    payloads: list[dict[str, object | None]],
) -> None:
    async for payload in service.stream_payloads(_request()):
        payloads.append(payload)


async def _cancel_stream_task(
    service: ProjectConversationStreamService,
    waiting: asyncio.Event,
    *,
    request: ChatCompletionRequest | None = None,
) -> list[dict[str, object | None]]:
    payloads: list[dict[str, object | None]] = []

    async def collect() -> None:
        async for payload in service.stream_payloads(request or _request()):
            payloads.append(payload)

    task = asyncio.create_task(collect())
    await asyncio.wait_for(waiting.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    return payloads


async def _cancel_stream_during_tool_execution(
    service: ProjectConversationStreamService,
    request: ChatCompletionRequest,
    started: threading.Event,
) -> list[dict[str, object | None]]:
    payloads: list[dict[str, object | None]] = []

    async def collect() -> None:
        async for payload in service.stream_payloads(request):
            payloads.append(payload)

    task = asyncio.create_task(collect())
    while not started.is_set():
        await asyncio.sleep(0.005)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    return payloads


async def _assert_tool_execution_does_not_block_event_loop():
    tool_execution_service = _BlockingToolExecutionService(delay_seconds=0.3)
    service = ProjectConversationStreamService(
        _ToolCallingChatService(),
        _FakeConversationService(),
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
        tool_execution_service=tool_execution_service,
        project_service=_FakeProjectService(),
    )
    request = replace(
        _request(),
        tools=(
            ChatToolDefinition(
                name="read_text_file",
                description="读取本地纯文本文件。",
                parameters={"type": "object", "properties": {}},
            ),
        ),
    )

    collect_task = asyncio.create_task(_collect_payloads(service, request=request))
    await asyncio.wait_for(asyncio.to_thread(tool_execution_service.started.wait), timeout=1)
    await asyncio.wait_for(asyncio.sleep(0.02), timeout=0.1)

    assert not tool_execution_service.finished.is_set()
    payloads = await collect_task
    assert any(payload["kind"] == "tool_result" for payload in payloads)


async def _assert_message_persistence_does_not_block_event_loop():
    conversation_service = _BlockingAppendConversationService(delay_seconds=0.3)
    service = ProjectConversationStreamService(
        _CompletingChatService(),
        conversation_service,
        _FakeUsageService(),
        _FakeNamingService(),
        _FakeMemoryService(),
    )

    collect_task = asyncio.create_task(_collect_payloads(service))
    await asyncio.wait_for(asyncio.to_thread(conversation_service.started.wait), timeout=1)
    await asyncio.wait_for(asyncio.sleep(0.02), timeout=0.1)

    assert not conversation_service.finished.is_set()
    payloads = await collect_task
    assert [payload["kind"] for payload in payloads] == [
        "conversation_run_started",
        "delta",
        "conversation_run_settled",
    ]
    assert payloads[1]["content"] == "complete"
    assert payloads[2]["status"] == "done"


def _request(*, system_prompt: str = "") -> ChatCompletionRequest:
    messages = []
    if system_prompt:
        messages.append(ChatMessage(role=ChatMessageRole.SYSTEM, content=system_prompt))
    messages.append(ChatMessage(role=ChatMessageRole.USER, content="hi"))
    return ChatCompletionRequest(
        provider_id="deepseek",
        model_id="deepseek-v4",
        project_id="project-1",
        session_id="session-1",
        messages=tuple(messages),
    )


def _request_with_client_message_id(message_id: str) -> ChatCompletionRequest:
    return replace(
        _request(),
        messages=(
            ChatMessage(
                role=ChatMessageRole.USER,
                content="hi",
                message_id=message_id,
            ),
        ),
    )


def _persisted_user_message(message_id: str) -> ProjectConversationMessage:
    return ProjectConversationMessage(
        message_id=message_id,
        session_id="session-1",
        role="user",
        content="hi",
        thinking_content="",
        usage=None,
        provider_id=None,
        model_id=None,
        target_provider_id="deepseek",
        target_model_id="deepseek-v4",
        status="done",
        created_at="now",
        updated_at="now",
    )


def _persisted_reply_message(*, role: str, status: str) -> ProjectConversationMessage:
    return ProjectConversationMessage(
        message_id="assistant-message-1",
        session_id="session-1",
        role=role,
        content="existing reply",
        thinking_content="",
        usage=None,
        provider_id="deepseek",
        model_id="deepseek-v4",
        status=status,
        created_at="now",
        updated_at="now",
    )


def _tool_definition(name: str) -> ChatToolDefinition:
    return ChatToolDefinition(
        name=name,
        description=f"{name} test tool",
        parameters={"type": "object", "properties": {}},
    )


class _NeverEndingChatService:
    async def stream(self, _request):
        yield ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content="partial")
        await asyncio.Event().wait()


class _CancellableChatService:
    def __init__(self, *, partial_content: str) -> None:
        self.partial_content = partial_content
        self.waiting = asyncio.Event()

    async def stream(self, _request):
        if self.partial_content:
            yield ChatStreamEvent(
                kind=ChatStreamEventKind.DELTA,
                content=self.partial_content,
            )
        self.waiting.set()
        await asyncio.Event().wait()


class _CancellableUsageChatService:
    def __init__(self) -> None:
        self.waiting = asyncio.Event()

    async def stream(self, _request):
        yield ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content="partial")
        yield ChatStreamEvent(
            kind=ChatStreamEventKind.USAGE,
            usage=ChatUsage(prompt_tokens=7, completion_tokens=2, total_tokens=9),
        )
        self.waiting.set()
        await asyncio.Event().wait()


class _CompletingChatService:
    async def stream(self, _request):
        yield ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content="complete")


class _DoneCompletingChatService:
    async def stream(self, _request):
        yield ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content="complete")
        yield ChatStreamEvent(kind=ChatStreamEventKind.DONE, finish_reason="stop")


class _EmptyDoneChatService:
    async def stream(self, _request):
        yield ChatStreamEvent(kind=ChatStreamEventKind.DONE, finish_reason="stop")


class _CountingDoneChatService:
    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, _request):
        self.calls += 1
        yield ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content="complete")
        yield ChatStreamEvent(kind=ChatStreamEventKind.DONE, finish_reason="stop")


class _UsageCompletingChatService:
    async def stream(self, _request):
        yield ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content="complete")
        yield ChatStreamEvent(
            kind=ChatStreamEventKind.USAGE,
            usage=ChatUsage(prompt_tokens=7, completion_tokens=11, total_tokens=18),
        )
        yield ChatStreamEvent(kind=ChatStreamEventKind.DONE, finish_reason="stop")


class _ConversationRemovingChatService:
    def __init__(self, conversation_service) -> None:
        self._conversation_service = conversation_service

    async def stream(self, _request):
        yield ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content="discard me")
        self._conversation_service.session = None


class _CapturingCompletingChatService:
    def __init__(self) -> None:
        self.requests: list[ChatCompletionRequest] = []

    async def stream(self, request):
        self.requests.append(request)
        yield ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content="complete")


class _ToolCallingChatService:
    def __init__(self) -> None:
        self.requests: list[ChatCompletionRequest] = []

    async def stream(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield ChatStreamEvent(
                kind=ChatStreamEventKind.PROVIDER_OUTPUT_ITEM,
                provider_output_item={
                    "id": "rs-1",
                    "type": "reasoning",
                    "encrypted_content": "encrypted",
                    "summary": [],
                },
            )
            yield ChatStreamEvent(kind=ChatStreamEventKind.THINKING_DELTA, content="需要读取文件。")
            yield ChatStreamEvent(
                kind=ChatStreamEventKind.TOOL_CALL,
                tool_call=ChatToolCall(
                    call_id="call-1",
                    name="read_text_file",
                    arguments='{"file_path":"C:/work/app.py"}',
                ),
            )
            yield ChatStreamEvent(kind=ChatStreamEventKind.DONE, finish_reason="tool_calls")
            return
        yield ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content="final answer")


class _ClientToolCallingChatService:
    async def stream(self, _request):
        yield ChatStreamEvent(
            kind=ChatStreamEventKind.TOOL_CALL,
            tool_call=ChatToolCall(
                call_id="call-1",
                name="interact_ai_conversation",
                arguments='{"action":"send","wait_for_reply":true}',
            ),
        )
        yield ChatStreamEvent(kind=ChatStreamEventKind.DONE, finish_reason="tool_calls")


class _ParallelToolCallingChatService:
    async def stream(self, _request):
        for call_id in ("call-1", "call-2"):
            yield ChatStreamEvent(
                kind=ChatStreamEventKind.TOOL_CALL,
                tool_call=ChatToolCall(
                    call_id=call_id,
                    name="parallel_tool",
                    arguments="{}",
                ),
            )
        yield ChatStreamEvent(kind=ChatStreamEventKind.DONE, finish_reason="tool_calls")


class _ToolCallingThenCancellableChatService:
    def __init__(self) -> None:
        self.requests: list[ChatCompletionRequest] = []
        self.waiting = asyncio.Event()

    async def stream(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield ChatStreamEvent(
                kind=ChatStreamEventKind.TOOL_CALL,
                tool_call=ChatToolCall(
                    call_id="call-1",
                    name="read_text_file",
                    arguments='{"file_path":"C:/work/app.py"}',
                ),
            )
            yield ChatStreamEvent(
                kind=ChatStreamEventKind.DONE,
                finish_reason="tool_calls",
            )
            return
        self.waiting.set()
        await asyncio.Event().wait()


class _TwoToolRoundChatService:
    def __init__(self) -> None:
        self.requests: list[ChatCompletionRequest] = []

    async def stream(self, request):
        self.requests.append(request)
        round_number = len(self.requests)
        usage = (
            ChatUsage(prompt_tokens=10, completion_tokens=2, total_tokens=12)
            if round_number == 1
            else ChatUsage(prompt_tokens=20, completion_tokens=3, total_tokens=23)
        )
        yield ChatStreamEvent(kind=ChatStreamEventKind.USAGE, usage=usage)
        yield ChatStreamEvent(
            kind=ChatStreamEventKind.TOOL_CALL,
            tool_call=ChatToolCall(
                call_id=f"call-{round_number}",
                name="read_text_file",
                arguments='{"file_path":"C:/work/app.py"}',
            ),
        )
        yield ChatStreamEvent(
            kind=ChatStreamEventKind.DONE,
            finish_reason="tool_calls",
        )


class _ToolCallDeltaChatService:
    def __init__(self) -> None:
        self.requests: list[ChatCompletionRequest] = []

    async def stream(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield ChatStreamEvent(
                kind=ChatStreamEventKind.THINKING_DELTA,
                content="先准备读取参数。",
            )
            yield ChatStreamEvent(
                kind=ChatStreamEventKind.TOOL_CALL_DELTA,
                tool_call=ChatToolCall(
                    call_id="call-1",
                    name="read_text_file",
                    arguments="",
                ),
            )
            yield ChatStreamEvent(
                kind=ChatStreamEventKind.TOOL_CALL_DELTA,
                tool_call=ChatToolCall(
                    call_id="call-1",
                    name="read_text_file",
                    arguments='{"file_path":"C:/work/app.py"}',
                ),
            )
            yield ChatStreamEvent(
                kind=ChatStreamEventKind.TOOL_CALL,
                tool_call=ChatToolCall(
                    call_id="call-1",
                    name="read_text_file",
                    arguments='{"file_path":"C:/work/app.py"}',
                ),
            )
            yield ChatStreamEvent(
                kind=ChatStreamEventKind.DONE,
                finish_reason="tool_calls",
            )
            return
        yield ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content="final answer")


class _RichToolCallingChatService:
    def __init__(self) -> None:
        self.requests: list[ChatCompletionRequest] = []

    async def stream(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield ChatStreamEvent(
                kind=ChatStreamEventKind.TOOL_CALL,
                tool_call=ChatToolCall(
                    call_id="capture-1",
                    name="capture_screen",
                    arguments="{}",
                ),
            )
            yield ChatStreamEvent(kind=ChatStreamEventKind.DONE, finish_reason="tool_calls")
            return
        yield ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content="看到了界面。")


class _MixedToolBatchChatService:
    def __init__(self) -> None:
        self.requests: list[ChatCompletionRequest] = []

    async def stream(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            for index, name in enumerate(
                (
                    "parallel_a",
                    "parallel_b",
                    "sequential_c",
                    "parallel_d",
                    "sequential_e",
                ),
                start=1,
            ):
                yield ChatStreamEvent(
                    kind=ChatStreamEventKind.TOOL_CALL,
                    tool_call=ChatToolCall(
                        call_id=f"call-{index}",
                        name=name,
                        arguments="{}",
                    ),
                )
            yield ChatStreamEvent(kind=ChatStreamEventKind.DONE, finish_reason="tool_calls")
            return
        yield ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content="final answer")


class _UsageToolLoopChatService:
    def __init__(self) -> None:
        self.requests: list[ChatCompletionRequest] = []

    async def stream(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield ChatStreamEvent(
                kind=ChatStreamEventKind.USAGE,
                usage=ChatUsage(
                    prompt_tokens=100,
                    completion_tokens=20,
                    total_tokens=120,
                    prompt_cache_hit_tokens=80,
                    prompt_cache_miss_tokens=20,
                    reasoning_tokens=5,
                ),
            )
            yield ChatStreamEvent(
                kind=ChatStreamEventKind.TOOL_CALL,
                tool_call=ChatToolCall(
                    call_id="call-1",
                    name="read_text_file",
                    arguments='{"file_path":"C:/work/app.py"}',
                ),
            )
            yield ChatStreamEvent(kind=ChatStreamEventKind.DONE, finish_reason="tool_calls")
            return
        yield ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content="final answer")
        yield ChatStreamEvent(
            kind=ChatStreamEventKind.USAGE,
            usage=ChatUsage(
                prompt_tokens=200,
                completion_tokens=30,
                total_tokens=230,
                prompt_cache_hit_tokens=150,
                prompt_cache_miss_tokens=50,
                reasoning_tokens=10,
            ),
        )


class _UsageThenConnectionFailureToolLoopChatService:
    def __init__(self) -> None:
        self.requests: list[ChatCompletionRequest] = []

    async def stream(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield ChatStreamEvent(
                kind=ChatStreamEventKind.USAGE,
                usage=ChatUsage(
                    prompt_tokens=100,
                    completion_tokens=20,
                    total_tokens=120,
                    prompt_cache_hit_tokens=80,
                    prompt_cache_miss_tokens=20,
                    reasoning_tokens=5,
                ),
            )
            yield ChatStreamEvent(
                kind=ChatStreamEventKind.TOOL_CALL,
                tool_call=ChatToolCall(
                    call_id="call-1",
                    name="read_text_file",
                    arguments='{"file_path":"C:/work/app.py"}',
                ),
            )
            yield ChatStreamEvent(kind=ChatStreamEventKind.DONE, finish_reason="tool_calls")
            return
        raise httpx.ConnectError(
            "connection reset",
            request=httpx.Request("POST", "https://example.test/chat/completions"),
        )


class _UsageThenErrorChatService:
    async def stream(self, _request):
        yield ChatStreamEvent(
            kind=ChatStreamEventKind.USAGE,
            usage=ChatUsage(prompt_tokens=7, completion_tokens=11, total_tokens=18),
        )
        yield ChatStreamEvent(kind=ChatStreamEventKind.ERROR, error="provider failed")


class _TwoRoundToolCallingChatService:
    def __init__(self) -> None:
        self.requests: list[ChatCompletionRequest] = []

    async def stream(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield ChatStreamEvent(kind=ChatStreamEventKind.THINKING_DELTA, content="第一步先看工作区。")
            yield ChatStreamEvent(
                kind=ChatStreamEventKind.TOOL_CALL,
                tool_call=ChatToolCall(
                    call_id="call-1",
                    name="read_text_file",
                    arguments='{"file_path":"C:/work/a.py"}',
                ),
            )
            yield ChatStreamEvent(kind=ChatStreamEventKind.DONE, finish_reason="tool_calls")
            return
        if len(self.requests) == 2:
            yield ChatStreamEvent(kind=ChatStreamEventKind.THINKING_DELTA, content="看到工作区后再读文件。")
            yield ChatStreamEvent(
                kind=ChatStreamEventKind.TOOL_CALL,
                tool_call=ChatToolCall(
                    call_id="call-2",
                    name="read_text_file",
                    arguments='{"file_path":"C:/work/b.py"}',
                ),
            )
            yield ChatStreamEvent(kind=ChatStreamEventKind.DONE, finish_reason="tool_calls")
            return
        yield ChatStreamEvent(kind=ChatStreamEventKind.THINKING_DELTA, content="最后整理答案。")
        yield ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content="final answer")


class _RepeatingToolCallingChatService:
    def __init__(self) -> None:
        self.requests: list[ChatCompletionRequest] = []

    async def stream(self, request):
        self.requests.append(request)
        yield ChatStreamEvent(
            kind=ChatStreamEventKind.TOOL_CALL,
            tool_call=ChatToolCall(
                call_id=f"call-{len(self.requests)}",
                name="read_text_file",
                arguments='{"file_path":"C:/work/app.py"}',
            ),
        )
        yield ChatStreamEvent(kind=ChatStreamEventKind.DONE, finish_reason="tool_calls")


class _FakeConversationService:
    def __init__(
        self,
        *,
        messages: tuple[ProjectConversationMessage, ...] = (),
        settings: ProjectConversationSessionSettings | None = None,
    ) -> None:
        self.appended = []
        self.cancelled_messages = []
        self.ai_run_records = []
        self.runtime_statuses = []
        self.messages = messages
        self.session = ProjectConversationSession(
            session_id="session-1",
            sequence_number=1,
            title="新对话",
            provider_id="volcengine",
            model_id="doubao-seed-1-6-flash",
            created_at="now",
            updated_at="now",
            message_count=0,
            settings=settings or ProjectConversationSessionSettings(),
        )

    def list_messages(self, _project_id, _session_id):
        return self.messages

    def update_session(self, *_args, **_kwargs):
        return self.session

    def append_message(self, project_id, session_id, **kwargs):
        self.appended.append(kwargs)
        message = ProjectConversationMessage(
            message_id=f"msg-{len(self.appended)}",
            session_id=session_id,
            role=kwargs["role"],
            content=kwargs["content"],
            thinking_content=kwargs.get("thinking_content", ""),
            usage=kwargs.get("usage"),
            context_tokens=kwargs.get("context_tokens"),
            provider_id=kwargs.get("provider_id"),
            model_id=kwargs.get("model_id"),
            status=kwargs.get("status", "done"),
            created_at="now",
            updated_at="now",
            name=kwargs.get("name"),
            tool_call_id=kwargs.get("tool_call_id"),
            tool_calls=kwargs.get("tool_calls", ()),
            content_parts=kwargs.get("content_parts", ()),
        )
        self.messages = (*self.messages, message)
        return message

    def cancel_assistant_message(
        self,
        project_id,
        session_id,
        message_id,
        *,
        usage=None,
        context_tokens=None,
        context_tokens_estimated=False,
    ):
        self.cancelled_messages.append(
            {
                "project_id": project_id,
                "session_id": session_id,
                "message_id": message_id,
                "usage": usage,
                "context_tokens": context_tokens,
                "context_tokens_estimated": context_tokens_estimated,
            }
        )
        message_number = int(message_id.removeprefix("msg-"))
        original = self.appended[message_number - 1]
        return ProjectConversationMessage(
            message_id=message_id,
            session_id=session_id,
            role=original["role"],
            content=original["content"],
            thinking_content=original.get("thinking_content", ""),
            usage=usage if usage is not None else original.get("usage"),
            context_tokens=(
                context_tokens
                if context_tokens is not None
                else original.get("context_tokens")
            ),
            context_tokens_estimated=context_tokens_estimated,
            provider_id=original.get("provider_id"),
            model_id=original.get("model_id"),
            status="cancelled",
            created_at="now",
            updated_at="now",
            tool_calls=original.get("tool_calls", ()),
        )

    def get_session(self, _project_id, _session_id):
        return self.session

    def get_cache_affinity_id(self, _project_id, session_id):
        return session_id

    def record_user_message_sent(self, _message):
        return None

    def record_ai_run_elapsed(
        self,
        user_message,
        *,
        assistant_message,
        elapsed_ms,
    ):
        self.ai_run_records.append(
            {
                "user_message": user_message,
                "assistant_message": assistant_message,
                "elapsed_ms": elapsed_ms,
            }
        )

    def save_session_runtime_status(self, project_id, session_id, runtime_status):
        self.runtime_statuses.append((project_id, session_id, runtime_status))

    def write_injection_preview(self, project_id, session_id, payload):
        self.injection_preview = (project_id, session_id, payload)


class _StatefulFakeConversationService(_FakeConversationService):
    def __init__(
        self,
        *,
        persisted_messages: tuple[ProjectConversationMessage, ...] = (),
        runtime_status: str = "idle",
    ) -> None:
        super().__init__()
        self.persisted_messages = list(persisted_messages)
        self.runtime_status = runtime_status
        self.update_session_calls = []

    def list_messages(self, _project_id, _session_id):
        return tuple(self.persisted_messages)

    def get_message_turn(self, _project_id, _session_id, user_message_id):
        matching_index = next(
            (
                index
                for index, message in enumerate(self.persisted_messages)
                if message.message_id == user_message_id
            ),
            None,
        )
        if matching_index is None:
            raise NotFoundError("Conversation user message was not found.")
        if self.persisted_messages[matching_index].role != "user":
            raise BadRequestError("Message is not a user message.")
        turn_messages = []
        for message in self.persisted_messages[matching_index:]:
            if turn_messages and message.role == "user":
                break
            turn_messages.append(message)
        return SimpleNamespace(items=tuple(turn_messages))

    def update_session(self, *args, **kwargs):
        self.update_session_calls.append((args, kwargs))
        return self.session

    def save_session_runtime_status(self, project_id, session_id, runtime_status):
        self.runtime_status = runtime_status
        super().save_session_runtime_status(project_id, session_id, runtime_status)

    def append_message(self, project_id, session_id, **kwargs):
        del project_id
        self.appended.append(kwargs)
        role = kwargs["role"]
        message_id = kwargs.get("message_id") or f"msg-{len(self.appended)}"
        message = ProjectConversationMessage(
            message_id=message_id,
            session_id=session_id,
            role=role,
            content=kwargs["content"],
            thinking_content=kwargs.get("thinking_content", ""),
            usage=kwargs.get("usage"),
            context_tokens=kwargs.get("context_tokens"),
            provider_id=None if role == "user" else kwargs.get("provider_id"),
            model_id=None if role == "user" else kwargs.get("model_id"),
            target_provider_id=kwargs.get("provider_id") if role == "user" else None,
            target_model_id=kwargs.get("model_id") if role == "user" else None,
            status=kwargs.get("status", "done"),
            created_at="now",
            updated_at="now",
            name=kwargs.get("name"),
            tool_call_id=kwargs.get("tool_call_id"),
            tool_calls=kwargs.get("tool_calls", ()),
            content_parts=kwargs.get("content_parts", ()),
        )
        self.persisted_messages.append(message)
        return message


class _BlockingAppendConversationService(_FakeConversationService):
    def __init__(self, *, delay_seconds: float) -> None:
        super().__init__()
        self.delay_seconds = delay_seconds
        self.started = threading.Event()
        self.finished = threading.Event()

    def append_message(self, project_id, session_id, **kwargs):
        if kwargs["role"] == "user":
            self.started.set()
            try:
                time.sleep(self.delay_seconds)
            finally:
                self.finished.set()
        return super().append_message(project_id, session_id, **kwargs)


class _FakeUsageService:
    def record_message_usage(self, **_kwargs):
        return None


class _RecordingUsageService(_FakeUsageService):
    def __init__(self) -> None:
        self.records = []

    def record_message_usage(self, **kwargs):
        self.records.append(kwargs)


class _FailingUsageService(_FakeUsageService):
    def record_message_usage(self, **_kwargs):
        raise RuntimeError("usage write failed")


class _FailingRecordUsageService(_FakeUsageService):
    def record_message_usage(self, **_kwargs):
        raise RuntimeError("usage record failed")


class _FakeNamingService:
    async def name_session_if_needed(self, *_args, **_kwargs):
        return None


class _BlockingNamingService:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def name_session_if_needed(self, *_args, **_kwargs):
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled.set()


class _FakeMemoryService:
    def __init__(self) -> None:
        self.compression_calls: list[tuple[str, str]] = []
        self.long_term_delivery_calls: list[tuple[str, str, str]] = []
        self.run_snapshots = []

    def build_request_with_compressed_context(self, request):
        return request

    def prepare_long_term_memory_delivery(
        self,
        project_id,
        session_id,
        user_message_id,
        **_kwargs,
    ):
        self.long_term_delivery_calls.append(
            (project_id, session_id, user_message_id)
        )
        return None

    def inject_long_term_memory_context(self, request, **_kwargs):
        return request

    async def compact_context_if_enabled(self, project_id, session_id, **_kwargs):
        self.compression_calls.append((project_id, session_id))
        self.run_snapshots.append(_kwargs.get("run_snapshot"))
        return None


class _DelayedMemoryService(_FakeMemoryService):
    def __init__(self) -> None:
        super().__init__()
        self.finished = False

    async def compact_context_if_enabled(self, project_id, session_id, **_kwargs):
        self.compression_calls.append((project_id, session_id))
        await asyncio.sleep(0)
        self.finished = True


class _BlockingModeMemoryService(_FakeMemoryService):
    def __init__(self) -> None:
        super().__init__()
        self.request_checks = 0
        self.blocking_values: list[bool | None] = []
        self.finished = False

    async def is_blocking_enabled(self) -> bool:
        return True

    async def compact_request_if_enabled(
        self,
        _project_id,
        _session_id,
        **kwargs,
    ):
        self.request_checks += 1
        self.blocking_values.append(kwargs.get("blocking"))

    async def compact_context_if_enabled(self, project_id, session_id, **kwargs):
        self.compression_calls.append((project_id, session_id))
        self.blocking_values.append(kwargs.get("blocking"))
        await asyncio.sleep(0)
        self.finished = True


class _BlockingMemoryService(_FakeMemoryService):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def compact_context_if_enabled(self, project_id, session_id, **_kwargs):
        self.compression_calls.append((project_id, session_id))
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled.set()


class _RewritingMemoryService(_FakeMemoryService):
    def build_request_with_compressed_context(self, request):
        return replace(
            request,
            messages=(
                ChatMessage(role=ChatMessageRole.USER, content="compressed context"),
            ),
        )


class _AfterRoundRewritingMemoryService(_FakeMemoryService):
    def __init__(self) -> None:
        super().__init__()
        self._ready = False

    def build_request_with_compressed_context(self, request):
        if not self._ready:
            return request
        return replace(
            request,
            messages=(
                ChatMessage(
                    role=ChatMessageRole.ASSISTANT,
                    content="compressed live context",
                ),
            ),
        )

    async def compact_context_if_enabled(self, project_id, session_id, **_kwargs):
        await super().compact_context_if_enabled(
            project_id,
            session_id,
            **_kwargs,
        )
        self._ready = True


class _FakeToolInjectionService:
    def __init__(self) -> None:
        self.enabled_tool_names: tuple[str, ...] | None = None

    def inject_request_tools(self, request, *, enabled_tool_names):
        self.enabled_tool_names = enabled_tool_names
        if enabled_tool_names == ():
            return request
        return replace(
            request,
            tools=(
                ChatToolDefinition(
                    name="read_text_file",
                    description="读取本地纯文本文件。",
                    parameters={
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"},
                        },
                    },
                ),
            ),
        )


class _FakeToolExecutionService:
    def is_parallel_tool(self, _tool_name: str) -> bool:
        return False

    def is_client_tool(self, _tool_name: str) -> bool:
        return False

    def execute(self, tool_call, *, context):
        assert context.workspace_root == "C:/work"
        assert context.project_id == "project-1"
        assert context.session_id == "session-1"
        return ChatToolResult(
            call_id=tool_call.call_id,
            name=tool_call.name,
            arguments=tool_call.arguments,
            ok=True,
            content='{"ok":true,"content":"hello"}',
            tool_project_id="tool_1",
        )


class _ClientToolExecutionService(_FakeToolExecutionService):
    def is_client_tool(self, tool_name: str) -> bool:
        return tool_name == "interact_ai_conversation"

    def prepare_client_tool(self, _tool_call):
        return PreparedClientToolExecution(
            tool_project_id="client-tool",
            dynamic=False,
            timeout_seconds=3600,
        )


class _WaitingClientToolBridge:
    def __init__(self) -> None:
        self.waiting = asyncio.Event()

    async def create_request(
        self,
        tool_call,
        *,
        project_id,
        session_id,
        timeout_seconds,
        model_context,
    ):
        return ChatClientToolRequest(
            request_id="client-request-1",
            call_id=tool_call.call_id,
            name=tool_call.name,
            arguments=tool_call.arguments,
            project_id=project_id,
            session_id=session_id,
            timeout_seconds=timeout_seconds,
            model_context=model_context,
        )

    async def wait_for_result(self, _request_id, *, timeout_seconds):
        del timeout_seconds
        self.waiting.set()
        await asyncio.Event().wait()


class _RichToolExecutionService(_FakeToolExecutionService):
    def execute(self, tool_call, *, context):
        assert context.provider_id == "provider-1"
        assert context.model_id == "model-1"
        assert context.input_modalities == ("text", "image")
        return ChatToolResult(
            call_id=tool_call.call_id,
            name=tool_call.name,
            arguments=tool_call.arguments,
            ok=True,
            content=(
                '{"ok":true,"content":[{"type":"resource_link",'
                '"uri":"tiance-project:///captures/dashboard.png",'
                '"name":"dashboard.png","mimeType":"image/png","size":256}]}'
            ),
            tool_project_id="tool_capture",
        )


class _FakeRuntimeCapabilitiesService:
    def get_capabilities(self, *, provider_id, model_id=None):
        assert provider_id == "provider-1"
        assert model_id == "model-1"
        return SimpleNamespace(input_modalities=("text", "image"))


class _PassthroughAttachmentService:
    def snapshot_image_ref(self, _project_id, _session_id, image_ref, **_kwargs):
        return image_ref


class _BlockingToolExecutionService(_FakeToolExecutionService):
    def __init__(self, *, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.started = threading.Event()
        self.finished = threading.Event()

    def execute(self, tool_call, *, context):
        self.started.set()
        try:
            time.sleep(self.delay_seconds)
            return super().execute(tool_call, context=context)
        finally:
            self.finished.set()


class _ParallelBlockingToolExecutionService(_FakeToolExecutionService):
    def __init__(self) -> None:
        self.started = threading.Event()
        self._started_count = 0
        self._lock = threading.Lock()

    def is_parallel_tool(self, tool_name: str) -> bool:
        return tool_name == "parallel_tool"

    def execute(self, tool_call, *, context):
        with self._lock:
            self._started_count += 1
            if self._started_count == 2:
                self.started.set()
        time.sleep(0.2)
        return super().execute(tool_call, context=context)


class _BlockSecondToolExecutionService(_FakeToolExecutionService):
    def __init__(self, *, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.started = threading.Event()

    def execute(self, tool_call, *, context):
        if tool_call.call_id == "call-2":
            self.started.set()
            time.sleep(self.delay_seconds)
        return super().execute(tool_call, context=context)


class _TimedToolExecutionService(_FakeToolExecutionService):
    def __init__(
        self,
        *,
        parallel_tool_names: set[str],
        delay_seconds: float,
    ) -> None:
        self.parallel_tool_names = parallel_tool_names
        self.delay_seconds = delay_seconds
        self.events: list[tuple[str, str, float]] = []
        self._lock = threading.Lock()

    def is_parallel_tool(self, tool_name: str) -> bool:
        return tool_name in self.parallel_tool_names

    def execute(self, tool_call, *, context):
        with self._lock:
            self.events.append(("start", tool_call.name, time.monotonic()))
        try:
            time.sleep(self.delay_seconds)
            return super().execute(tool_call, context=context)
        finally:
            with self._lock:
                self.events.append(("finish", tool_call.name, time.monotonic()))


class _FakeToolCallRecordService:
    def __init__(self) -> None:
        self.records = []

    def append_result(self, tool_result, *, project_id, session_id):
        self.records.append((tool_result, {"project_id": project_id, "session_id": session_id}))


class _FakeProject:
    name = "test"
    root_path = "C:/work"


class _FakeProjectService:
    def get_project(self, _project_id):
        return _FakeProject()
