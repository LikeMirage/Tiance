from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.llm.chat import ChatMessage, ChatMessageContentPartType, ChatMessageRole
from app.domain.llm.token_estimation_settings import TokenEstimationSettings
from app.services.llm.usage.estimation import estimate_message_tokens
from app.services.project.conversation_functional_snapshot import (
    context_token_measurement,
    legal_conversation_snapshot_messages,
)
from app.services.project.conversation_message_groups import (
    atomic_conversation_message_groups,
    complete_group_message_ids,
    protocol_safe_message_ids,
)
from app.services.project.conversation_request_provenance import conversation_message_id
from app.services.project.conversation_run_snapshot import ConversationRunSnapshot


COMPACTION_SOURCE_TYPE = "conversation_context"


@dataclass(frozen=True, slots=True)
class ConversationCompactionPlan:
    active_record: dict[str, Any] | None
    source_messages: tuple[ChatMessage, ...]
    source_message_ids: tuple[str, ...]
    newly_covered_message_ids: tuple[str, ...]
    source_boundary_message_id: str
    snapshot_boundary_message_id: str
    newly_covered_token_count: int
    protected_tail_token_count: int


def build_conversation_compaction_plan(
    run_snapshot: ConversationRunSnapshot,
    records: list[dict[str, Any]],
    *,
    target_token_count: int,
    protected_token_reserve: int,
    token_estimation_settings: TokenEstimationSettings,
) -> ConversationCompactionPlan | None:
    return _build_conversation_compaction_plan(
        run_snapshot,
        records,
        target_token_count=target_token_count,
        protected_token_reserve=protected_token_reserve,
        token_estimation_settings=token_estimation_settings,
        require_context_threshold=True,
    )


def build_manual_conversation_compaction_plan(
    run_snapshot: ConversationRunSnapshot,
    records: list[dict[str, Any]],
    *,
    target_token_count: int,
    protected_token_reserve: int,
    token_estimation_settings: TokenEstimationSettings,
) -> ConversationCompactionPlan | None:
    return _build_conversation_compaction_plan(
        run_snapshot,
        records,
        target_token_count=target_token_count,
        protected_token_reserve=protected_token_reserve,
        token_estimation_settings=token_estimation_settings,
        require_context_threshold=False,
    )


def _build_conversation_compaction_plan(
    run_snapshot: ConversationRunSnapshot,
    records: list[dict[str, Any]],
    *,
    target_token_count: int,
    protected_token_reserve: int,
    token_estimation_settings: TokenEstimationSettings,
    require_context_threshold: bool,
) -> ConversationCompactionPlan | None:
    request_messages = legal_conversation_snapshot_messages(run_snapshot)
    active_record = latest_completed_compaction(records)
    ordered_active_source_ids = protocol_safe_message_ids(
        request_messages,
        compaction_source_message_ids(active_record),
    )
    active_source_ids = set(ordered_active_source_ids)
    visible_messages = tuple(
        message
        for message in request_messages
        if (
            (message_id := conversation_message_id(message)) is not None
            and message_id not in active_source_ids
        )
    )
    if not visible_messages:
        return None

    target = max(1, target_token_count)
    reserve = max(0, protected_token_reserve)
    if (
        require_context_threshold
        and _context_token_count(
            run_snapshot,
            token_estimation_settings,
        ) < target + reserve
    ):
        return None

    protected_ids: set[str] = set()
    protected_tokens = 0
    if reserve > 0:
        for group in reversed(
            atomic_conversation_message_groups(visible_messages)
        ):
            group_ids = complete_group_message_ids(group)
            if not group_ids:
                continue
            protected_ids.update(group_ids)
            protected_tokens += sum(
                estimate_message_tokens(message, token_estimation_settings)
                for message in group
            )
            if protected_tokens >= reserve:
                break

    selected_ids: list[str] = []
    selected_messages: list[ChatMessage] = []
    selected_tokens = 0
    for group in atomic_conversation_message_groups(visible_messages):
        group_ids = complete_group_message_ids(group)
        if not group_ids or protected_ids.intersection(group_ids):
            continue
        selected_ids.extend(group_ids)
        selected_messages.extend(group)
        selected_tokens += sum(
            estimate_message_tokens(message, token_estimation_settings)
            for message in group
        )
        if selected_tokens >= target:
            break
    if not selected_ids:
        return None

    newly_covered_ids = tuple(
        message_id
        for message_id in selected_ids
        if message_id not in active_source_ids
    )
    if not newly_covered_ids:
        return None

    snapshot_boundary_message_id = next(
        (
            message_id
            for message in reversed(request_messages)
            if (message_id := conversation_message_id(message)) is not None
        ),
        None,
    )
    if snapshot_boundary_message_id is None:
        return None

    source_message_ids = tuple(
        dict.fromkeys((*ordered_active_source_ids, *selected_ids))
    )
    return ConversationCompactionPlan(
        active_record=active_record,
        source_messages=tuple(selected_messages),
        source_message_ids=source_message_ids,
        newly_covered_message_ids=newly_covered_ids,
        source_boundary_message_id=newly_covered_ids[-1],
        snapshot_boundary_message_id=snapshot_boundary_message_id,
        newly_covered_token_count=selected_tokens,
        protected_tail_token_count=protected_tokens,
    )


def _context_token_count(
    run_snapshot: ConversationRunSnapshot,
    token_estimation_settings: TokenEstimationSettings,
) -> int:
    return context_token_measurement(
        run_snapshot,
        token_estimation_settings,
    )[0]


def latest_completed_compaction(
    records: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for record in reversed(records):
        if (
            record.get("status") == "completed"
            and record.get("source_type") == COMPACTION_SOURCE_TYPE
            and compaction_summary_text(record)
            and compaction_source_message_ids(record)
        ):
            return record
    return None


def compaction_source_message_ids(record: dict[str, Any] | None) -> tuple[str, ...]:
    if record is None:
        return ()
    values = record.get("source_message_ids")
    if not isinstance(values, list):
        return ()
    return tuple(
        dict.fromkeys(
            item
            for item in values
            if isinstance(item, str) and item
        )
    )


def compaction_summary_text(record: dict[str, Any] | None) -> str:
    if record is None:
        return ""
    result = record.get("result")
    if not isinstance(result, dict):
        return ""
    lines = ["历史累计摘要："]
    items = result.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, str) and content.strip():
                lines.append(f"- {content.strip()}")
    handoff = result.get("handoff")
    if isinstance(handoff, str) and handoff.strip():
        lines.extend(("", "交接总结：", handoff.strip()))
    return "\n".join(lines)
