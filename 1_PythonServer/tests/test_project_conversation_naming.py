import asyncio
from dataclasses import replace
from datetime import UTC, datetime
import json

import pytest

from app.core.errors import ConflictError
from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatMessage,
    ChatMessageRole,
    ChatToolCall,
)
from app.domain.llm.functional_model_defaults import DEFAULT_NAMING_PROMPT
from app.domain.llm.functional_model_settings import LlmFunctionalModelSettings
from app.domain.llm.generation_params import LlmGenerationParams
from app.domain.llm.token_estimation_settings import (
    DEFAULT_TOKEN_ESTIMATION_SETTINGS,
    TokenEstimationSettings,
)
from app.domain.project import Project
from app.domain.project.project_conversation import ProjectConversationSession
from app.repositories.project.conversation_naming_repository import (
    ProjectConversationNamingRepository,
)
from app.repositories.project.conversation_repository import (
    ProjectConversationRepository,
)
from app.services.project.conversation_naming import ProjectConversationNamingService
from app.services.project.conversation_naming_plan import (
    build_conversation_naming_plan,
)
from app.services.project.conversation_request_provenance import (
    tag_conversation_message,
)
from app.services.project.conversation_run_snapshot import ConversationRunSnapshot


def test_naming_waits_until_context_reaches_token_threshold():
    repository = _FakeNamingRepository()
    service = _service(repository=repository)

    result = asyncio.run(
        service.name_session_if_needed(
            "project-1",
            "session-1",
            run_snapshot=_snapshot(context_tokens=19_999),
        )
    )

    assert result is None
    assert repository.create_calls == []


def test_naming_creates_functional_session_at_default_20k_threshold():
    repository = _FakeNamingRepository()
    service = _service(repository=repository)
    snapshot = _snapshot(context_tokens=20_000)

    result = asyncio.run(
        service.name_session_if_needed(
            "project-1",
            "session-1",
            run_snapshot=snapshot,
        )
    )

    assert result is repository.creation
    call = repository.create_calls[0]
    assert call["snapshot_boundary_message_id"] == "assistant-2"
    assert call["target_provider_id"] == "codex"
    assert call["target_model_id"] == "gpt-5.6-sol"
    assert call["mode"] == "session"
    assert call["trigger"]["trigger_token_threshold"] == 20_000
    assert call["trigger"]["context_token_source"] == "provider_reported"
    assert "只能调用一次 manage_ai_conversations" in call["task_prompt"]
    assert "action 必须使用 name_parent_session" in call["task_prompt"]
    assert "session-1" not in call["task_prompt"]


def test_naming_uses_configured_prompt_without_dynamic_session_identity():
    repository = _FakeNamingRepository()
    configured_prompt = "用户在设定集中保存的完整命名规则。"
    service = _service(
        repository=repository,
        settings={
            **_default_settings(),
            "prompt": configured_prompt,
        },
    )

    asyncio.run(
        service.name_session_if_needed(
            "project-1",
            "session-1",
            run_snapshot=_snapshot(context_tokens=20_000),
        )
    )

    assert repository.create_calls[0]["task_prompt"] == configured_prompt


def test_naming_uses_local_context_estimate_when_provider_usage_is_missing():
    repository = _FakeNamingRepository()
    service = _service(
        repository=repository,
        settings={
            **_default_settings(),
            "triggerTokenThreshold": 1,
        },
    )

    asyncio.run(
        service.name_session_if_needed(
            "project-1",
            "session-1",
            run_snapshot=_snapshot(context_tokens=None),
        )
    )

    assert repository.create_calls[0]["trigger"]["context_token_source"] \
        == "local_estimate"


def test_naming_boundary_rounds_forward_across_tool_call_and_results():
    messages = (
        _tag(ChatMessage(role=ChatMessageRole.USER, content="开始"), "user-1"),
        _tag(
            ChatMessage(
                role=ChatMessageRole.ASSISTANT,
                content="",
                tool_calls=(
                    ChatToolCall(
                        call_id="call-1",
                        name="read_file",
                        arguments='{"file_path":"notes.txt"}',
                    ),
                ),
            ),
            "assistant-tool",
        ),
        _tag(
            ChatMessage(
                role=ChatMessageRole.TOOL,
                content="x" * 400,
                name="read_file",
                tool_call_id="call-1",
            ),
            "tool-result",
        ),
    )
    snapshot = ConversationRunSnapshot(
        model_request=ChatCompletionRequest(
            provider_id="codex",
            model_id="gpt-5.6-sol",
            messages=messages,
        ),
        assistant_response=_tag(
            ChatMessage(role=ChatMessageRole.ASSISTANT, content="已读取"),
            "assistant-final",
        ),
        context_tokens=500,
    )

    plan = build_conversation_naming_plan(
        snapshot,
        trigger_token_threshold=20,
        token_estimation_settings=DEFAULT_TOKEN_ESTIMATION_SETTINGS,
    )

    assert plan is not None
    assert plan.snapshot_boundary_message_id == "tool-result"


def test_naming_local_estimate_uses_configured_ratios_but_provider_usage_wins():
    messages = (
        _tag(
            ChatMessage(role=ChatMessageRole.USER, content="a" * 80),
            "user-1",
        ),
    )
    request = ChatCompletionRequest(
        provider_id="codex",
        model_id="gpt-5.6-sol",
        messages=messages,
    )
    compact_estimate_settings = TokenEstimationSettings(
        ascii_chars_per_token=16,
        other_chars_per_token=16,
        message_overhead_tokens=0,
        image_placeholder_tokens=0,
    )
    local_plan = build_conversation_naming_plan(
        ConversationRunSnapshot(
            model_request=request,
            assistant_response=_tag(
                ChatMessage(role=ChatMessageRole.ASSISTANT, content="done"),
                "assistant-1",
            ),
            context_tokens=None,
        ),
        trigger_token_threshold=40,
        token_estimation_settings=compact_estimate_settings,
    )
    dense_estimate_plan = build_conversation_naming_plan(
        ConversationRunSnapshot(
            model_request=request,
            assistant_response=_tag(
                ChatMessage(role=ChatMessageRole.ASSISTANT, content="done"),
                "assistant-1",
            ),
            context_tokens=None,
        ),
        trigger_token_threshold=40,
        token_estimation_settings=TokenEstimationSettings(
            ascii_chars_per_token=1,
            other_chars_per_token=1,
            message_overhead_tokens=0,
            image_placeholder_tokens=0,
        ),
    )
    provider_plan = build_conversation_naming_plan(
        ConversationRunSnapshot(
            model_request=request,
            assistant_response=_tag(
                ChatMessage(role=ChatMessageRole.ASSISTANT, content="done"),
                "assistant-1",
            ),
            context_tokens=40,
        ),
        trigger_token_threshold=40,
        token_estimation_settings=compact_estimate_settings,
    )

    assert local_plan is None
    assert dense_estimate_plan is not None
    assert dense_estimate_plan.trigger_context_token_source == "local_estimate"
    assert provider_plan is not None
    assert provider_plan.trigger_context_token_count == 40
    assert provider_plan.trigger_context_token_source == "provider_reported"


def test_dedicated_naming_uses_configured_model_and_task_system_prompt():
    repository = _FakeNamingRepository()
    service = _service(
        repository=repository,
        settings={
            **_default_settings(),
            "modelSource": "dedicated",
            "modelKey": "deepseek:deepseek-v4-flash",
        },
    )

    asyncio.run(
        service.name_session_if_needed(
            "project-1",
            "session-1",
            run_snapshot=_snapshot(context_tokens=20_000),
        )
    )

    call = repository.create_calls[0]
    assert call["target_provider_id"] == "deepseek"
    assert call["target_model_id"] == "deepseek-v4-flash"
    assert call["mode"] == "dedicated"
    assert call["target_settings"].system_prompt == call["task_prompt"]


def test_naming_skips_manual_or_already_named_sessions():
    repository = _FakeNamingRepository()
    for session in (
        replace(_session(), title="已有标题"),
        replace(_session(), manual_title=True),
    ):
        service = _service(repository=repository, session=session)
        result = asyncio.run(
            service.name_session_if_needed(
                "project-1",
                "session-1",
                run_snapshot=_snapshot(context_tokens=20_000),
            )
        )
        assert result is None
    assert repository.create_calls == []


def test_title_submission_and_run_settlement_delegate_to_repository():
    repository = _FakeNamingRepository()
    service = _service(repository=repository)

    applied = service.name_parent_session(
        "project-1",
        "function-1",
        title="自动命名测试",
    )
    settled = service.settle_automatic_naming(
        "project-1",
        "function-1",
        outcome="done",
    )

    assert applied["status"] == "completed"
    assert settled["status"] == "failed"
    assert repository.apply_calls[0]["title"] == "自动命名测试"
    assert repository.settle_calls[0]["outcome"] == "done"


def test_naming_repository_copies_prefix_and_atomically_applies_title(tmp_path):
    project_repository = _FakeProjectRepository(str(tmp_path))
    conversations = ProjectConversationRepository(project_repository)
    naming = ProjectConversationNamingRepository(project_repository)
    source = conversations.create_session(
        _PROJECT_ID,
        title="新对话",
        provider_id="codex",
        model_id="gpt-5.6-sol",
        reasoning_mode="high",
        settings={"system_prompt": "稳定提示词"},
    )
    user = conversations.append_message(
        _PROJECT_ID,
        source.session_id,
        role="user",
        content="设计 Token 统计。",
        status="done",
    )
    assistant = conversations.append_message(
        _PROJECT_ID,
        source.session_id,
        role="assistant",
        content="先统一统计口径。",
        provider_id="codex",
        model_id="gpt-5.6-sol",
        status="done",
    )

    created = naming.create_task(
        _PROJECT_ID,
        source.session_id,
        snapshot_boundary_message_id=assistant.message_id,
        target_provider_id="codex",
        target_model_id="gpt-5.6-sol",
        target_reasoning_mode="high",
        target_settings=source.settings,
        mode="session",
        trigger={"trigger_token_threshold": 20_000},
        task_prompt="只执行自动命名。",
    )

    assert created is not None
    copied = conversations.list_messages(
        _PROJECT_ID,
        created.session.session_id,
    )
    assert [message.content for message in copied] == [
        user.content,
        assistant.content,
    ]
    assert [message.origin_message_id for message in copied] == [
        user.message_id,
        assistant.message_id,
    ]
    assert created.branch.parent_session_id == source.session_id
    assert created.branch.relation_kind == "functional"
    assert created.branch.function_type == "automatic_naming"
    assert created.branch.created_by == "system"
    duplicate = naming.create_task(
        _PROJECT_ID,
        source.session_id,
        snapshot_boundary_message_id=assistant.message_id,
        target_provider_id="codex",
        target_model_id="gpt-5.6-sol",
        target_reasoning_mode="high",
        target_settings=source.settings,
        mode="session",
        trigger={"trigger_token_threshold": 20_000},
        task_prompt="只执行自动命名。",
    )
    assert duplicate is None

    result = naming.apply_title(
        _PROJECT_ID,
        created.session.session_id,
        title="Token 统计设计",
    )
    updated_source = conversations.get_session(_PROJECT_ID, source.session_id)

    assert result["status"] == "completed"
    assert updated_source is not None
    assert updated_source.title == "Token 统计设计"
    assert updated_source.manual_title is False


def test_naming_repository_rejects_non_naming_session(tmp_path):
    project_repository = _FakeProjectRepository(str(tmp_path))
    conversations = ProjectConversationRepository(project_repository)
    naming = ProjectConversationNamingRepository(project_repository)
    ordinary = conversations.create_session(
        _PROJECT_ID,
        title="新对话",
        provider_id="codex",
        model_id="gpt-5.6-sol",
        reasoning_mode=None,
    )

    with pytest.raises(ConflictError, match="不是自动命名任务会话"):
        naming.apply_title(
            _PROJECT_ID,
            ordinary.session_id,
            title="不应写入",
        )


def test_naming_repository_rejects_task_and_branch_parent_mismatch(tmp_path):
    project_repository = _FakeProjectRepository(str(tmp_path))
    conversations = ProjectConversationRepository(project_repository)
    naming = ProjectConversationNamingRepository(project_repository)
    source = conversations.create_session(
        _PROJECT_ID,
        title="新对话",
        provider_id="codex",
        model_id="gpt-5.6-sol",
        reasoning_mode=None,
    )
    other = conversations.create_session(
        _PROJECT_ID,
        title="新对话",
        provider_id="codex",
        model_id="gpt-5.6-sol",
        reasoning_mode=None,
    )
    user = conversations.append_message(
        _PROJECT_ID,
        source.session_id,
        role="user",
        content="测试关系校验。",
        status="done",
    )
    created = naming.create_task(
        _PROJECT_ID,
        source.session_id,
        snapshot_boundary_message_id=user.message_id,
        target_provider_id="codex",
        target_model_id="gpt-5.6-sol",
        target_reasoning_mode=None,
        target_settings=source.settings,
        mode="session",
        trigger={"trigger_token_threshold": 20_000},
        task_prompt="只执行自动命名。",
    )
    assert created is not None
    task_path = (
        tmp_path
        / ".Tiance"
        / "conversations"
        / "sessions"
        / created.session.session_id
        / "automatic_naming_task.json"
    )
    task = json.loads(task_path.read_text(encoding="utf-8"))
    task["source_session_id"] = other.session_id
    task_path.write_text(
        json.dumps(task, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with pytest.raises(ConflictError, match="关系不一致"):
        naming.apply_title(
            _PROJECT_ID,
            created.session.session_id,
            title="不应写入",
        )

    unchanged = conversations.get_session(_PROJECT_ID, source.session_id)
    assert unchanged is not None
    assert unchanged.title == "新对话"


class _FakeConversationService:
    def __init__(self, session: ProjectConversationSession) -> None:
        self.session = session

    def get_session(self, project_id: str, session_id: str):
        return self.session if session_id == self.session.session_id else None


class _FakeFunctionalModelSettingsService:
    def __init__(self, settings: dict) -> None:
        self.settings = settings

    def get_profile_settings(self, profile_key: str):
        assert profile_key == "naming"
        return LlmFunctionalModelSettings(
            settings_id=profile_key,
            version=25,
            settings=self.settings,
            created_at="now",
            updated_at="now",
        )


class _FakeNamingRepository:
    def __init__(self) -> None:
        self.creation = object()
        self.create_calls: list[dict] = []
        self.apply_calls: list[dict] = []
        self.settle_calls: list[dict] = []

    def create_task(self, project_id: str, source_session_id: str, **kwargs):
        self.create_calls.append(
            {
                "project_id": project_id,
                "source_session_id": source_session_id,
                **kwargs,
            }
        )
        return self.creation

    def apply_title(self, project_id: str, function_session_id: str, **kwargs):
        self.apply_calls.append(
            {
                "project_id": project_id,
                "function_session_id": function_session_id,
                **kwargs,
            }
        )
        return {
            "applied": True,
            "source_session_id": "session-1",
            "title": kwargs["title"],
            "status": "completed",
        }

    def settle_task(self, project_id: str, function_session_id: str, **kwargs):
        self.settle_calls.append(
            {
                "project_id": project_id,
                "function_session_id": function_session_id,
                **kwargs,
            }
        )
        return {"task_id": "task-1", "status": "failed"}


def _service(
    *,
    repository: _FakeNamingRepository,
    session: ProjectConversationSession | None = None,
    settings: dict | None = None,
) -> ProjectConversationNamingService:
    return ProjectConversationNamingService(
        _FakeConversationService(session or _session()),
        _FakeFunctionalModelSettingsService(settings or _default_settings()),
        repository,
        _FakeTokenEstimationSettingsService(),
    )


class _FakeTokenEstimationSettingsService:
    def get_settings(self):
        return DEFAULT_TOKEN_ESTIMATION_SETTINGS


def _session() -> ProjectConversationSession:
    return ProjectConversationSession(
        session_id="session-1",
        sequence_number=1,
        title="新对话",
        provider_id="codex",
        model_id="gpt-5.6-sol",
        created_at="now",
        updated_at="now",
        message_count=4,
    )


def _default_settings() -> dict:
    return {
        "modelKey": "",
        "modelSource": "session",
        "prompt": DEFAULT_NAMING_PROMPT,
        "triggerTokenThreshold": 20_000,
        "generation": {
            "temperature": 0.2,
            "maxOutputTokens": 256,
            "reasoning": {"mode": "off"},
        },
        "output": {"format": "text"},
    }


def _snapshot(*, context_tokens: int | None) -> ConversationRunSnapshot:
    messages = (
        ChatMessage(role=ChatMessageRole.SYSTEM, content="系统提示词"),
        _tag(
            ChatMessage(role=ChatMessageRole.USER, content="帮我设计用量统计。"),
            "user-1",
        ),
        _tag(
            ChatMessage(role=ChatMessageRole.ASSISTANT, content="先统一统计口径。"),
            "assistant-1",
        ),
        _tag(
            ChatMessage(role=ChatMessageRole.USER, content="继续。"),
            "user-2",
        ),
    )
    return ConversationRunSnapshot(
        model_request=ChatCompletionRequest(
            provider_id="codex",
            model_id="gpt-5.6-sol",
            messages=messages,
            generation=LlmGenerationParams(
                max_output_tokens=1024,
                temperature=0.4,
                top_p=0.8,
            ),
        ),
        assistant_response=_tag(
            ChatMessage(role=ChatMessageRole.ASSISTANT, content="完成具体设计。"),
            "assistant-2",
        ),
        context_tokens=context_tokens,
        context_tokens_estimated=False,
    )


def _tag(message: ChatMessage, message_id: str) -> ChatMessage:
    return tag_conversation_message(message, message_id)


_PROJECT_ID = "00000000-0000-0000-0000-000000000991"


class _FakeProjectRepository:
    def __init__(self, root_path: str) -> None:
        now = datetime.now(UTC).isoformat()
        self.project = Project(
            project_id=_PROJECT_ID,
            name="automatic-naming-test",
            root_path=root_path,
            is_default=False,
            sort_order=0,
            created_at=now,
            updated_at=now,
        )

    def get_project(self, project_id: str) -> Project | None:
        return self.project if project_id == _PROJECT_ID else None
