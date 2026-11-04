from __future__ import annotations

from dataclasses import dataclass

from app.domain.llm.token_estimation_settings import TokenEstimationSettings
from app.domain.project.project_conversation import (
    ProjectConversationMessage,
    ProjectConversationSessionSettings,
)
from app.services.project.conversation_token_condition import (
    HistoryTokenCondition,
    evaluate_history_token_condition,
)
from app.services.project.conversation_request_messages import (
    build_conversation_request_messages,
)


@dataclass(frozen=True, slots=True)
class LongTermMemoryManagementPlan:
    token_condition: HistoryTokenCondition
    newly_covered_message_ids: tuple[str, ...]
    newly_covered_token_count: int
    previous_boundary_message_id: str | None
    snapshot_boundary_message_id: str


def build_long_term_memory_management_plan(
    messages: tuple[ProjectConversationMessage, ...],
    settings: ProjectConversationSessionSettings,
    *,
    previous_boundary_message_id: str | None,
    trigger_token_threshold: int,
    token_estimation_settings: TokenEstimationSettings,
) -> LongTermMemoryManagementPlan | None:
    raw_message_ids = [message.message_id for message in messages]
    if previous_boundary_message_id is None:
        pending_raw_ids = set(raw_message_ids)
    else:
        try:
            boundary_index = raw_message_ids.index(previous_boundary_message_id)
        except ValueError:
            return None
        pending_raw_ids = set(raw_message_ids[boundary_index + 1 :])
    if not pending_raw_ids:
        return None

    request_messages = build_conversation_request_messages(
        messages,
        None,
        settings,
    )
    evaluation = evaluate_history_token_condition(
        request_messages,
        threshold=trigger_token_threshold,
        token_estimation_settings=token_estimation_settings,
        included_message_ids=pending_raw_ids,
    )
    condition = evaluation.condition
    if not condition.reached:
        return None
    selected_ids = [
        message_id
        for group in evaluation.groups
        for message_id in group.message_ids
    ]
    return LongTermMemoryManagementPlan(
        token_condition=condition,
        newly_covered_message_ids=tuple(dict.fromkeys(selected_ids)),
        newly_covered_token_count=condition.token_count,
        previous_boundary_message_id=previous_boundary_message_id,
        snapshot_boundary_message_id=selected_ids[-1],
    )
