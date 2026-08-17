from __future__ import annotations

from dataclasses import replace

from app.domain.llm.chat import ChatCompletionRequest, ChatMessage, ChatMessageRole
from app.domain.project.project_conversation import ProjectConversationMessage
from app.services.project.conversation_naming_messages import (
    build_naming_input,
    naming_usage_message_id,
)
from app.services.project.conversation_functional_settings import (
    generation_from_settings,
    output_from_settings,
)
from app.services.project.conversation_request_provenance import conversation_message_id
from app.services.project.conversation_run_snapshot import ConversationRunSnapshot


class SessionNamingSourceBoundaryError(ValueError):
    pass


def build_dedicated_naming_request(
    *,
    provider_id: str,
    model_id: str,
    project_id: str,
    session_id: str,
    prompt: str,
    reference_messages: tuple[ProjectConversationMessage, ...],
    settings: dict[str, object],
) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        provider_id=provider_id,
        model_id=model_id,
        project_id=project_id,
        session_id=session_id,
        messages=(
            ChatMessage(role=ChatMessageRole.SYSTEM, content=prompt),
            ChatMessage(
                role=ChatMessageRole.USER,
                content=build_naming_input(reference_messages),
            ),
        ),
        generation=generation_from_settings(settings.get("generation")),
        output=output_from_settings(settings.get("output")),
        record_usage=True,
        usage_message_id=naming_usage_message_id(project_id, session_id),
        usage_feature_key="conversation_naming",
    )


def build_session_naming_request(
    *,
    run_snapshot: ConversationRunSnapshot,
    project_id: str,
    session_id: str,
    prompt: str,
    reference_messages: tuple[ProjectConversationMessage, ...],
    settings: dict[str, object],
) -> ChatCompletionRequest:
    boundary_message_id = _reference_boundary_message_id(reference_messages)
    request_messages = (
        *run_snapshot.model_request.messages,
        run_snapshot.assistant_response,
    )
    cutoff = _unique_message_position(request_messages, boundary_message_id) + 1
    configured_generation = generation_from_settings(settings.get("generation"))
    generation = replace(
        configured_generation,
        reasoning=run_snapshot.model_request.generation.reasoning,
    )
    return replace(
        run_snapshot.model_request,
        project_id=project_id,
        session_id=session_id,
        messages=(
            *request_messages[:cutoff],
            ChatMessage(role=ChatMessageRole.USER, content=prompt),
        ),
        generation=generation,
        output=output_from_settings(settings.get("output")),
        record_usage=True,
        usage_message_id=naming_usage_message_id(project_id, session_id),
        usage_feature_key="conversation_naming",
    )


def _reference_boundary_message_id(
    messages: tuple[ProjectConversationMessage, ...],
) -> str:
    if not messages or messages[-1].role != "assistant":
        raise SessionNamingSourceBoundaryError(
            "会话命名参考范围没有以完整 AI 回复结束。",
        )
    message_id = messages[-1].message_id.strip()
    if not message_id:
        raise SessionNamingSourceBoundaryError(
            "会话命名参考范围缺少边界消息 ID。",
        )
    return message_id


def _unique_message_position(
    messages: tuple[ChatMessage, ...],
    expected_message_id: str,
) -> int:
    positions = [
        index
        for index, message in enumerate(messages)
        if conversation_message_id(message) == expected_message_id
    ]
    if len(positions) != 1:
        state = "缺少" if not positions else "重复"
        raise SessionNamingSourceBoundaryError(
            f"无法在本轮真实模型请求中唯一定位命名范围（{state}边界消息）。",
        )
    return positions[0]
