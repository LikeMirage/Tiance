from __future__ import annotations

import asyncio
import logging
from time import monotonic

from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatMessage,
    ChatMessageContentPart,
    ChatMessageRole,
    ChatUsage,
)
from app.domain.project.project_conversation import ProjectConversationMessage
from app.services.llm.token_estimation_settings import TokenEstimationSettingsService
from app.services.llm.usage.estimation import complete_usage_with_estimates
from app.services.project.conversation_stream_persistence import ConversationStreamPersistence
from app.services.project.conversation_stream_run_events import conversation_run_settled_payload
from app.services.project.conversation_stream_usage import usage_to_payload
from app.services.tools.tool_cancellation import ToolCancellationScope


logger = logging.getLogger(__name__)


class ConversationStreamSettlement:
    """Persist and account for every terminal conversation-run state."""

    def __init__(
        self,
        *,
        persistence: ConversationStreamPersistence,
        token_estimation_settings_service: TokenEstimationSettingsService,
    ) -> None:
        self._persistence = persistence
        self._token_estimation_settings_service = token_estimation_settings_service

    async def settle_interrupted(
        self,
        request: ChatCompletionRequest,
        user_message: ProjectConversationMessage | None,
        *,
        run_started_at: float,
        assistant_message: ProjectConversationMessage | None,
        last_model_request: ChatCompletionRequest | None,
        current_round_already_persisted: bool,
        persisted_tool_call_message_id: str | None,
        cancelled_tool_scopes: dict[str, ToolCancellationScope],
        usage: ChatUsage | None,
        answer_parts: list[str],
        thinking_parts: list[str],
        content_parts: list[ChatMessageContentPart],
        usage_payload: dict[str, object] | None,
        context_tokens: int | None,
        context_tokens_estimated: bool,
    ) -> tuple[
        ProjectConversationMessage | None,
        dict[str, object | None] | None,
    ]:
        completed_usage = usage
        if assistant_message is None:
            (
                completed_usage,
                usage_payload,
                context_tokens,
                context_tokens_estimated,
            ) = self._complete_interrupted_round_usage(
                model_request=last_model_request,
                round_already_persisted=current_round_already_persisted,
                provider_usage=usage,
                answer_parts=answer_parts,
                thinking_parts=thinking_parts,
                content_parts=content_parts,
                current_usage_payload=usage_payload,
                current_context_tokens=context_tokens,
                current_context_tokens_estimated=context_tokens_estimated,
            )
            interrupted_tool_round_completed = False
            if current_round_already_persisted and persisted_tool_call_message_id:
                try:
                    interrupted_tool_round_completed = await asyncio.to_thread(
                        self._persistence.complete_interrupted_tool_round,
                        request,
                        persisted_tool_call_message_id,
                        cancellation_scopes=cancelled_tool_scopes,
                    )
                except Exception:
                    logger.exception("Failed to complete an interrupted tool-call round.")
            assistant_message = await asyncio.to_thread(
                self._persistence.append_interrupted_assistant_message,
                request,
                answer_parts=answer_parts,
                thinking_parts=thinking_parts,
                content_parts=content_parts,
                usage_payload=usage_payload,
                context_tokens=context_tokens,
                context_tokens_estimated=context_tokens_estimated,
                persisted_tool_call_message_id=(
                    persisted_tool_call_message_id
                    if current_round_already_persisted
                    and not interrupted_tool_round_completed
                    else None
                ),
            )

        await asyncio.to_thread(self._persistence.save_runtime_status, request, "idle")
        await self.record_assistant_usage_best_effort(
            request,
            assistant_message,
            completed_usage,
        )
        await self.record_ai_run_elapsed(
            user_message,
            assistant_message,
            run_started_at=run_started_at,
        )
        status = (
            "done"
            if assistant_message is not None and assistant_message.status == "done"
            else "cancelled"
        )
        await asyncio.to_thread(
            self._persistence.settle_run,
            request,
            status=status,
            attempt_count=max(1, request.upstream_attempt_index),
        )
        return (
            assistant_message,
            conversation_run_settled_payload(
                user_message,
                assistant_message,
                status=status,
            ),
        )

    async def settle_failed(
        self,
        request: ChatCompletionRequest,
        user_message: ProjectConversationMessage | None,
        *,
        run_started_at: float,
        assistant_message: ProjectConversationMessage | None = None,
        content: str,
        error_code: str | None,
        attempt_count: int,
        usage: ChatUsage | None,
        usage_payload: dict[str, object] | None,
        context_tokens: int | None,
        context_tokens_estimated: bool,
    ) -> tuple[ProjectConversationMessage | None, dict[str, object | None] | None]:
        if user_message is not None:
            await asyncio.to_thread(self._persistence.save_runtime_status, request, "error")
        await asyncio.to_thread(
            self._persistence.settle_run,
            request,
            status="error",
            error_code=error_code,
            error_message=content,
            attempt_count=attempt_count,
        )
        await self.record_ai_run_elapsed(
            user_message,
            assistant_message,
            run_started_at=run_started_at,
        )
        await self.record_assistant_usage_best_effort(request, assistant_message, usage)
        return (
            assistant_message,
            conversation_run_settled_payload(
                user_message,
                assistant_message,
                status="error",
            ),
        )

    async def record_ai_run_elapsed(
        self,
        user_message: ProjectConversationMessage | None,
        assistant_message: ProjectConversationMessage | None,
        *,
        run_started_at: float | None,
    ) -> None:
        elapsed_ms = (
            None
            if run_started_at is None
            else max(0, round((monotonic() - run_started_at) * 1000))
        )
        await asyncio.to_thread(
            self._persistence.record_ai_run_elapsed,
            user_message,
            assistant_message,
            elapsed_ms=elapsed_ms,
        )

    async def record_assistant_usage_best_effort(
        self,
        request: ChatCompletionRequest,
        assistant_message: ProjectConversationMessage | None,
        usage: ChatUsage | None,
    ) -> None:
        try:
            await asyncio.to_thread(
                self._persistence.record_assistant_usage,
                request,
                assistant_message,
                usage,
            )
        except Exception:
            logger.exception("Failed to record usage after an assistant message was persisted.")

    def _complete_interrupted_round_usage(
        self,
        *,
        model_request: ChatCompletionRequest | None,
        round_already_persisted: bool,
        provider_usage: ChatUsage | None,
        answer_parts: list[str],
        thinking_parts: list[str],
        content_parts: list[ChatMessageContentPart],
        current_usage_payload: dict[str, object] | None,
        current_context_tokens: int | None,
        current_context_tokens_estimated: bool,
    ) -> tuple[ChatUsage | None, dict[str, object] | None, int | None, bool]:
        if round_already_persisted or model_request is None:
            return (
                provider_usage,
                current_usage_payload,
                current_context_tokens,
                current_context_tokens_estimated,
            )

        completed_usage = complete_usage_with_estimates(
            request=model_request,
            provider_usage=provider_usage,
            response_message=ChatMessage(
                role=ChatMessageRole.ASSISTANT,
                content="".join(answer_parts),
                thinking_content="".join(thinking_parts),
                content_parts=tuple(content_parts),
            ),
            settings=self._token_estimation_settings_service.get_settings(),
        )
        return (
            completed_usage,
            usage_to_payload(completed_usage),
            completed_usage.prompt_tokens,
            "prompt_tokens" in completed_usage.estimated_fields,
        )
