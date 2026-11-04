from dataclasses import replace
import json

import pytest

from app.domain.llm.chat import (
    ChatCompletionRequest, ChatMessage, ChatMessageRole, ChatToolCall, ChatToolDefinition,
)
from app.domain.llm.token_estimation_settings import DEFAULT_TOKEN_ESTIMATION_SETTINGS
from app.domain.project.project_conversation import (
    ProjectConversationMessage, ProjectConversationSessionSettings,
)
from app.services.llm.usage.estimation import estimate_message_tokens
from app.services.project.conversation_long_term_memory_plan import build_long_term_memory_management_plan
from app.services.project.conversation_memory_compaction import build_conversation_compaction_plan
from app.services.project.conversation_naming_plan import build_conversation_naming_plan
from app.services.project.conversation_request_messages import build_conversation_request_messages
from app.services.project.conversation_request_provenance import tag_conversation_message
from app.services.project.conversation_run_snapshot import ConversationRunSnapshot


ESTIMATION = DEFAULT_TOKEN_ESTIMATION_SETTINGS


def tagged(role, content, message_id, **kwargs):
    return tag_conversation_message(ChatMessage(role=role, content=content, **kwargs), message_id)


def history():
    return (
        tagged(ChatMessageRole.USER, "请研究项目代码", "u1"),
        tagged(ChatMessageRole.ASSISTANT, "", "a1", tool_calls=(
            ChatToolCall(call_id="call1", name="read_file", arguments='{"path":"main.py"}'),
        )),
        tagged(ChatMessageRole.TOOL, "完整文件内容" * 100, "t1", tool_call_id="call1", name="read_file"),
        tagged(ChatMessageRole.ASSISTANT, "研究结果" * 30, "a2"),
    )


def snapshot(messages, *, prefix_size=0, provider_tokens=None):
    # Prefixes can use any role. Their provenance, not role or text, distinguishes
    # them from actual conversation messages.
    prefix = tuple(ChatMessage(role=role, content="注入内容" * prefix_size) for role in (
        ChatMessageRole.SYSTEM, ChatMessageRole.USER, ChatMessageRole.ASSISTANT,
    ))
    return ConversationRunSnapshot(
        model_request=ChatCompletionRequest(
            provider_id="p", model_id="m", messages=(*prefix, *messages[:-1]),
            tools=(ChatToolDefinition(
                name="read_file", description="工具定义" * prefix_size,
                parameters={"type": "object", "description": "参数规则" * prefix_size},
            ),),
        ),
        assistant_response=messages[-1], context_tokens=provider_tokens,
    )


@pytest.mark.parametrize("prefix_size", [0, 50_000])
@pytest.mark.parametrize("provider_tokens", [None, 1, 1_000_000])
def test_naming_and_compaction_only_trigger_on_history_at_exact_boundary(prefix_size, provider_tokens):
    messages = history()
    expected = sum(estimate_message_tokens(message, ESTIMATION) for message in messages)
    current = snapshot(messages, prefix_size=prefix_size, provider_tokens=provider_tokens)
    naming = build_conversation_naming_plan(
        current, trigger_token_threshold=expected, token_estimation_settings=ESTIMATION,
    )
    compaction = build_conversation_compaction_plan(
        current, [], target_token_count=expected, protected_token_reserve=0,
        token_estimation_settings=ESTIMATION,
    )
    assert naming is not None and compaction is not None
    assert naming.snapshot_boundary_message_id == "a2"
    assert compaction.newly_covered_message_ids == ("u1", "a1", "t1", "a2")
    assert naming.token_condition == compaction.token_condition
    assert naming.token_condition.trigger_metadata() == {
        "context_token_count": expected,
        "context_token_threshold": expected,
        "context_token_source": "local_estimate",
        "context_token_scope": "conversation_history",
    }
    assert build_conversation_naming_plan(
        current, trigger_token_threshold=expected + 1, token_estimation_settings=ESTIMATION,
    ) is None
    assert build_conversation_compaction_plan(
        current, [], target_token_count=expected + 1, protected_token_reserve=0,
        token_estimation_settings=ESTIMATION,
    ) is None


@pytest.mark.parametrize("old_history_still_in_snapshot", [False, True])
def test_completed_compaction_and_large_summary_do_not_retrigger(old_history_still_in_snapshot):
    messages = history()
    covered_ids = ["u1", "a1", "t1"]
    record = {
        "status": "completed", "source_type": "conversation_context",
        "compression_id": "cmp1", "source_message_ids": covered_ids,
        "result": {"items": [{"content": "累计摘要" * 50_000}]},
    }
    remaining_tokens = estimate_message_tokens(messages[-1], ESTIMATION)
    current = snapshot(
        messages if old_history_still_in_snapshot else messages[-1:],
        prefix_size=50_000, provider_tokens=1_000_000,
    )
    assert build_conversation_compaction_plan(
        current, [record], target_token_count=remaining_tokens + 1,
        protected_token_reserve=0, token_estimation_settings=ESTIMATION,
    ) is None
    plan = build_conversation_compaction_plan(
        current, [record], target_token_count=remaining_tokens,
        protected_token_reserve=0, token_estimation_settings=ESTIMATION,
    )
    assert plan is not None
    assert plan.token_condition.token_count == remaining_tokens
    assert plan.newly_covered_message_ids == ("a2",)
    assert plan.source_message_ids == (*covered_ids, "a2")


def persisted(message):
    return ProjectConversationMessage(
        message_id=message.internal_metadata["conversation_message_id"],
        session_id="session", role=message.role.value,
        content=(json.dumps({"result": message.content}, ensure_ascii=False)
                 if message.role == ChatMessageRole.TOOL else message.content),
        thinking_content="", usage=None, provider_id="p", model_id="m", status="done",
        created_at="2026-11-04T00:00:00Z", updated_at="2026-11-04T00:00:00Z",
        tool_calls=message.tool_calls, tool_call_id=message.tool_call_id, name=message.name,
    )


@pytest.mark.parametrize("prefix_size", [0, 50_000])
def test_memory_scopes_keep_independent_progress_and_ignore_system_prefix(prefix_size):
    messages = tuple(persisted(message) for message in history())
    settings = ProjectConversationSessionSettings(system_prompt="系统前置" * prefix_size)
    request_history = build_conversation_request_messages(
        messages, None, replace(settings, system_prompt=""),
    )
    expected_pending = estimate_message_tokens(request_history[-1], ESTIMATION)

    def plan(boundary, threshold):
        return build_long_term_memory_management_plan(
            messages, settings, previous_boundary_message_id=boundary,
            trigger_token_threshold=threshold, token_estimation_settings=ESTIMATION,
        )

    # Project memory has processed through the tool result; global memory has not.
    assert plan("t1", expected_pending + 1) is None
    global_plan = plan(None, expected_pending + 1)
    project_plan = plan("t1", expected_pending)
    assert global_plan is not None and project_plan is not None
    assert global_plan.newly_covered_message_ids == ("u1", "a1", "t1", "a2")
    assert project_plan.newly_covered_message_ids == ("a2",)
    assert project_plan.token_condition.token_count == expected_pending
    assert plan("a2", 1) is None
    assert plan("missing-boundary", 1) is None


def test_compaction_reserve_and_selection_use_same_history_count():
    messages = history()
    reserve = estimate_message_tokens(messages[-1], ESTIMATION)
    target = sum(estimate_message_tokens(message, ESTIMATION) for message in messages[:-1])
    current = snapshot(messages, prefix_size=50_000, provider_tokens=1)
    plan = build_conversation_compaction_plan(
        current, [], target_token_count=target, protected_token_reserve=reserve,
        token_estimation_settings=ESTIMATION,
    )
    assert plan is not None
    assert plan.newly_covered_message_ids == ("u1", "a1", "t1")
    assert plan.protected_tail_token_count == reserve
    assert plan.token_condition.token_count == target + reserve
    assert build_conversation_compaction_plan(
        current, [], target_token_count=target, protected_token_reserve=reserve + 1,
        token_estimation_settings=ESTIMATION,
    ) is None
