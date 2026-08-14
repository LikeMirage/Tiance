import asyncio
from datetime import UTC, datetime

from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatMessage,
    ChatMessageRole,
    ChatToolCall,
)
from app.domain.llm.functional_model_defaults import (
    DEFAULT_GLOBAL_MEMORY_MANAGEMENT_PROMPT,
    DEFAULT_PROJECT_MEMORY_MANAGEMENT_PROMPT,
)
from app.domain.llm.functional_model_settings import LlmFunctionalModelSettings
from app.domain.llm.token_estimation_settings import (
    DEFAULT_TOKEN_ESTIMATION_SETTINGS,
)
from app.domain.project import Project
from app.repositories.project.conversation_long_term_memory_repository import (
    GLOBAL_MEMORY_REPOSITORY_DEFINITION,
    PROJECT_MEMORY_REPOSITORY_DEFINITION,
    ProjectConversationLongTermMemoryRepository,
)
from app.repositories.project.conversation_repository import (
    ProjectConversationRepository,
)
from app.services.project.conversation_long_term_memory import (
    ProjectConversationLongTermMemoryService,
)
from app.services.project.conversation_long_term_memory_plan import (
    build_long_term_memory_management_plan,
)
from app.services.project.conversation_request_messages import (
    build_conversation_request_messages,
)
from app.services.project.conversation_request_provenance import (
    tag_conversation_message,
)
from app.services.project.conversation_run_snapshot import ConversationRunSnapshot
from app.services.project.project_conversations import ProjectConversationService


PROJECT_ID = "00000000-0000-0000-0000-000000000992"


def test_long_term_memory_plan_counts_only_messages_after_completed_boundary(
    tmp_path,
):
    conversation, session, _repository, _global_repository, _service = (
        _create_services(tmp_path)
    )
    _user_1, assistant_1 = _append_turn(conversation, session.session_id, 1)
    _user_2, assistant_2 = _append_turn(conversation, session.session_id, 2)
    messages = conversation.list_messages(PROJECT_ID, session.session_id)

    first_plan = build_long_term_memory_management_plan(
        messages,
        session.settings,
        previous_boundary_message_id=None,
        trigger_token_threshold=1,
        token_estimation_settings=DEFAULT_TOKEN_ESTIMATION_SETTINGS,
    )
    next_plan = build_long_term_memory_management_plan(
        messages,
        session.settings,
        previous_boundary_message_id=assistant_1.message_id,
        trigger_token_threshold=1,
        token_estimation_settings=DEFAULT_TOKEN_ESTIMATION_SETTINGS,
    )

    assert first_plan is not None
    assert first_plan.snapshot_boundary_message_id == assistant_2.message_id
    assert next_plan is not None
    assert next_plan.snapshot_boundary_message_id == assistant_2.message_id
    assert assistant_1.message_id not in next_plan.newly_covered_message_ids


def test_long_term_memory_success_advances_boundary_and_does_not_repeat(
    tmp_path,
):
    conversation, session, repository, _global_repository, service = (
        _create_services(tmp_path)
    )
    _user, assistant = _append_turn(conversation, session.session_id, 1)
    runner_calls: list[ChatCompletionRequest] = []
    service.set_functional_conversation_runner(
        _successful_runner(conversation, runner_calls)
    )
    snapshot = _snapshot(conversation, session.session_id)

    asyncio.run(
        service.manage_context_if_enabled(
            PROJECT_ID,
            session.session_id,
            blocking=False,
            session_snapshot=session,
            run_snapshot=snapshot,
        )
    )
    asyncio.run(
        service.manage_context_if_enabled(
            PROJECT_ID,
            session.session_id,
            blocking=False,
            session_snapshot=session,
            run_snapshot=snapshot,
        )
    )

    state = repository.read_state(PROJECT_ID, session.session_id)
    assert state is not None
    assert state["last_completed_boundary_message_id"] == assistant.message_id
    assert len(runner_calls) == 1
    assert runner_calls[0].usage_feature_key == "project_memory_management"
    function_session = conversation.get_session(
        PROJECT_ID,
        runner_calls[0].session_id,
    )
    assert function_session is not None
    assert function_session.settings.memory_compression_enabled is False
    assert function_session.settings.project_memory_extraction_enabled is False
    assert function_session.settings.global_memory_extraction_enabled is False


def test_long_term_memory_failure_does_not_advance_boundary(tmp_path):
    conversation, session, repository, _global_repository, service = _create_services(
        tmp_path,
        settings_overrides={"failureRetryCount": 0},
    )
    _append_turn(conversation, session.session_id, 1)
    function_session_ids: list[str] = []

    async def runner(request: ChatCompletionRequest) -> None:
        assert request.session_id is not None
        function_session_ids.append(request.session_id)
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
            content="没有调用记忆工具。",
            provider_id=request.provider_id,
            model_id=request.model_id,
        )

    service.set_functional_conversation_runner(runner)
    asyncio.run(
        service.manage_context_if_enabled(
            PROJECT_ID,
            session.session_id,
            blocking=False,
            session_snapshot=session,
            run_snapshot=_snapshot(conversation, session.session_id),
        )
    )

    assert repository.read_state(PROJECT_ID, session.session_id) is None
    task = repository.read_task(PROJECT_ID, function_session_ids[0])
    assert task is not None
    assert task["status"] == "failed"
    assert task["failure"]["reason"] == "MissingMemoryManagementToolCallError"


def test_async_long_term_memory_keeps_new_messages_for_the_next_task(tmp_path):
    conversation, session, repository, _global_repository, service = (
        _create_services(tmp_path)
    )
    _user_1, assistant_1 = _append_turn(conversation, session.session_id, 1)
    calls: list[ChatCompletionRequest] = []
    successful_runner = _successful_runner(conversation, calls)
    appended_during_run = []

    async def runner(request: ChatCompletionRequest) -> None:
        if not appended_during_run:
            appended_during_run.extend(
                _append_turn(conversation, session.session_id, 2)
            )
        await successful_runner(request)

    service.set_functional_conversation_runner(runner)
    asyncio.run(
        service.manage_context_if_enabled(
            PROJECT_ID,
            session.session_id,
            blocking=False,
            session_snapshot=session,
            run_snapshot=_snapshot(conversation, session.session_id),
        )
    )

    first_state = repository.read_state(PROJECT_ID, session.session_id)
    assert first_state is not None
    assert (
        first_state["last_completed_boundary_message_id"]
        == assistant_1.message_id
    )

    asyncio.run(
        service.manage_context_if_enabled(
            PROJECT_ID,
            session.session_id,
            blocking=False,
            session_snapshot=session,
            run_snapshot=_snapshot(conversation, session.session_id),
        )
    )

    second_state = repository.read_state(PROJECT_ID, session.session_id)
    assert second_state is not None
    assert (
        second_state["last_completed_boundary_message_id"]
        == appended_during_run[-1].message_id
    )
    assert len(calls) == 2


def test_long_term_memory_plan_keeps_tool_call_and_result_together(tmp_path):
    conversation, session, _repository, _global_repository, _service = (
        _create_services(tmp_path)
    )
    conversation.append_message(
        PROJECT_ID,
        session.session_id,
        role="user",
        content="读取文件。",
    )
    tool_call = conversation.append_message(
        PROJECT_ID,
        session.session_id,
        role="assistant",
        content="",
        provider_id="codex",
        model_id="gpt-5.6-sol",
        tool_calls=(
            ChatToolCall(
                call_id="call-read",
                name="read_file",
                arguments='{"file_path":"notes.txt"}',
            ),
        ),
    )
    tool_result = conversation.append_message(
        PROJECT_ID,
        session.session_id,
        role="tool",
        content='{"result":"文件内容"}',
        name="read_file",
        tool_call_id="call-read",
    )
    messages = conversation.list_messages(PROJECT_ID, session.session_id)

    plan = build_long_term_memory_management_plan(
        messages,
        session.settings,
        previous_boundary_message_id=None,
        trigger_token_threshold=1,
        token_estimation_settings=DEFAULT_TOKEN_ESTIMATION_SETTINGS,
    )

    assert plan is not None
    assert tool_call.message_id in plan.newly_covered_message_ids
    assert tool_result.message_id in plan.newly_covered_message_ids
    assert plan.snapshot_boundary_message_id == tool_result.message_id


def test_project_and_global_memory_advance_independent_boundaries(tmp_path):
    (
        conversation,
        session,
        project_repository,
        global_repository,
        service,
    ) = _create_services(
        tmp_path,
        global_settings_overrides={"triggerTokenThreshold": 1},
    )
    _user, assistant = _append_turn(conversation, session.session_id, 1)
    runner_calls: list[ChatCompletionRequest] = []
    service.set_functional_conversation_runner(
        _successful_runner(conversation, runner_calls)
    )

    asyncio.run(
        service.manage_context_if_enabled(
            PROJECT_ID,
            session.session_id,
            blocking=False,
            session_snapshot=session,
            run_snapshot=_snapshot(conversation, session.session_id),
        )
    )

    project_state = project_repository.read_state(PROJECT_ID, session.session_id)
    global_state = global_repository.read_state(PROJECT_ID, session.session_id)
    assert project_state is not None
    assert global_state is not None
    assert project_state["last_completed_boundary_message_id"] == assistant.message_id
    assert global_state["last_completed_boundary_message_id"] == assistant.message_id
    assert {request.usage_feature_key for request in runner_calls} == {
        "project_memory_management",
        "global_memory_management",
    }


def test_project_memory_extraction_can_be_disabled_per_session(tmp_path):
    (
        conversation,
        session,
        project_repository,
        _global_repository,
        service,
    ) = _create_services(tmp_path)
    session = conversation.update_session(
        PROJECT_ID,
        session.session_id,
        settings={"project_memory_extraction_enabled": False},
        should_update_settings=True,
    )
    _append_turn(conversation, session.session_id, 1)
    runner_calls: list[ChatCompletionRequest] = []
    service.set_functional_conversation_runner(
        _successful_runner(conversation, runner_calls)
    )

    asyncio.run(
        service.manage_context_if_enabled(
            PROJECT_ID,
            session.session_id,
            blocking=False,
            session_snapshot=session,
            run_snapshot=_snapshot(conversation, session.session_id),
        )
    )

    assert project_repository.read_state(PROJECT_ID, session.session_id) is None
    assert runner_calls == []


def test_queued_checks_honor_current_disabled_settings(tmp_path):
    (
        conversation,
        stale_session_snapshot,
        project_repository,
        global_repository,
        service,
    ) = _create_services(
        tmp_path,
        global_settings_overrides={"triggerTokenThreshold": 1},
    )
    conversation.update_session(
        PROJECT_ID,
        stale_session_snapshot.session_id,
        settings={
            "project_memory_extraction_enabled": False,
            "global_memory_extraction_enabled": False,
        },
        should_update_settings=True,
    )
    _append_turn(conversation, stale_session_snapshot.session_id, 1)
    runner_calls: list[ChatCompletionRequest] = []
    service.set_functional_conversation_runner(
        _successful_runner(conversation, runner_calls)
    )

    asyncio.run(
        service.manage_context_if_enabled(
            PROJECT_ID,
            stale_session_snapshot.session_id,
            blocking=False,
            session_snapshot=stale_session_snapshot,
            run_snapshot=_snapshot(
                conversation,
                stale_session_snapshot.session_id,
            ),
        )
    )

    assert project_repository.read_state(
        PROJECT_ID,
        stale_session_snapshot.session_id,
    ) is None
    assert global_repository.read_state(
        PROJECT_ID,
        stale_session_snapshot.session_id,
    ) is None
    assert runner_calls == []


def _create_services(
    tmp_path,
    *,
    settings_overrides: dict | None = None,
    global_settings_overrides: dict | None = None,
):
    (tmp_path / "project").mkdir()
    project_repository = _FakeProjectRepository(str(tmp_path / "project"))
    conversation = ProjectConversationService(
        ProjectConversationRepository(project_repository)
    )
    session = conversation.create_session(
        PROJECT_ID,
        title="主会话",
        provider_id="codex",
        model_id="gpt-5.6-sol",
    )
    repository = ProjectConversationLongTermMemoryRepository(
        project_repository,
        PROJECT_MEMORY_REPOSITORY_DEFINITION,
    )
    global_repository = ProjectConversationLongTermMemoryRepository(
        project_repository,
        GLOBAL_MEMORY_REPOSITORY_DEFINITION,
    )
    project_settings = {
        "blockingEnabled": False,
        "failureRetryCount": 3,
        "generation": {
            "maxOutputTokens": 4096,
            "reasoning": {"mode": "off"},
            "temperature": 0.2,
            "topP": 1,
        },
        "modelKey": "",
        "modelSource": "session",
        "output": {"format": "text"},
        "prompt": DEFAULT_PROJECT_MEMORY_MANAGEMENT_PROMPT,
        "triggerTokenThreshold": 1,
        **(settings_overrides or {}),
    }
    global_settings = {
        **project_settings,
        "prompt": DEFAULT_GLOBAL_MEMORY_MANAGEMENT_PROMPT,
        "triggerTokenThreshold": 100_000,
        **(global_settings_overrides or {}),
    }
    service = ProjectConversationLongTermMemoryService(
        conversation,
        _FakeFunctionalModelSettingsService(
            {
                "projectMemoryManagement": project_settings,
                "globalMemoryManagement": global_settings,
            }
        ),
        (repository, global_repository),
        _FakeTokenEstimationSettingsService(),
    )
    return conversation, session, repository, global_repository, service


class _FakeTokenEstimationSettingsService:
    def get_settings(self):
        return DEFAULT_TOKEN_ESTIMATION_SETTINGS


def _append_turn(
    conversation: ProjectConversationService,
    session_id: str,
    number: int,
):
    user = conversation.append_message(
        PROJECT_ID,
        session_id,
        role="user",
        content=f"第 {number} 轮用户请求：" + ("甲" * 80),
    )
    assistant = conversation.append_message(
        PROJECT_ID,
        session_id,
        role="assistant",
        content=f"第 {number} 轮助手结果：" + ("乙" * 80),
        provider_id="codex",
        model_id="gpt-5.6-sol",
    )
    return user, assistant


def _snapshot(
    conversation: ProjectConversationService,
    session_id: str,
) -> ConversationRunSnapshot:
    session = conversation.get_session(PROJECT_ID, session_id)
    assert session is not None
    messages = conversation.list_messages(PROJECT_ID, session_id)
    assistant = messages[-1]
    return ConversationRunSnapshot(
        model_request=ChatCompletionRequest(
            provider_id="codex",
            model_id="gpt-5.6-sol",
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
        context_tokens=500,
    )


def _successful_runner(
    conversation: ProjectConversationService,
    calls: list[ChatCompletionRequest],
):
    async def runner(request: ChatCompletionRequest) -> None:
        assert request.session_id is not None
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
                    call_id="call-memory",
                    name="manage_memory",
                    arguments='{"action":"list","scope":"project"}',
                ),
            ),
        )
        conversation.append_message(
            PROJECT_ID,
            request.session_id,
            role="tool",
            content='{"ok":true}',
            name="manage_memory",
            tool_call_id="call-memory",
        )
        conversation.append_message(
            PROJECT_ID,
            request.session_id,
            role="assistant",
            content="长期记忆管理已完成。",
            provider_id=request.provider_id,
            model_id=request.model_id,
        )

    return runner


class _FakeFunctionalModelSettingsService:
    def __init__(self, settings: dict[str, dict]) -> None:
        self._settings = settings

    def get_profile_settings(self, profile_key: str):
        assert profile_key in self._settings
        return LlmFunctionalModelSettings(
            settings_id=profile_key,
            version=1,
            settings=self._settings[profile_key],
            created_at="now",
            updated_at="now",
        )


class _FakeProjectRepository:
    def __init__(self, root_path: str) -> None:
        now = datetime.now(UTC).isoformat()
        self.project = Project(
            project_id=PROJECT_ID,
            name="long-term-memory-test",
            root_path=root_path,
            is_default=False,
            sort_order=0,
            created_at=now,
            updated_at=now,
        )

    def get_project(self, project_id: str) -> Project | None:
        return self.project if project_id == PROJECT_ID else None
