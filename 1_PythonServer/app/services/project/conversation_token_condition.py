from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from app.domain.llm.chat import ChatMessage
from app.domain.llm.token_estimation_settings import TokenEstimationSettings
from app.services.llm.usage.estimation import estimate_message_tokens
from app.services.project.conversation_message_groups import (
    atomic_conversation_message_groups,
    complete_group_message_ids,
)


@dataclass(frozen=True, slots=True)
class HistoryTokenGroup:
    messages: tuple[ChatMessage, ...]
    message_ids: tuple[str, ...]
    token_count: int


@dataclass(frozen=True, slots=True)
class HistoryTokenCondition:
    token_count: int
    threshold: int

    @property
    def reached(self) -> bool:
        return self.token_count >= self.threshold

    def trigger_metadata(self) -> dict[str, str | int]:
        return {
            "context_token_count": self.token_count,
            "context_token_threshold": self.threshold,
            "context_token_source": "local_estimate",
            "context_token_scope": "conversation_history",
        }


@dataclass(frozen=True, slots=True)
class HistoryTokenEvaluation:
    groups: tuple[HistoryTokenGroup, ...]
    condition: HistoryTokenCondition


def evaluate_history_token_condition(
    messages: tuple[ChatMessage, ...],
    *,
    threshold: int,
    token_estimation_settings: TokenEstimationSettings,
    included_message_ids: Collection[str] | None = None,
    excluded_message_ids: Collection[str] = (),
) -> HistoryTokenEvaluation:
    """Measure eligible history, never injected prefixes or provider input totals.

    History is identified by provenance, not by role, position or prompt text.
    Each caller supplies its progress boundary; tool calls and results stay in
    the same atomic group. Selection and threshold checks reuse the same count.
    """
    included = set(included_message_ids) if included_message_ids is not None else None
    excluded = set(excluded_message_ids)
    groups: list[HistoryTokenGroup] = []
    for messages_in_group in atomic_conversation_message_groups(messages):
        message_ids = complete_group_message_ids(messages_in_group)
        if not message_ids:
            continue
        if included is not None and not included.intersection(message_ids):
            continue
        if excluded.intersection(message_ids):
            continue
        groups.append(HistoryTokenGroup(
            messages=messages_in_group,
            message_ids=message_ids,
            token_count=sum(
                estimate_message_tokens(message, token_estimation_settings)
                for message in messages_in_group
            ),
        ))
    return HistoryTokenEvaluation(
        groups=tuple(groups),
        condition=HistoryTokenCondition(
            token_count=sum(group.token_count for group in groups),
            threshold=max(1, threshold),
        ),
    )
