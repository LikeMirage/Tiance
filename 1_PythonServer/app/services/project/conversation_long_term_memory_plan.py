from __future__ import annotations

from dataclasses import dataclass

from app.domain.llm.token_estimation_settings import TokenEstimationSettings
from app.domain.project.project_conversation import (
    ProjectConversationMessage,
    ProjectConversationSessionSettings,
)
from app.services.llm.usage.estimation import estimate_message_tokens
from app.services.project.conversation_message_groups import (
    atomic_conversation_message_groups,
    complete_group_message_ids,
)
from app.services.project.conversation_request_messages import (
    build_conversation_request_messages,
)


@dataclass(frozen=True, slots=True)
class LongTermMemoryManagementPlan:
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
    selected_ids: list[str] = []
    selected_tokens = 0
    for group in atomic_conversation_message_groups(request_messages):
        group_ids = complete_group_message_ids(group)
        if not group_ids or not pending_raw_ids.intersection(group_ids):
            continue
        selected_ids.extend(group_ids)
        selected_tokens += sum(
            estimate_message_tokens(message, token_estimation_settings)
            for message in group
        )

    if (
        not selected_ids
        or selected_tokens < max(1, trigger_token_threshold)
    ):
        return None
    return LongTermMemoryManagementPlan(
        newly_covered_message_ids=tuple(dict.fromkeys(selected_ids)),
        newly_covered_token_count=selected_tokens,
        previous_boundary_message_id=previous_boundary_message_id,
        snapshot_boundary_message_id=selected_ids[-1],
    )
