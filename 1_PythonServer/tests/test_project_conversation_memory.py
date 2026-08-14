import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from app.core.errors import BadRequestError
from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatMessage,
    ChatMessageRole,
    ChatToolCall,
)
from app.domain.llm.functional_model_defaults import DEFAULT_MEMORY_COMPRESSION_PROMPT
from app.domain.llm.functional_model_settings import LlmFunctionalModelSettings
from app.domain.llm.generation_params import (
    LlmGenerationParams,
    LlmReasoningMode,
    LlmReasoningOptions,
)
from app.domain.llm.token_estimation_settings import (
    DEFAULT_TOKEN_ESTIMATION_SETTINGS,
)
from app.domain.project import Project
from app.repositories.project.conversation_compaction_repository import (
    ProjectConversationCompactionRepository,
)
from app.repositories.project.conversation_memory_repository import (
    ProjectConversationMemoryRepository,
)
from app.repositories.project.conversation_repository import (
    ProjectConversationRepository,
)
from app.services.project.conversation_memory import (
    ProjectConversationMemoryService,
    _compaction_record_needs_protocol_repair,
)
from app.services.project.conversation_memory_compaction import (
    build_conversation_compaction_plan,
)
from app.services.project.conversation_request_messages import (
    build_conversation_request_messages,
)
from app.services.project.conversation_request_provenance import (
    conversation_message_id,
    tag_conversation_message,
)
from app.services.project.conversation_run_snapshot import (
    ConversationRunSnapshot,
)
from app.services.project.memory_management import ProjectMemoryManagementService
from app.services.project.project_conversations import ProjectConversationService


PROJECT_ID = "00000000-0000-0000-0000-000000000123"
COMPACTION_RESULT = {
    "items": [
        {
            "content": "[当前状态] 旧历史已压缩为可继续工作的累计摘要。",
            "keywords": ["历史", "摘要"],
        }
    ],
    "handoff": "从仍保留的近期原文继续处理。",
}


class FakeProjectRepository:
    def __init__(self, root_path: str) -> None:
        Path(root_path).mkdir(parents=True, exist_ok=True)
        self.project = Project(
            project_id=PROJECT_ID,
            name="test",
            root_path=root_path,
            is_default=False,
            sort_order=0,
            created_at="now",
            updated_at="now",
        )

    def get_project(self, project_id: str) -> Project | None:
        return self.project if project_id == PROJECT_ID else None


class FakeFunctionalModelSettingsService:
    def __init__(self, **overrides) -> None:
        self._overrides = overrides

    def get_profile_settings(self, profile_key: str):
        return LlmFunctionalModelSettings(
            settings_id=profile_key,
            version=29,
            settings={
                "modelKey": "deepseek:deepseek-v4",
                "modelSource": "session",
                "prompt": DEFAULT_MEMORY_COMPRESSION_PROMPT,
                "failureRetryCount": 3,
                "generation": {
                    "temperature": 0.2,
                    "topP": 1,
                    "maxOutputTokens": 8192,
                    "reasoning": {"mode": "off"},
                },
                **self._overrides,
            },
            created_at="now",
            updated_at="now",
        )


def _create_services(tmp_path, *, settings=None, functional_overrides=None):
    project_repository = FakeProjectRepository(str(tmp_path / "project"))
    conversation_service = ProjectConversationService(
        ProjectConversationRepository(project_repository)
    )
    session = conversation_service.create_session(
        PROJECT_ID,
        title="主会话",
        provider_id="deepseek",
        model_id="deepseek-v4",
        settings={
            "memory_context_token_trigger_threshold": 20,
            "memory_raw_context_token_reserve": 10,
            **(settings or {}),
        },
    )
    memory_repository = ProjectConversationMemoryRepository(
        project_repository,
        global_memory_root=tmp_path / "runtime" / "memory",
    )
    memory_service = ProjectConversationMemoryService(
        conversation_service,
        memory_repository,
        FakeFunctionalModelSettingsService(**(functional_overrides or {})),
        compaction_repository=ProjectConversationCompactionRepository(
            project_repository
        ),
    )
    return conversation_service, session, memory_repository, memory_service


def _append_turn(
    conversation_service: ProjectConversationService,
    session_id: str,
    number: int,
):
    user = conversation_service.append_message(
        PROJECT_ID,
        session_id,
        role="user",
        content=f"第 {number} 轮用户需求：" + ("甲" * 80),
        provider_id="deepseek",
        model_id="deepseek-v4",
    )
    assistant = conversation_service.append_message(
        PROJECT_ID,
        session_id,
        role="assistant",
        content=f"第 {number} 轮助手回复：" + ("乙" * 80),
        provider_id="deepseek",
        model_id="deepseek-v4",
        context_tokens=250000,
    )
    return user, assistant


def _snapshot_for_latest_assistant(
    conversation_service: ProjectConversationService,
    session_id: str,
) -> ConversationRunSnapshot:
    session = conversation_service.get_session(PROJECT_ID, session_id)
    assert session is not None
    messages = conversation_service.list_messages(PROJECT_ID, session_id)
    assistant = messages[-1]
    return ConversationRunSnapshot(
        model_request=ChatCompletionRequest(
            provider_id="deepseek",
            model_id="deepseek-v4",
            project_id=PROJECT_ID,
            session_id=session_id,
            messages=build_conversation_request_messages(
                messages[:-1],
                None,
                session.settings,
            ),
        ),
        assistant_response=tag_conversation_message(
            ChatMessage(
                role=ChatMessageRole.ASSISTANT,
                content=assistant.content,
            ),
            assistant.message_id,
        ),
        context_tokens=250000,
    )


def _install_successful_runner(
    conversation: ProjectConversationService,
    memory: ProjectConversationMemoryService,
    *,
    calls: list[ChatCompletionRequest] | None = None,
):
    async def run(request: ChatCompletionRequest) -> None:
        if calls is not None:
            calls.append(request)
        conversation.append_message(
            PROJECT_ID,
            request.session_id,
            role="user",
            content=request.messages[-1].content,
        )
        conversation.append_message(
            PROJECT_ID,
            request.session_id,
            role="assistant",
            content="",
            provider_id=request.provider_id,
            model_id=request.model_id,
            tool_calls=(
                ChatToolCall(
                    call_id="call-submit",
                    name="submit_memory_compaction",
                    arguments='{"result":{}}',
                ),
            ),
            context_tokens=186558,
        )
        memory.submit_compaction_result(
            PROJECT_ID,
            request.session_id,
            COMPACTION_RESULT,
        )

    memory.set_functional_conversation_runner(run)


def test_token_plan_compresses_fixed_target_and_keeps_token_reserve():
    messages = tuple(
        tag_conversation_message(
            ChatMessage(
                role=(
                    ChatMessageRole.USER
                    if index % 2 == 0
                    else ChatMessageRole.ASSISTANT
                ),
                content=str(index) + ("内容" * 40),
            ),
            f"msg_{index}",
        )
        for index in range(8)
    )
    snapshot = ConversationRunSnapshot(
        model_request=ChatCompletionRequest(
            provider_id="p",
            model_id="m",
            messages=messages[:-1],
        ),
        assistant_response=messages[-1],
        context_tokens=500,
    )

    plan = build_conversation_compaction_plan(
        snapshot,
        [],
        target_token_count=40,
        protected_token_reserve=30,
        token_estimation_settings=DEFAULT_TOKEN_ESTIMATION_SETTINGS,
    )

    assert plan is not None
    assert plan.newly_covered_token_count >= 40
    assert plan.protected_tail_token_count >= 30
    assert set(plan.source_message_ids).isdisjoint(
        {"msg_6", "msg_7"}
    )
    assert plan.source_boundary_message_id not in {"msg_6", "msg_7"}
    assert plan.snapshot_boundary_message_id == "msg_7"


def test_full_context_fixed_content_counts_toward_compaction_trigger():
    messages = tuple(
        tag_conversation_message(
            ChatMessage(
                role=ChatMessageRole.USER,
                content="内容" * 20,
            ),
            f"msg_{index}",
        )
        for index in range(3)
    )
    snapshot = ConversationRunSnapshot(
        model_request=ChatCompletionRequest(
            provider_id="p",
            model_id="m",
            messages=messages[:-1],
        ),
        assistant_response=messages[-1],
        context_tokens=110,
    )

    plan = build_conversation_compaction_plan(
        snapshot,
        [],
        target_token_count=100,
        protected_token_reserve=10,
        token_estimation_settings=DEFAULT_TOKEN_ESTIMATION_SETTINGS,
    )

    assert plan is not None
    assert plan.newly_covered_token_count < 100
    assert (
        build_conversation_compaction_plan(
            replace(snapshot, context_tokens=109),
            [],
            target_token_count=100,
            protected_token_reserve=10,
            token_estimation_settings=DEFAULT_TOKEN_ESTIMATION_SETTINGS,
        )
        is None
    )


def test_zero_token_reserve_does_not_protect_a_hidden_message():
    messages = tuple(
        tag_conversation_message(
            ChatMessage(
                role=ChatMessageRole.USER,
                content="内容" * 40,
            ),
            f"msg_{index}",
        )
        for index in range(3)
    )
    plan = build_conversation_compaction_plan(
        ConversationRunSnapshot(
            model_request=ChatCompletionRequest(
                provider_id="p",
                model_id="m",
                messages=messages[:-1],
            ),
            assistant_response=messages[-1],
            context_tokens=500,
        ),
        [],
        target_token_count=1,
        protected_token_reserve=0,
        token_estimation_settings=DEFAULT_TOKEN_ESTIMATION_SETTINGS,
    )

    assert plan is not None
    assert plan.protected_tail_token_count == 0
    assert plan.source_message_ids[0] == "msg_0"


def test_token_plan_keeps_tool_call_and_results_in_one_atomic_group():
    messages = (
        tag_conversation_message(
            ChatMessage(
                role=ChatMessageRole.ASSISTANT,
                content="",
                tool_calls=(
                    ChatToolCall(
                        call_id="call-1",
                        name="read_file",
                        arguments="{}",
                    ),
                ),
            ),
            "assistant-call",
        ),
        tag_conversation_message(
            ChatMessage(
                role=ChatMessageRole.TOOL,
                content='{"ok":true}',
                tool_call_id="call-1",
            ),
            "tool-result",
        ),
        tag_conversation_message(
            ChatMessage(
                role=ChatMessageRole.USER,
                content="近期请求",
            ),
            "recent-user",
        ),
    )
    plan = build_conversation_compaction_plan(
        ConversationRunSnapshot(
            model_request=ChatCompletionRequest(
                provider_id="p",
                model_id="m",
                messages=messages[:-1],
            ),
            assistant_response=messages[-1],
            context_tokens=500,
        ),
        [],
        target_token_count=1,
        protected_token_reserve=1,
        token_estimation_settings=DEFAULT_TOKEN_ESTIMATION_SETTINGS,
    )

    assert plan is not None
    assert plan.source_message_ids == ("assistant-call", "tool-result")
    assert [
        conversation_message_id(message)
        for message in plan.source_messages
    ] == ["assistant-call", "tool-result"]


def test_token_plan_uses_last_legal_boundary_before_unfinished_tool_call():
    previous_user = tag_conversation_message(
        ChatMessage(
            role=ChatMessageRole.USER,
            content="此前请求" * 40,
        ),
        "previous-user",
    )
    unfinished_tool_call = tag_conversation_message(
        ChatMessage(
            role=ChatMessageRole.ASSISTANT,
            content="",
            tool_calls=(
                ChatToolCall(
                    call_id="call-1",
                    name="read_file",
                    arguments="{}",
                ),
            ),
        ),
        "unfinished-tool-call",
    )
    plan = build_conversation_compaction_plan(
        ConversationRunSnapshot(
            model_request=ChatCompletionRequest(
                provider_id="p",
                model_id="m",
                messages=(previous_user,),
            ),
            assistant_response=unfinished_tool_call,
            context_tokens=500,
        ),
        [],
        target_token_count=1,
        protected_token_reserve=0,
        token_estimation_settings=DEFAULT_TOKEN_ESTIMATION_SETTINGS,
    )

    assert plan is not None
    assert plan.source_boundary_message_id == "previous-user"
    assert plan.snapshot_boundary_message_id == "previous-user"
    assert "unfinished-tool-call" not in plan.source_message_ids


def test_token_plan_reselects_tool_group_from_legacy_partial_compaction():
    messages = (
        tag_conversation_message(
            ChatMessage(
                role=ChatMessageRole.ASSISTANT,
                content="",
                tool_calls=(
                    ChatToolCall(
                        call_id="call-1",
                        name="read_file",
                        arguments="{}",
                    ),
                ),
            ),
            "assistant-call",
        ),
        tag_conversation_message(
            ChatMessage(
                role=ChatMessageRole.TOOL,
                content='{"ok":true}',
                tool_call_id="call-1",
            ),
            "tool-result",
        ),
        tag_conversation_message(
            ChatMessage(
                role=ChatMessageRole.USER,
                content="近期请求",
            ),
            "recent-user",
        ),
    )
    plan = build_conversation_compaction_plan(
        ConversationRunSnapshot(
            model_request=ChatCompletionRequest(
                provider_id="p",
                model_id="m",
                messages=messages[:-1],
            ),
            assistant_response=messages[-1],
            context_tokens=500,
        ),
        [
            {
                "compression_id": "legacy-partial",
                "status": "completed",
                "source_type": "conversation_context",
                "source_message_ids": ["assistant-call"],
                "result": {
                    "items": [{"content": "旧摘要", "keywords": []}],
                    "handoff": "继续",
                },
            }
        ],
        target_token_count=1,
        protected_token_reserve=1,
        token_estimation_settings=DEFAULT_TOKEN_ESTIMATION_SETTINGS,
    )

    assert plan is not None
    assert plan.source_message_ids == ("assistant-call", "tool-result")


def test_partial_tool_group_record_is_allowed_to_enter_repair_compaction():
    request = ChatCompletionRequest(
        provider_id="p",
        model_id="m",
        messages=(
            tag_conversation_message(
                ChatMessage(
                    role=ChatMessageRole.ASSISTANT,
                    content="",
                    tool_calls=(
                        ChatToolCall(
                            call_id="call-1",
                            name="read_file",
                            arguments="{}",
                        ),
                    ),
                ),
                "assistant-call",
            ),
            tag_conversation_message(
                ChatMessage(
                    role=ChatMessageRole.TOOL,
                    content='{"ok":true}',
                    tool_call_id="call-1",
                ),
                "tool-result",
            ),
        ),
    )

    assert _compaction_record_needs_protocol_repair(
        request,
        {"source_message_ids": ["assistant-call"]},
    )
    assert not _compaction_record_needs_protocol_repair(
        request,
        {"source_message_ids": ["assistant-call", "tool-result"]},
    )


def test_compaction_creates_named_function_session_and_replaces_source_history(
    tmp_path,
):
    conversation, session, repository, memory = _create_services(
        tmp_path,
        settings={"enabled_tool_names": ["read_file"]},
    )
    _append_turn(conversation, session.session_id, 1)
    _append_turn(conversation, session.session_id, 2)
    source_messages = conversation.list_messages(
        PROJECT_ID,
        session.session_id,
    )
    calls: list[ChatCompletionRequest] = []
    _install_successful_runner(conversation, memory, calls=calls)

    asyncio.run(
        memory.compact_context_if_enabled(
            PROJECT_ID,
            session.session_id,
            session_snapshot=session,
            run_snapshot=_snapshot_for_latest_assistant(
                conversation,
                session.session_id,
            ),
        )
    )

    sessions = conversation.list_sessions(PROJECT_ID)
    function_session = next(
        item for item in sessions if item.session_id != session.session_id
    )
    nodes, _ = conversation.list_branch_graph(PROJECT_ID)
    function_node = next(
        node for node in nodes if node.session_id == function_session.session_id
    )
    records = repository.list_compressions(PROJECT_ID, session.session_id)
    assert function_session.title == "主会话_1"
    assert function_node.relation_kind == "functional"
    assert function_node.function_type == "memory_compaction"
    assert function_node.created_by == "system"
    assert function_node.history_mode == "copy"
    assert function_node.source_message_id == source_messages[-1].message_id
    assert function_session.settings.enabled_tool_names == ("read_file",)
    assert conversation.get_cache_affinity_id(
        PROJECT_ID,
        function_session.session_id,
    ) == conversation.get_cache_affinity_id(
        PROJECT_ID,
        session.session_id,
    )
    assert len(calls) == 1
    assert records[-1]["status"] == "completed"
    assert records[-1]["result"] == COMPACTION_RESULT
    assert records[-1]["source_token_count"] == 186558
    assert records[-1]["source_token_source"] == "provider_reported"
    assert records[-1]["source_message_count"] < len(source_messages)
    source_status_messages = [
        message
        for message in conversation.list_messages(PROJECT_ID, session.session_id)
        if message.role == "system" and message.name == "memory_compaction"
    ]
    assert [message.content for message in source_status_messages] == [
        "正在异步执行记忆压缩。",
        "已完成异步记忆压缩。",
    ]
    assert [message.status for message in source_status_messages] == [
        "running",
        "done",
    ]
    function_messages = conversation.list_messages(
        PROJECT_ID,
        function_session.session_id,
    )
    assert [
        message.origin_message_id
        for message in function_messages[: len(source_messages)]
    ] == [message.message_id for message in source_messages]

    source = conversation.get_session(PROJECT_ID, session.session_id)
    assert source is not None
    request = ChatCompletionRequest(
        provider_id="deepseek",
        model_id="deepseek-v4",
        project_id=PROJECT_ID,
        session_id=session.session_id,
        messages=build_conversation_request_messages(
            conversation.list_messages(PROJECT_ID, session.session_id),
            None,
            source.settings,
        ),
    )
    compacted = memory.build_request_with_compressed_context(request)
    assert compacted.messages[0].content.startswith("历史累计摘要：")
    assert len(compacted.messages) == (
        1 + len(source_messages) - records[-1]["source_message_count"]
    )
    assert compacted.messages[-1].content == source_messages[-1].content
    assert "交接总结：" in compacted.messages[0].content
    assert compacted.messages[0].preview_metadata["memory_compression"][
        "compression_id"
    ] == records[-1]["compression_id"]

    function_request = ChatCompletionRequest(
        provider_id=function_session.provider_id or "",
        model_id=function_session.model_id or "",
        project_id=PROJECT_ID,
        session_id=function_session.session_id,
        messages=build_conversation_request_messages(
            conversation.list_messages(
                PROJECT_ID,
                function_session.session_id,
            ),
            None,
            function_session.settings,
        ),
    )
    compacted_function = memory.build_request_with_compressed_context(
        function_request
    )
    assert compacted_function.messages == function_request.messages
    compaction_task_message = next(
        message
        for message in compacted_function.messages
        if message.role == ChatMessageRole.USER
        and "submit_memory_compaction" in message.content
    )
    assert compaction_task_message.content == DEFAULT_MEMORY_COMPRESSION_PROMPT
    assert "只调用一次 submit_memory_compaction" in compaction_task_message.content
    assert '"result": {' in compaction_task_message.content
    assert '"items": [' in compaction_task_message.content
    assert "字段不得增加、删除或改名" in compaction_task_message.content
    assert "最近用户请求：" in compaction_task_message.content


def test_session_model_compaction_uses_triggering_request_generation(tmp_path):
    conversation, session, _, memory = _create_services(
        tmp_path,
        settings={"system_prompt": "主会话系统提示词"},
    )
    _append_turn(conversation, session.session_id, 1)
    _append_turn(conversation, session.session_id, 2)
    calls: list[ChatCompletionRequest] = []
    _install_successful_runner(conversation, memory, calls=calls)
    snapshot = _snapshot_for_latest_assistant(
        conversation,
        session.session_id,
    )
    request_generation = LlmGenerationParams(
        temperature=0.73,
        top_p=0.84,
        presence_penalty=0.15,
        frequency_penalty=0.25,
        max_output_tokens=4567,
        reasoning=LlmReasoningOptions(
            mode=LlmReasoningMode.HIGH,
            budget_tokens=3210,
        ),
    )
    snapshot = replace(
        snapshot,
        model_request=replace(
            snapshot.model_request,
            provider_id="active-provider",
            model_id="active-model",
            generation=request_generation,
        ),
    )

    asyncio.run(
        memory.compact_context_if_enabled(
            PROJECT_ID,
            session.session_id,
            session_snapshot=session,
            run_snapshot=snapshot,
        )
    )

    assert len(calls) == 1
    assert calls[0].provider_id == "active-provider"
    assert calls[0].model_id == "active-model"
    assert calls[0].generation == request_generation
    function_session = next(
        item
        for item in conversation.list_sessions(PROJECT_ID)
        if item.session_id != session.session_id
    )
    assert function_session.settings.system_prompt == "主会话系统提示词"


def test_blocking_compaction_uses_blocking_status_messages(tmp_path):
    conversation, session, _, memory = _create_services(
        tmp_path,
        functional_overrides={"blockingEnabled": True},
    )
    _append_turn(conversation, session.session_id, 1)
    _append_turn(conversation, session.session_id, 2)
    _install_successful_runner(conversation, memory)

    assert asyncio.run(memory.is_blocking_enabled()) is True
    asyncio.run(
        memory.compact_context_if_enabled(
            PROJECT_ID,
            session.session_id,
            blocking=True,
            session_snapshot=session,
            run_snapshot=_snapshot_for_latest_assistant(
                conversation,
                session.session_id,
            ),
        )
    )

    status_messages = [
        message
        for message in conversation.list_messages(PROJECT_ID, session.session_id)
        if message.role == "system" and message.name == "memory_compaction"
    ]
    assert [message.content for message in status_messages] == [
        "正在执行记忆压缩。",
        "已完成记忆压缩。",
    ]


def test_dedicated_model_compaction_keeps_profile_generation(tmp_path):
    conversation, session, _, memory = _create_services(
        tmp_path,
        functional_overrides={
            "modelSource": "dedicated",
            "modelKey": "memory-provider:memory-model",
        },
    )
    _append_turn(conversation, session.session_id, 1)
    _append_turn(conversation, session.session_id, 2)
    calls: list[ChatCompletionRequest] = []
    _install_successful_runner(conversation, memory, calls=calls)
    snapshot = _snapshot_for_latest_assistant(
        conversation,
        session.session_id,
    )
    snapshot = replace(
        snapshot,
        model_request=replace(
            snapshot.model_request,
            generation=LlmGenerationParams(
                temperature=0.73,
                max_output_tokens=4567,
            ),
        ),
    )

    asyncio.run(
        memory.compact_context_if_enabled(
            PROJECT_ID,
            session.session_id,
            session_snapshot=session,
            run_snapshot=snapshot,
        )
    )

    assert len(calls) == 1
    assert calls[0].provider_id == "memory-provider"
    assert calls[0].model_id == "memory-model"
    assert calls[0].generation == LlmGenerationParams(
        temperature=0.2,
        top_p=1.0,
        max_output_tokens=8192,
        reasoning=LlmReasoningOptions(mode=LlmReasoningMode.OFF),
    )
    function_session = next(
        item
        for item in conversation.list_sessions(PROJECT_ID)
        if item.session_id != session.session_id
    )
    assert function_session.settings.system_prompt == calls[0].messages[0].content
    assert "submit_memory_compaction" in function_session.settings.system_prompt


def test_compaction_uses_configured_prompt_without_hidden_suffix(tmp_path):
    configured_prompt = "这是用户保存的完整压缩提示词。"
    conversation, session, _, memory = _create_services(
        tmp_path,
        functional_overrides={
            "modelSource": "dedicated",
            "modelKey": "memory-provider:memory-model",
            "prompt": configured_prompt,
        },
    )
    _append_turn(conversation, session.session_id, 1)
    _append_turn(conversation, session.session_id, 2)
    calls: list[ChatCompletionRequest] = []
    _install_successful_runner(conversation, memory, calls=calls)

    asyncio.run(
        memory.compact_context_if_enabled(
            PROJECT_ID,
            session.session_id,
            session_snapshot=session,
            run_snapshot=_snapshot_for_latest_assistant(
                conversation,
                session.session_id,
            ),
        )
    )

    assert len(calls) == 1
    assert calls[0].messages[-1].content == configured_prompt
    function_session = next(
        item
        for item in conversation.list_sessions(PROJECT_ID)
        if item.session_id != session.session_id
    )
    assert function_session.settings.system_prompt == configured_prompt


def test_normal_conversation_tool_call_returns_clear_not_needed_result(tmp_path):
    conversation, session, repository, memory = _create_services(tmp_path)

    outcome = memory.handle_compaction_tool_call(
        PROJECT_ID,
        session.session_id,
        {},
    )

    assert outcome["action"] == "not_needed"
    assert repository.list_compressions(PROJECT_ID, session.session_id) == []


def test_normal_conversation_tool_call_schedules_manual_compaction(tmp_path):
    conversation, session, repository, memory = _create_services(
        tmp_path,
        settings={"memory_context_token_trigger_threshold": 100000},
    )
    _append_turn(conversation, session.session_id, 1)
    _append_turn(conversation, session.session_id, 2)

    outcome = memory.handle_compaction_tool_call(
        PROJECT_ID,
        session.session_id,
        {},
    )

    assert outcome["action"] == "scheduled"
    assert outcome["request"]["trigger_type"] == "manual_tool"

    calls: list[ChatCompletionRequest] = []
    _install_successful_runner(conversation, memory, calls=calls)
    asyncio.run(
        memory.compact_context_if_enabled(
            PROJECT_ID,
            session.session_id,
            session_snapshot=session,
            run_snapshot=_snapshot_for_latest_assistant(
                conversation,
                session.session_id,
            ),
        )
    )

    records = repository.list_compressions(PROJECT_ID, session.session_id)
    assert len(calls) == 1
    assert records[-1]["status"] == "completed"
    assert records[-1]["trigger"]["trigger_type"] == "manual_tool"
    compaction_repository = ProjectConversationCompactionRepository(
        FakeProjectRepository(str(tmp_path / "project"))
    )
    assert (
        compaction_repository.read_manual_compaction_request(
            PROJECT_ID,
            session.session_id,
        )
        is None
    )


def test_concurrent_checks_create_only_one_compaction_session(tmp_path):
    conversation, session, repository, memory = _create_services(tmp_path)
    _append_turn(conversation, session.session_id, 1)
    _append_turn(conversation, session.session_id, 2)
    calls: list[ChatCompletionRequest] = []
    _install_successful_runner(conversation, memory, calls=calls)
    snapshot = _snapshot_for_latest_assistant(
        conversation,
        session.session_id,
    )

    async def run_both():
        await asyncio.gather(
            memory.compact_context_if_enabled(
                PROJECT_ID,
                session.session_id,
                session_snapshot=session,
                run_snapshot=snapshot,
            ),
            memory.compact_context_if_enabled(
                PROJECT_ID,
                session.session_id,
                session_snapshot=session,
                run_snapshot=snapshot,
            ),
        )

    asyncio.run(run_both())
    assert len(calls) == 1
    assert len(repository.list_compressions(PROJECT_ID, session.session_id)) == 1


def test_queued_check_honors_current_disabled_setting(tmp_path):
    conversation, stale_session_snapshot, repository, memory = _create_services(tmp_path)
    _append_turn(conversation, stale_session_snapshot.session_id, 1)
    _append_turn(conversation, stale_session_snapshot.session_id, 2)
    conversation.update_session(
        PROJECT_ID,
        stale_session_snapshot.session_id,
        settings={"memory_compression_enabled": False},
        should_update_settings=True,
    )
    calls: list[ChatCompletionRequest] = []
    _install_successful_runner(conversation, memory, calls=calls)

    asyncio.run(
        memory.compact_context_if_enabled(
            PROJECT_ID,
            stale_session_snapshot.session_id,
            session_snapshot=stale_session_snapshot,
            run_snapshot=_snapshot_for_latest_assistant(
                conversation,
                stale_session_snapshot.session_id,
            ),
        )
    )

    assert calls == []
    assert repository.list_compressions(
        PROJECT_ID,
        stale_session_snapshot.session_id,
    ) == []


def test_failed_attempt_retries_in_a_new_function_session(tmp_path):
    conversation, session, repository, memory = _create_services(
        tmp_path,
        functional_overrides={"failureRetryCount": 1},
    )
    _append_turn(conversation, session.session_id, 1)
    _append_turn(conversation, session.session_id, 2)
    calls: list[str] = []

    async def run(request: ChatCompletionRequest) -> None:
        calls.append(request.session_id)
        if len(calls) == 1:
            raise TimeoutError("temporary timeout")
        conversation.append_message(
            PROJECT_ID,
            request.session_id,
            role="assistant",
            content="",
            provider_id=request.provider_id,
            model_id=request.model_id,
            tool_calls=(
                ChatToolCall(
                    call_id="call-submit",
                    name="submit_memory_compaction",
                    arguments='{"result":{}}',
                ),
            ),
            context_tokens=120,
        )
        memory.submit_compaction_result(
            PROJECT_ID,
            request.session_id,
            COMPACTION_RESULT,
        )

    memory.set_functional_conversation_runner(run)
    asyncio.run(
        memory.compact_context_if_enabled(
            PROJECT_ID,
            session.session_id,
            session_snapshot=session,
            run_snapshot=_snapshot_for_latest_assistant(
                conversation,
                session.session_id,
            ),
        )
    )

    records = repository.list_compressions(PROJECT_ID, session.session_id)
    assert len(calls) == 2
    assert calls[0] != calls[1]
    assert [record["status"] for record in records] == ["failed", "completed"]
    assert records[1]["retry_of"] == records[0]["compression_id"]
    assert records[1]["source_message_ids"] == records[0]["source_message_ids"]
    status_messages = [
        message
        for message in conversation.list_messages(PROJECT_ID, session.session_id)
        if message.role == "system" and message.name == "memory_compaction"
    ]
    assert [message.content for message in status_messages] == [
        "正在异步执行记忆压缩。",
        "异步记忆压缩失败，正在重试。",
        "已完成异步记忆压缩。",
    ]
    function_titles = sorted(
        item.title
        for item in conversation.list_sessions(PROJECT_ID)
        if item.session_id != session.session_id
    )
    assert function_titles == [
        "主会话_1",
        "主会话_2",
    ]


def test_zero_retry_setting_stops_after_first_failed_function_session(tmp_path):
    conversation, session, repository, memory = _create_services(
        tmp_path,
        functional_overrides={"failureRetryCount": 0},
    )
    _append_turn(conversation, session.session_id, 1)
    _append_turn(conversation, session.session_id, 2)
    function_session_ids: list[str] = []

    async def run(request: ChatCompletionRequest) -> None:
        assert request.session_id is not None
        function_session_ids.append(request.session_id)
        raise TimeoutError("temporary timeout")

    memory.set_functional_conversation_runner(run)
    asyncio.run(
        memory.compact_context_if_enabled(
            PROJECT_ID,
            session.session_id,
            session_snapshot=session,
            run_snapshot=_snapshot_for_latest_assistant(
                conversation,
                session.session_id,
            ),
        )
    )

    records = repository.list_compressions(PROJECT_ID, session.session_id)
    assert len(function_session_ids) == 1
    assert [record["status"] for record in records] == ["failed"]
    assert len(conversation.list_sessions(PROJECT_ID)) == 2


def test_compaction_function_session_defaults_disable_memory_automation(tmp_path):
    conversation, session, _, memory = _create_services(tmp_path)
    _append_turn(conversation, session.session_id, 1)
    _append_turn(conversation, session.session_id, 2)
    observed = False

    async def run(request: ChatCompletionRequest) -> None:
        nonlocal observed
        function_session = conversation.get_session(
            PROJECT_ID,
            request.session_id,
        )
        assert function_session is not None
        await memory.compact_request_if_enabled(
            PROJECT_ID,
            request.session_id,
            model_request=request,
            session_snapshot=function_session,
        )
        observed = True
        conversation.append_message(
            PROJECT_ID,
            request.session_id,
            role="assistant",
            content="",
            provider_id=request.provider_id,
            model_id=request.model_id,
            tool_calls=(
                ChatToolCall(
                    call_id="call-submit",
                    name="submit_memory_compaction",
                    arguments='{"result":{}}',
                ),
            ),
            context_tokens=100,
        )
        memory.submit_compaction_result(
            PROJECT_ID,
            request.session_id,
            COMPACTION_RESULT,
        )

    memory.set_functional_conversation_runner(run)
    asyncio.run(
        memory.compact_context_if_enabled(
            PROJECT_ID,
            session.session_id,
            session_snapshot=session,
            run_snapshot=_snapshot_for_latest_assistant(
                conversation,
                session.session_id,
            ),
        )
    )
    assert observed is True
    assert len(conversation.list_sessions(PROJECT_ID)) == 2

    function_session = next(
        item
        for item in conversation.list_sessions(PROJECT_ID)
        if item.session_id != session.session_id
    )
    assert function_session.settings.memory_compression_enabled is False
    assert function_session.settings.project_memory_extraction_enabled is False
    assert function_session.settings.global_memory_extraction_enabled is False
    assert function_session.settings.project_memory_enabled is True
    assert function_session.settings.global_memory_enabled is True
    reenabled = conversation.update_session(
        PROJECT_ID,
        function_session.session_id,
        settings={
            "memory_compression_enabled": True,
            "project_memory_extraction_enabled": True,
            "global_memory_extraction_enabled": True,
        },
        should_update_settings=True,
    )
    assert reenabled.settings.memory_compression_enabled is True
    assert reenabled.settings.project_memory_extraction_enabled is True
    assert reenabled.settings.global_memory_extraction_enabled is True


def test_request_context_does_not_truncate_large_history(tmp_path):
    conversation, session, repository, memory = _create_services(tmp_path)
    turns = [_append_turn(conversation, session.session_id, index) for index in range(80)]
    covered = [
        message.message_id
        for turn in turns[:10]
        for message in turn
    ]
    repository.append_compression(
        PROJECT_ID,
        session.session_id,
        {
            "compression_id": "cmp_large",
            "status": "completed",
            "source_type": "conversation_context",
            "source_message_ids": covered,
            "result": COMPACTION_RESULT,
        },
    )
    request = ChatCompletionRequest(
        provider_id="deepseek",
        model_id="deepseek-v4",
        project_id=PROJECT_ID,
        session_id=session.session_id,
        messages=build_conversation_request_messages(
            conversation.list_messages(PROJECT_ID, session.session_id),
            None,
            session.settings,
        ),
    )
    compacted = memory.build_request_with_compressed_context(request)

    assert len(compacted.messages) == 1 + (70 * 2)
    assert compacted.messages[-1].content.startswith("第 79 轮助手回复")


def test_memory_management_remains_independent_from_compaction(tmp_path):
    repository = ProjectConversationMemoryRepository(
        FakeProjectRepository(str(tmp_path / "project")),
        global_memory_root=tmp_path / "runtime" / "memory",
    )
    service = ProjectMemoryManagementService(repository)
    added = service.apply_operation(
        scope="project",
        operation="add",
        project_id=PROJECT_ID,
        content="工具系统长期规则。",
        keywords=["工具系统"],
        reason="用户明确要求保存",
    )
    memory_id = added["memory_id"]
    service.apply_operation(
        scope="project",
        operation="update",
        project_id=PROJECT_ID,
        memory_id=memory_id,
        content="工具系统更新后的长期规则。",
        keywords=["工具系统"],
        reason="用户明确替换旧规则",
    )
    assert repository.list_project_memory_context(PROJECT_ID)[0]["content"] == (
        "工具系统更新后的长期规则。"
    )


def test_memory_management_requires_explicit_reason(tmp_path):
    repository = ProjectConversationMemoryRepository(
        FakeProjectRepository(str(tmp_path / "project")),
        global_memory_root=tmp_path / "runtime" / "memory",
    )
    with pytest.raises(BadRequestError, match="变更原因"):
        ProjectMemoryManagementService(repository).apply_operation(
            scope="project",
            operation="add",
            project_id=PROJECT_ID,
            content="无依据记忆",
            reason=" ",
        )
