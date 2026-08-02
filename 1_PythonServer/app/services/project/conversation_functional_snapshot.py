from __future__ import annotations

from app.domain.llm.chat import ChatMessage
from app.domain.llm.token_estimation_settings import TokenEstimationSettings
from app.services.llm.usage.estimation import estimate_request_context_tokens
from app.services.project.conversation_run_snapshot import ConversationRunSnapshot


def legal_conversation_snapshot_messages(
    run_snapshot: ConversationRunSnapshot,
) -> tuple[ChatMessage, ...]:
    messages = run_snapshot.model_request.messages
    if run_snapshot.assistant_response.tool_calls:
        return messages
    return (*messages, run_snapshot.assistant_response)


def context_token_measurement(
    run_snapshot: ConversationRunSnapshot,
    token_estimation_settings: TokenEstimationSettings,
) -> tuple[int, str]:
    if run_snapshot.context_tokens is not None:
        return (
            max(0, run_snapshot.context_tokens),
            (
                "local_estimate"
                if run_snapshot.context_tokens_estimated
                else "provider_reported"
            ),
        )
    return (
        estimate_request_context_tokens(
            run_snapshot.model_request,
            token_estimation_settings,
        ),
        "local_estimate",
    )
