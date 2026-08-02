from __future__ import annotations

from app.domain.llm.chat import ChatMessage, ChatMessageRole
from app.services.project.conversation_request_provenance import (
    conversation_message_id,
)


def atomic_conversation_message_groups(
    messages: tuple[ChatMessage, ...],
) -> tuple[tuple[ChatMessage, ...], ...]:
    groups: list[tuple[ChatMessage, ...]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        group = [message]
        index += 1
        if message.role == ChatMessageRole.ASSISTANT and message.tool_calls:
            while (
                index < len(messages)
                and messages[index].role == ChatMessageRole.TOOL
            ):
                group.append(messages[index])
                index += 1
        groups.append(tuple(group))
    return tuple(groups)


def complete_group_message_ids(
    group: tuple[ChatMessage, ...],
) -> tuple[str, ...]:
    message_ids = tuple(
        message_id
        for message in group
        if (message_id := conversation_message_id(message)) is not None
    )
    return message_ids if len(message_ids) == len(group) else ()


def protocol_safe_message_ids(
    messages: tuple[ChatMessage, ...],
    message_ids: tuple[str, ...],
) -> tuple[str, ...]:
    safe_ids = set(message_ids)
    for group in atomic_conversation_message_groups(messages):
        first = group[0]
        if first.role != ChatMessageRole.ASSISTANT or not first.tool_calls:
            continue
        group_ids = complete_group_message_ids(group)
        known_group_ids = {
            message_id
            for message in group
            if (message_id := conversation_message_id(message)) is not None
        }
        covered_group_ids = safe_ids.intersection(known_group_ids)
        if covered_group_ids and (
            not group_ids
            or covered_group_ids != set(group_ids)
        ):
            safe_ids.difference_update(known_group_ids)
    return tuple(message_id for message_id in message_ids if message_id in safe_ids)
