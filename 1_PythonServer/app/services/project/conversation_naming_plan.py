from __future__ import annotations

from dataclasses import dataclass

from app.domain.llm.token_estimation_settings import TokenEstimationSettings
from app.services.llm.usage.estimation import estimate_message_tokens
from app.services.project.conversation_functional_snapshot import (
    context_token_measurement,
    legal_conversation_snapshot_messages,
)
from app.services.project.conversation_message_groups import (
    atomic_conversation_message_groups,
    complete_group_message_ids,
)
from app.services.project.conversation_run_snapshot import ConversationRunSnapshot


@dataclass(frozen=True, slots=True)
class ConversationNamingPlan:
    snapshot_boundary_message_id: str
    selected_context_token_count: int
    trigger_context_token_count: int
    trigger_context_token_source: str


def build_conversation_naming_plan(
    run_snapshot: ConversationRunSnapshot,
    *,
    trigger_token_threshold: int,
    token_estimation_settings: TokenEstimationSettings,
) -> ConversationNamingPlan | None:
    threshold = max(1, trigger_token_threshold)
    trigger_tokens, trigger_source = context_token_measurement(
        run_snapshot,
        token_estimation_settings,
    )
    if trigger_tokens < threshold:
        return None

    accumulated_tokens = 0
    latest_boundary_message_id: str | None = None
    for group in atomic_conversation_message_groups(
        legal_conversation_snapshot_messages(run_snapshot)
    ):
        accumulated_tokens += sum(
            estimate_message_tokens(message, token_estimation_settings)
            for message in group
        )
        group_ids = complete_group_message_ids(group)
        if group_ids:
            latest_boundary_message_id = group_ids[-1]
        if (
            accumulated_tokens >= threshold
            and latest_boundary_message_id is not None
        ):
            break

    if latest_boundary_message_id is None:
        return None
    return ConversationNamingPlan(
        snapshot_boundary_message_id=latest_boundary_message_id,
        selected_context_token_count=accumulated_tokens,
        trigger_context_token_count=trigger_tokens,
        trigger_context_token_source=trigger_source,
    )
