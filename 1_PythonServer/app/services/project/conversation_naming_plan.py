from __future__ import annotations

from dataclasses import dataclass

from app.domain.llm.token_estimation_settings import TokenEstimationSettings
from app.services.project.conversation_functional_snapshot import (
    legal_conversation_snapshot_messages,
)
from app.services.project.conversation_token_condition import (
    HistoryTokenCondition,
    evaluate_history_token_condition,
)
from app.services.project.conversation_run_snapshot import ConversationRunSnapshot


@dataclass(frozen=True, slots=True)
class ConversationNamingPlan:
    snapshot_boundary_message_id: str
    selected_context_token_count: int
    token_condition: HistoryTokenCondition


def build_conversation_naming_plan(
    run_snapshot: ConversationRunSnapshot,
    *,
    trigger_token_threshold: int,
    token_estimation_settings: TokenEstimationSettings,
) -> ConversationNamingPlan | None:
    evaluation = evaluate_history_token_condition(
        legal_conversation_snapshot_messages(run_snapshot),
        threshold=trigger_token_threshold,
        token_estimation_settings=token_estimation_settings,
    )
    condition = evaluation.condition
    if not condition.reached:
        return None

    accumulated_tokens = 0
    latest_boundary_message_id: str | None = None
    for group in evaluation.groups:
        accumulated_tokens += group.token_count
        latest_boundary_message_id = group.message_ids[-1]
        if accumulated_tokens >= condition.threshold:
            break

    if latest_boundary_message_id is None:
        return None
    return ConversationNamingPlan(
        snapshot_boundary_message_id=latest_boundary_message_id,
        selected_context_token_count=accumulated_tokens,
        token_condition=condition,
    )
