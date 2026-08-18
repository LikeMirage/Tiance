from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.core.errors import AppError, BadRequestError, ConflictError, NotFoundError
from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatMessageContentPart,
    ChatMessageRole,
    ChatUsage,
)
from app.domain.project.project_conversation import (
    ProjectConversationMessage,
    ProjectConversationSession,
)
from app.services.llm.usage import LlmUsageService
from app.services.project.conversation_background_tasks import (
    ConversationBackgroundTaskRegistry,
)
from app.services.project.conversation_memory import ProjectConversationMemoryService
from app.services.project.conversation_model_exchange import build_model_exchange_record
from app.services.project.conversation_naming import ProjectConversationNamingService
from app.services.project.conversation_long_term_memory import (
    ProjectConversationLongTermMemoryService,
)
from app.services.project.conversation_run_snapshot import ConversationRunSnapshot
from app.services.project.conversation_stream_events import tool_result_message_content
from app.services.project.project_conversations import ProjectConversationService
from app.services.project.conversation_references import (
    normalize_conversation_references,
    references_from_chat_message,
)
from app.services.tools.tool_call_records import ToolCallRecordService
from app.services.tools.tool_cancellation import (
    ToolCancellationScope,
    cancelled_tool_result,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ExistingConversationRequestTurn:
    reply: ProjectConversationMessage | None
    user: ProjectConversationMessage


def _log_background_task_error(task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("Conversation background task failed.")


class ConversationStreamPersistence:
    def __init__(
        self,
        *,
        conversation_service: ProjectConversationService,
        usage_service: LlmUsageService,
        naming_service: ProjectConversationNamingService,
        memory_service: ProjectConversationMemoryService,
        background_task_registry: ConversationBackgroundTaskRegistry,
        tool_call_record_service: ToolCallRecordService | None = None,
        long_term_memory_service: (
            ProjectConversationLongTermMemoryService | None
        ) = None,
    ) -> None:
        self._conversation_service = conversation_service
        self._usage_service = usage_service
        self._naming_service = naming_service
        self._memory_service = memory_service
        self._long_term_memory_service = long_term_memory_service
        self._background_task_registry = background_task_registry
        self._tool_call_record_service = tool_call_record_service

    def validate_conversation_target(self, request: ChatCompletionRequest) -> None:
        if not request.project_id or not request.session_id:
            return
        self._conversation_service.list_messages(request.project_id, request.session_id)

    def sync_session_metadata(self, request: ChatCompletionRequest) -> None:
        if not request.project_id or not request.session_id:
            return
        reasoning_mode = None
        if request.generation.reasoning is not None:
            reasoning_mode = request.generation.reasoning.mode.value
        try:
            self._conversation_service.update_session(
                request.project_id,
                request.session_id,
                provider_id=request.provider_id,
                should_update_provider=True,
                model_id=request.model_id,
                should_update_model=True,
                reasoning_mode=reasoning_mode,
                should_update_reasoning=reasoning_mode is not None,
            )
        except AppError:
            return

    def append_user_message(self, request: ChatCompletionRequest) -> ProjectConversationMessage | None:
        if not request.project_id or not request.session_id:
            return None
        user_messages = [
            message for message in request.messages if message.role == ChatMessageRole.USER
        ]
        if not user_messages:
            return None
        last_user_message = user_messages[-1]
        references = references_from_chat_message(last_user_message)
        if self._matching_pending_user_message(request, last_user_message) is not None:
            return None
        message = self._append_conversation_message(
            request.project_id,
            request.session_id,
            role="user",
            content=last_user_message.content,
            content_parts=last_user_message.content_parts,
            references=references,
            provider_id=request.provider_id,
            model_id=request.model_id,
            message_id=last_user_message.message_id,
        )
        self._conversation_service.record_user_message_sent(message)
        return message

    def existing_request_turn(
        self,
        request: ChatCompletionRequest,
    ) -> ExistingConversationRequestTurn | None:
        requested_user = next(
            (message for message in reversed(request.messages) if message.role == ChatMessageRole.USER),
            None,
        )
        if requested_user is None or requested_user.message_id is None:
            return None
        if not request.project_id or not request.session_id:
            return None
        try:
            turn = self._conversation_service.get_message_turn(
                request.project_id,
                request.session_id,
                requested_user.message_id,
            )
        except NotFoundError:
            return None
        except BadRequestError as exc:
            raise ConflictError(
                f"Conversation message '{requested_user.message_id}' already exists with a non-user role."
            ) from exc

        existing_user = turn.items[0]
        requested_references = references_from_chat_message(requested_user)
        if not (
            existing_user.content == requested_user.content
            and existing_user.content_parts == requested_user.content_parts
            and normalize_conversation_references(existing_user.references) == requested_references
            and existing_user.target_provider_id == request.provider_id
            and existing_user.target_model_id == request.model_id
        ):
            raise ConflictError(
                f"Conversation message '{requested_user.message_id}' already exists with different content."
            )

        self._conversation_service.record_user_message_sent(existing_user)
        reply = None
        for message in turn.items[1:]:
            if (
                message.role in {"assistant", "error"}
                and message.status in {"done", "error", "cancelled"}
            ):
                reply = message
        return ExistingConversationRequestTurn(user=existing_user, reply=reply)

    def current_user_message(
        self,
        request: ChatCompletionRequest,
    ) -> ProjectConversationMessage | None:
        last_user_message = next(
            (message for message in reversed(request.messages) if message.role == ChatMessageRole.USER),
            None,
        )
        if last_user_message is None:
            return None
        return self._matching_pending_user_message(request, last_user_message)

    def record_ai_run_elapsed(
        self,
        user_message: ProjectConversationMessage | None,
        assistant_message: ProjectConversationMessage | None,
        *,
        elapsed_ms: int | None,
    ) -> None:
        if user_message is None:
            return
        self._conversation_service.record_ai_run_elapsed(
            user_message,
            assistant_message=assistant_message,
            elapsed_ms=elapsed_ms,
        )

    def session_snapshot(
        self,
        request: ChatCompletionRequest,
    ) -> ProjectConversationSession | None:
        if not request.project_id or not request.session_id:
            return None
        return self._conversation_service.get_session(
            request.project_id,
            request.session_id,
        )

    def prepare_long_term_memory_delivery(
        self,
        request: ChatCompletionRequest,
        user_message: ProjectConversationMessage | None,
    ) -> None:
        if not request.project_id or not request.session_id:
            return
        target_message = user_message
        if target_message is None:
            last_user_message = next(
                (
                    message
                    for message in reversed(request.messages)
                    if message.role == ChatMessageRole.USER
                ),
                None,
            )
            if last_user_message is not None:
                target_message = self._matching_pending_user_message(
                    request,
                    last_user_message,
                )
        if target_message is None:
            return
        self._memory_service.prepare_long_term_memory_delivery(
            request.project_id,
            request.session_id,
            target_message.message_id,
            provider_id=request.provider_id,
            model_id=request.model_id,
        )

    def append_assistant_message(
        self,
        request: ChatCompletionRequest,
        *,
        content: str,
        thinking_content: str = "",
        content_parts: tuple[ChatMessageContentPart, ...] = (),
        usage: dict[str, object] | None = None,
        context_tokens: int | None = None,
        context_tokens_estimated: bool = False,
        status: str,
        sync_session_model: bool = False,
    ) -> ProjectConversationMessage | None:
        if not request.project_id or not request.session_id:
            return None
        if not content.strip() and not thinking_content.strip() and not content_parts:
            return None
        return self._append_conversation_message(
            request.project_id,
            request.session_id,
            role="assistant" if status != "error" else "error",
            content=content,
            thinking_content=thinking_content,
            content_parts=content_parts,
            usage=usage,
            context_tokens=context_tokens,
            context_tokens_estimated=context_tokens_estimated,
            provider_id=request.provider_id,
            model_id=request.model_id,
            status=status,
            sync_session_model=sync_session_model,
        )

    def append_interrupted_assistant_message(
        self,
        request: ChatCompletionRequest,
        *,
        answer_parts: list[str],
        thinking_parts: list[str],
        content_parts: list[ChatMessageContentPart],
        usage_payload: dict[str, object] | None,
        context_tokens: int | None,
        context_tokens_estimated: bool = False,
        persisted_tool_call_message_id: str | None = None,
    ) -> ProjectConversationMessage | None:
        if not request.project_id or not request.session_id:
            return None
        content = "".join(answer_parts)
        thinking_content = "".join(thinking_parts)
        if content.strip() or thinking_content.strip() or content_parts:
            return self.append_assistant_message(
                request,
                content=content,
                thinking_content=thinking_content,
                content_parts=tuple(content_parts),
                usage=usage_payload,
                context_tokens=context_tokens,
                context_tokens_estimated=context_tokens_estimated,
                status="cancelled",
                sync_session_model=False,
            )
        if persisted_tool_call_message_id is not None:
            return self._conversation_service.cancel_assistant_message(
                request.project_id,
                request.session_id,
                persisted_tool_call_message_id,
                usage=usage_payload,
                context_tokens=context_tokens,
                context_tokens_estimated=context_tokens_estimated,
            )
        return self._append_conversation_message(
            request.project_id,
            request.session_id,
            role="assistant",
            content="",
            usage=usage_payload,
            context_tokens=context_tokens,
            context_tokens_estimated=context_tokens_estimated,
            provider_id=request.provider_id,
            model_id=request.model_id,
            status="cancelled",
            sync_session_model=False,
        )

    def complete_interrupted_tool_round(
        self,
        request: ChatCompletionRequest,
        assistant_message_id: str,
        *,
        cancellation_scopes: dict[str, ToolCancellationScope],
    ) -> bool:
        if not request.project_id or not request.session_id:
            return False
        messages = self._conversation_service.list_messages(
            request.project_id,
            request.session_id,
        )
        assistant_index = next(
            (
                index
                for index, message in enumerate(messages)
                if message.message_id == assistant_message_id
            ),
            None,
        )
        if assistant_index is None:
            return False
        assistant_message = messages[assistant_index]
        if assistant_message.role != "assistant" or not assistant_message.tool_calls:
            return False

        completed_call_ids: set[str] = set()
        for message in messages[assistant_index + 1 :]:
            if message.role != "tool":
                break
            if message.tool_call_id:
                completed_call_ids.add(message.tool_call_id)

        for tool_call in assistant_message.tool_calls:
            if tool_call.call_id in completed_call_ids:
                continue
            result = cancelled_tool_result(
                tool_call,
                scope=cancellation_scopes.get(
                    tool_call.call_id,
                    ToolCancellationScope.CALL,
                ),
            )
            self._append_conversation_message(
                request.project_id,
                request.session_id,
                role="tool",
                content=tool_result_message_content(result),
                name=result.name,
                tool_call_id=result.call_id,
                status="cancelled",
                sync_session_model=False,
            )
            if self._tool_call_record_service is not None:
                try:
                    self._tool_call_record_service.append_result(
                        result,
                        project_id=request.project_id,
                        session_id=request.session_id,
                    )
                except Exception:
                    logger.exception(
                        "Failed to record a cancelled tool call result.",
                    )
        return True

    def record_assistant_usage(
        self,
        request: ChatCompletionRequest,
        assistant_message: ProjectConversationMessage | None,
        usage: ChatUsage | None,
    ) -> None:
        if usage is None or assistant_message is None:
            return
        if not request.project_id or not request.session_id:
            return
        self._usage_service.record_message_usage(
            project_id=request.project_id,
            session_id=request.session_id,
            message_id=assistant_message.message_id,
            provider_id=request.provider_id,
            model_id=request.model_id,
            usage=usage,
            usage_feature_key=request.usage_feature_key,
        )

    def record_model_exchange(
        self,
        request: ChatCompletionRequest,
        assistant_message: ProjectConversationMessage | None,
        *,
        round_index: int,
        usage: ChatUsage | None,
    ) -> None:
        if assistant_message is None or not request.project_id or not request.session_id:
            return
        try:
            self._conversation_service.append_model_exchange(
                request.project_id,
                request.session_id,
                build_model_exchange_record(
                    request,
                    assistant_message,
                    round_index=round_index,
                    usage=usage,
                ),
            )
        except Exception:
            logger.exception("Failed to record a model request and response round.")

    def schedule_memory_compression(
        self,
        request: ChatCompletionRequest,
        assistant_message: ProjectConversationMessage | None,
        *,
        session_snapshot: ProjectConversationSession | None = None,
        run_snapshot: ConversationRunSnapshot | None = None,
    ) -> asyncio.Task | None:
        if assistant_message is None:
            return None
        if not request.project_id or not request.session_id:
            return None
        task = self._background_task_registry.create_task(
            request.project_id,
            request.session_id,
            self._memory_service.compact_context_if_enabled(
                request.project_id,
                request.session_id,
                blocking=False,
                session_snapshot=session_snapshot,
                run_snapshot=run_snapshot,
            ),
            name="conversation-memory-compression",
        )
        self._track_background_task(task)
        return task

    def schedule_session_naming(
        self,
        request: ChatCompletionRequest,
        assistant_message: ProjectConversationMessage | None,
        *,
        run_snapshot: ConversationRunSnapshot | None = None,
    ) -> asyncio.Task | None:
        if assistant_message is None:
            return None
        if not request.project_id or not request.session_id:
            return None
        task = self._background_task_registry.create_task(
            request.project_id,
            request.session_id,
            self._naming_service.name_session_if_needed(
                request.project_id,
                request.session_id,
                run_snapshot=run_snapshot,
            ),
            name="conversation-session-naming",
        )
        self._track_background_task(task)
        return task

    async def memory_compression_is_blocking(self) -> bool:
        if not hasattr(self._memory_service, "is_blocking_enabled"):
            return False
        return await self._memory_service.is_blocking_enabled()

    def schedule_long_term_memory_management(
        self,
        request: ChatCompletionRequest,
        assistant_message: ProjectConversationMessage | None,
        *,
        session_snapshot: ProjectConversationSession | None = None,
        run_snapshot: ConversationRunSnapshot | None = None,
    ) -> asyncio.Task | None:
        if (
            self._long_term_memory_service is None
            or assistant_message is None
            or not request.project_id
            or not request.session_id
        ):
            return None
        task = self._background_task_registry.create_task(
            request.project_id,
            request.session_id,
            self._long_term_memory_service.manage_context_if_enabled(
                request.project_id,
                request.session_id,
                blocking=False,
                session_snapshot=session_snapshot,
                run_snapshot=run_snapshot,
            ),
            name="conversation-long-term-memory-management",
        )
        self._track_background_task(task)
        return task

    async def run_long_term_memory_management(
        self,
        request: ChatCompletionRequest,
        assistant_message: ProjectConversationMessage | None,
        *,
        session_snapshot: ProjectConversationSession | None = None,
        run_snapshot: ConversationRunSnapshot | None = None,
    ) -> None:
        if (
            self._long_term_memory_service is None
            or assistant_message is None
            or not request.project_id
            or not request.session_id
        ):
            return
        await self._long_term_memory_service.manage_context_if_enabled(
            request.project_id,
            request.session_id,
            blocking=True,
            session_snapshot=session_snapshot,
            run_snapshot=run_snapshot,
        )

    def schedule_long_term_memory_request_check(
        self,
        request: ChatCompletionRequest,
        model_request: ChatCompletionRequest,
        *,
        session_snapshot: ProjectConversationSession | None = None,
    ) -> asyncio.Task | None:
        if (
            self._long_term_memory_service is None
            or not request.project_id
            or not request.session_id
        ):
            return None
        task = self._background_task_registry.create_task(
            request.project_id,
            request.session_id,
            self._long_term_memory_service.manage_request_if_enabled(
                request.project_id,
                request.session_id,
                blocking=False,
                model_request=model_request,
                session_snapshot=session_snapshot,
            ),
            name="conversation-long-term-memory-request-check",
        )
        self._track_background_task(task)
        return task

    async def run_long_term_memory_request_check(
        self,
        request: ChatCompletionRequest,
        model_request: ChatCompletionRequest,
        *,
        session_snapshot: ProjectConversationSession | None = None,
    ) -> None:
        if (
            self._long_term_memory_service is None
            or not request.project_id
            or not request.session_id
        ):
            return
        await self._long_term_memory_service.manage_request_if_enabled(
            request.project_id,
            request.session_id,
            blocking=True,
            model_request=model_request,
            session_snapshot=session_snapshot,
        )

    async def run_memory_compression(
        self,
        request: ChatCompletionRequest,
        assistant_message: ProjectConversationMessage | None,
        *,
        session_snapshot: ProjectConversationSession | None = None,
        run_snapshot: ConversationRunSnapshot | None = None,
    ) -> None:
        if assistant_message is None:
            return
        if not request.project_id or not request.session_id:
            return
        await self._memory_service.compact_context_if_enabled(
            request.project_id,
            request.session_id,
            blocking=True,
            session_snapshot=session_snapshot,
            run_snapshot=run_snapshot,
        )

    def schedule_memory_request_check(
        self,
        request: ChatCompletionRequest,
        model_request: ChatCompletionRequest,
        *,
        session_snapshot: ProjectConversationSession | None = None,
    ) -> asyncio.Task | None:
        if not request.project_id or not request.session_id:
            return None
        if not hasattr(self._memory_service, "compact_request_if_enabled"):
            return None
        task = self._background_task_registry.create_task(
            request.project_id,
            request.session_id,
            self._memory_service.compact_request_if_enabled(
                request.project_id,
                request.session_id,
                blocking=False,
                model_request=model_request,
                session_snapshot=session_snapshot,
            ),
            name="conversation-memory-request-check",
        )
        self._track_background_task(task)
        return task

    async def run_memory_request_check(
        self,
        request: ChatCompletionRequest,
        model_request: ChatCompletionRequest,
        *,
        session_snapshot: ProjectConversationSession | None = None,
    ) -> None:
        if not request.project_id or not request.session_id:
            return
        if not hasattr(self._memory_service, "compact_request_if_enabled"):
            return
        await self._memory_service.compact_request_if_enabled(
            request.project_id,
            request.session_id,
            blocking=True,
            model_request=model_request,
            session_snapshot=session_snapshot,
        )

    def _track_background_task(self, task: asyncio.Task) -> None:
        task.add_done_callback(_log_background_task_error)

    def conversation_target_exists(self, request: ChatCompletionRequest) -> bool:
        if not request.project_id or not request.session_id:
            return True
        try:
            return self._conversation_service.get_session(
                request.project_id,
                request.session_id,
            ) is not None
        except AppError:
            return False

    def save_runtime_status(self, request: ChatCompletionRequest, status: str) -> None:
        if not request.project_id or not request.session_id:
            return
        try:
            self._conversation_service.save_session_runtime_status(
                request.project_id,
                request.session_id,
                status,
            )
        except AppError:
            return

    def _matching_pending_user_message(
        self,
        request: ChatCompletionRequest,
        last_user_message: ChatMessage,
    ) -> ProjectConversationMessage | None:
        if not request.project_id or not request.session_id:
            return None
        try:
            existing_messages = self._conversation_service.list_messages(
                request.project_id,
                request.session_id,
            )
        except AppError:
            return None
        if not existing_messages:
            return None
        last_existing_message = existing_messages[-1]
        requested_references = references_from_chat_message(last_user_message)
        matches = (
            last_existing_message.role == "user"
            and (
                last_user_message.message_id is None
                or last_existing_message.message_id == last_user_message.message_id
            )
            and last_existing_message.content == last_user_message.content
            and last_existing_message.content_parts == last_user_message.content_parts
            and normalize_conversation_references(last_existing_message.references) == requested_references
            and last_existing_message.target_provider_id == request.provider_id
            and last_existing_message.target_model_id == request.model_id
        )
        return last_existing_message if matches else None

    def _append_conversation_message(
        self,
        project_id: str,
        session_id: str,
        **kwargs,
    ) -> ProjectConversationMessage | None:
        return self._conversation_service.append_message(project_id, session_id, **kwargs)
