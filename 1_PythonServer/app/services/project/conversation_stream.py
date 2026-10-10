import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing
from dataclasses import replace
from functools import lru_cache
from time import monotonic
from uuid import uuid4

from app.domain.llm.output_limit import OutputLimitRecoveryBudget, OUTPUT_LIMIT_MESSAGE_PREFIX
from typing import Any

import httpx

from app.core.errors import AppError, local_exception_message, upstream_http_error_message
from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatMessage,
    ChatMessageRole,
    ChatMessageContentPart,
    ChatStreamEvent,
    ChatStreamEventKind,
    ChatToolCall,
    ChatUsage,
)
from app.domain.project.project_conversation import ProjectConversationMessage
from app.services.llm.chat.service import ChatCompletionService, get_chat_completion_service
from app.services.llm.runtime import (
    LlmRuntimeCapabilitiesService,
    get_llm_runtime_capabilities_service,
)
from app.services.llm.usage import LlmUsageService, get_llm_usage_service
from app.services.llm.token_estimation_settings import (
    TokenEstimationSettingsService,
    get_token_estimation_settings_service,
)
from app.services.project.conversation_background_tasks import (
    ConversationBackgroundTaskRegistry,
    get_conversation_background_task_registry,
)
from app.services.project.conversation_stream_context import ConversationStreamContextBuilder
from app.services.project.conversation_stream_checkpoints import (
    ConversationPersistenceCheckpoint,
    persistence_checkpoint_payload,
)
from app.services.project.conversation_naming import (
    ProjectConversationNamingService,
    get_project_conversation_naming_service,
)
from app.services.project.conversation_functional_run import (
    FunctionalConversationRunError,
)
from app.services.project.conversation_memory import (
    ProjectConversationMemoryService,
    get_project_conversation_memory_service,
)
from app.services.project.conversation_long_term_memory import (
    ProjectConversationLongTermMemoryService,
    get_project_conversation_long_term_memory_service,
)
from app.services.project.conversation_image_references import (
    ConversationImageReferenceResolver,
    get_conversation_image_reference_resolver,
)
from app.services.project.conversation_attachments import (
    ConversationAttachmentService,
    get_conversation_attachment_service,
)
from app.services.project.conversation_audit import get_conversation_audit_service
from app.services.project.conversation_stream_persistence import ConversationStreamPersistence
from app.services.project.conversation_stream_settlement import ConversationStreamSettlement
from app.services.project.conversation_stream_events import stream_event_to_payload
from app.services.project.conversation_notifications import conversation_notifications
from app.services.project.conversation_stream_run_events import (
    conversation_run_settled_payload,
    conversation_run_started_payload,
)
from app.services.project.conversation_stream_usage import merge_usage, usage_to_payload
from app.services.project.conversation_run_snapshot import build_conversation_run_snapshot
from app.services.project.conversation_run_manager import (
    ConversationRunManager,
    get_conversation_run_manager,
)
from app.services.project.conversation_tool_loop import ConversationToolLoop
from app.services.project.project_conversations import (
    ProjectConversationService,
    get_project_conversation_service,
)
from app.services.project.projects import ProjectService, get_project_service
from app.services.tools.chat_tool_injection import (
    ChatToolInjectionService,
    get_chat_tool_injection_service,
)
from app.services.tools.tool_execution import (
    ToolExecutionService,
    get_tool_execution_service,
)
from app.services.tools.tool_result_guidance import (
    ToolResultGuidanceService,
    get_tool_result_guidance_service,
)
from app.services.tools.tool_call_records import (
    ToolCallRecordService,
    get_tool_call_record_service,
)
from app.services.tools.client_tool_bridge import (
    ClientToolBridgeService,
    get_client_tool_bridge_service,
)
from app.services.tools.tool_cancellation import ToolCancellationScope


logger = logging.getLogger(__name__)
_STREAM_HEARTBEAT_SECONDS = 10.0


class ProjectConversationStreamService:
    def __init__(
        self,
        chat_service: ChatCompletionService,
        conversation_service: ProjectConversationService,
        usage_service: LlmUsageService,
        naming_service: ProjectConversationNamingService,
        memory_service: ProjectConversationMemoryService,
        tool_injection_service: ChatToolInjectionService | None = None,
        tool_execution_service: ToolExecutionService | None = None,
        tool_result_guidance_service: ToolResultGuidanceService | None = None,
        project_service: ProjectService | None = None,
        tool_call_record_service: ToolCallRecordService | None = None,
        image_reference_resolver: ConversationImageReferenceResolver | None = None,
        client_tool_bridge_service: ClientToolBridgeService | None = None,
        background_task_registry: ConversationBackgroundTaskRegistry | None = None,
        runtime_capabilities_service: LlmRuntimeCapabilitiesService | None = None,
        attachment_service: ConversationAttachmentService | None = None,
        run_manager: ConversationRunManager | None = None,
        token_estimation_settings_service: TokenEstimationSettingsService | None = None,
        long_term_memory_service: (
            ProjectConversationLongTermMemoryService | None
        ) = None,
    ) -> None:
        self._chat_service = chat_service
        self._tool_call_record_service = tool_call_record_service
        self._image_reference_resolver = image_reference_resolver
        self._background_task_registry = (
            background_task_registry or get_conversation_background_task_registry()
        )
        self._audit_service = get_conversation_audit_service()
        self._run_manager = run_manager or get_conversation_run_manager()
        self._token_estimation_settings_service = (
            token_estimation_settings_service
            or get_token_estimation_settings_service()
        )
        self._persistence = ConversationStreamPersistence(
            conversation_service=conversation_service,
            usage_service=usage_service,
            naming_service=naming_service,
            memory_service=memory_service,
            long_term_memory_service=long_term_memory_service,
            background_task_registry=self._background_task_registry,
            tool_call_record_service=tool_call_record_service,
        )
        self._settlement = ConversationStreamSettlement(
            persistence=self._persistence,
            token_estimation_settings_service=self._token_estimation_settings_service,
        )
        self._context_builder = ConversationStreamContextBuilder(
            conversation_service=conversation_service,
            memory_service=memory_service,
            tool_injection_service=tool_injection_service,
        )
        self._tool_loop = ConversationToolLoop(
            chat_service=chat_service,
            conversation_service=conversation_service,
            tool_execution_service=tool_execution_service,
            tool_result_guidance_service=tool_result_guidance_service,
            project_service=project_service,
            tool_call_record_service=tool_call_record_service,
            client_tool_bridge_service=client_tool_bridge_service,
            runtime_capabilities_service=runtime_capabilities_service,
            attachment_service=attachment_service or get_conversation_attachment_service(),
            audit_service=self._audit_service,
        )
        if hasattr(memory_service, "set_functional_conversation_runner"):
            memory_service.set_functional_conversation_runner(
                self._run_functional_conversation
            )
        if long_term_memory_service is not None:
            long_term_memory_service.set_functional_conversation_runner(
                self._run_functional_conversation
            )

    def validate_conversation_target(self, request: ChatCompletionRequest) -> None:
        self._persistence.validate_conversation_target(request)

    async def update_injection_preview(
        self,
        request: ChatCompletionRequest,
    ) -> dict[str, Any] | None:
        await asyncio.to_thread(self._persistence.validate_conversation_target, request)
        request = await self._prepare_image_references(request)
        session_request = await asyncio.to_thread(
            self._context_builder.rebuild_session_request_messages,
            request,
        )
        session_request = await self._prepare_image_references(session_request)
        compressed_request = await asyncio.to_thread(
            self._context_builder.replace_session_compressed_history,
            session_request,
        )
        memory_request = await asyncio.to_thread(
            self._context_builder.inject_session_long_term_memory,
            compressed_request,
            include_pending_changes=True,
        )
        preview_request = replace(
            await asyncio.to_thread(self._context_builder.inject_session_tools, memory_request),
            record_usage=False,
        )
        return await asyncio.to_thread(
            self._context_builder.write_injection_preview,
            preview_request,
            preview_source="draft_request",
        )

    async def stream_payloads(
        self,
        request: ChatCompletionRequest,
        *,
        await_background_tasks: bool = False,
        include_persistence_checkpoints: bool = False,
    ) -> AsyncGenerator[dict[str, object | None], None]:
        # One manager task owns all automatic user turns, so stop cancels the chain.
        request = replace(request, output_limit_budget=OutputLimitRecoveryBudget(), record_attempt_usage=True, emit_response_boundaries=True)
        pending_user: dict | None = None
        conversation_notifications.open(request.project_id, request.session_id)
        try:
            while True:
                try:
                    continuation = await asyncio.to_thread(self._persistence.output_limit_continuation, request)
                except AppError:
                    # Let the regular run pipeline report conflicts/deletions with its usual semantics.
                    continuation = None
                if continuation is not None:
                    parent, next_user, saved = continuation
                    started = conversation_run_started_payload(parent)
                    if started:
                        yield started
                    pending_user = _output_limit_message_payload(next_user)
                    yield {
                        "kind": "output_limit", "action": "send_message", "will_recover": True,
                        "saved_message": _output_limit_message_payload(saved),
                        "next_user_message": pending_user, "usage": None,
                    }
                    request.output_limit_budget.used += 1
                    request = _output_limit_continuation_request(request, pending_user)
                    continue
                next_message: dict | None = None
                single_run = self._stream_single_run_payloads(
                    request,
                    await_background_tasks=await_background_tasks,
                    include_persistence_checkpoints=include_persistence_checkpoints,
                )
                try:
                    async for payload in single_run:
                        if payload.get("kind") == "output_limit" and payload.get("will_recover") and payload.get("action") == "send_message":
                            next_message = payload.get("next_user_message")
                            pending_user = next_message
                        if payload.get("kind") in {"conversation_run_started", "conversation_run_settled"} and pending_user and payload.get("user_message_id") == pending_user["message_id"]:
                            pending_user = None
                        yield payload
                finally:
                    await single_run.aclose()
                if next_message is None:
                    return
                request = _output_limit_continuation_request(request, next_message)
        except (asyncio.CancelledError, GeneratorExit) as exc:
            # A stop may arrive after the automatic user is durable but before its run starts.
            if pending_user is not None:
                cancelled_request = _output_limit_continuation_request(request, pending_user)
                try:
                    user = await asyncio.to_thread(self._persistence.current_user_message, cancelled_request)
                    await asyncio.to_thread(self._persistence.begin_run, cancelled_request, user)
                    await asyncio.to_thread(self._persistence.settle_run, cancelled_request, status="cancelled", attempt_count=1)
                    await asyncio.to_thread(self._persistence.save_runtime_status, cancelled_request, "idle")
                    settled = conversation_run_settled_payload(user, None, status="cancelled")
                    if settled is not None and not isinstance(exc, GeneratorExit):
                        yield settled
                except Exception:
                    logger.exception("Failed to settle a pending output-limit continuation.")
            raise
        finally:
            # Cancellation, errors and generator closure also release pending notices.
            await conversation_notifications.close(request.project_id, request.session_id)

    async def _stream_single_run_payloads(
        self,
        request: ChatCompletionRequest,
        *,
        await_background_tasks: bool = False,
        include_persistence_checkpoints: bool = False,
    ) -> AsyncGenerator[dict[str, object | None], None]:
        answer_parts: list[str] = []
        thinking_parts: list[str] = []
        assistant_content_parts: list[ChatMessageContentPart] = []
        usage_payload: dict[str, object] | None = None
        usage: ChatUsage | None = None
        context_tokens: int | None = None
        context_tokens_estimated = False
        done_payload: dict[str, object | None] | None = None
        final_response_boundary: ChatStreamEvent | None = None
        background_tasks: list[asyncio.Task] = []
        blocking_before_next_model_request: list[asyncio.Task] = []
        run_started_at = monotonic()
        last_heartbeat = monotonic()
        memory_session_snapshot = None
        memory_compression_blocking = False
        last_model_request: ChatCompletionRequest | None = None
        run_user_message: ProjectConversationMessage | None = None
        final_assistant_message: ProjectConversationMessage | None = None
        model_round_serial = 0
        persisted_tool_call_message_id: str | None = None
        persisted_tool_call_round_serial: int | None = None
        cancelled_tool_scopes: dict[str, ToolCancellationScope] = {}
        upstream_attempt_index = 1

        def capture_model_request(model_request: ChatCompletionRequest) -> None:
            nonlocal usage, usage_payload
            nonlocal context_tokens, context_tokens_estimated, last_model_request
            nonlocal model_round_serial, upstream_attempt_index
            last_model_request = model_request
            if model_request.output_limit_budget is not None:
                model_request.output_limit_budget.last_round_usage_recorded = False
            model_round_serial += 1
            # Attempt indexes are local to one upstream model round.  A retry in
            # an earlier tool round must not leak into the final run outcome.
            upstream_attempt_index = 1
            usage = None
            usage_payload = None
            context_tokens = None
            context_tokens_estimated = False

        def schedule_model_exchange(
            model_request: ChatCompletionRequest,
            assistant_message: ProjectConversationMessage | None,
            *,
            round_index: int,
            round_usage: ChatUsage | None,
        ) -> None:
            if (
                assistant_message is None
                or not model_request.project_id
                or not model_request.session_id
            ):
                return
            task = self._audit_service.create_session_task(
                model_request.project_id,
                model_request.session_id,
                asyncio.to_thread(
                    self._persistence.record_model_exchange,
                    model_request,
                    assistant_message,
                    round_index=round_index,
                    usage=round_usage,
                ),
                name="conversation-model-exchange-audit",
            )
            background_tasks.append(task)

        async def prepare_next_tool_loop_model_request(
            model_request: ChatCompletionRequest,
        ) -> ChatCompletionRequest:
            if blocking_before_next_model_request:
                tasks = tuple(blocking_before_next_model_request)
                blocking_before_next_model_request.clear()
                await asyncio.gather(*tasks)
            return await self._refresh_tool_loop_memory_context(model_request)

        async def schedule_completed_model_round(
            model_request: ChatCompletionRequest,
            assistant_message: ProjectConversationMessage,
            round_usage: ChatUsage | None,
        ) -> None:
            nonlocal usage, usage_payload, context_tokens, context_tokens_estimated
            nonlocal persisted_tool_call_message_id
            nonlocal persisted_tool_call_round_serial
            persisted_tool_call_message_id = assistant_message.message_id
            persisted_tool_call_round_serial = model_round_serial
            answer_parts.clear()
            thinking_parts.clear()
            await self._settlement.record_assistant_usage_best_effort(
                model_request,
                assistant_message,
                round_usage,
            )
            schedule_model_exchange(
                model_request,
                assistant_message,
                round_index=model_round_serial,
                round_usage=round_usage,
            )
            usage = None
            usage_payload = None
            context_tokens = None
            context_tokens_estimated = False
            run_snapshot = build_conversation_run_snapshot(
                model_request,
                assistant_message,
            )
            if not memory_compression_blocking:
                task = self._persistence.schedule_memory_compression(
                    request,
                    assistant_message,
                    session_snapshot=memory_session_snapshot,
                    run_snapshot=run_snapshot,
                )
                if task is not None:
                    background_tasks.append(task)

            task = self._persistence.schedule_tool_round_blocking_memory(
                request,
                assistant_message,
                include_compression=memory_compression_blocking,
                await_nonblocking_followup=await_background_tasks,
                session_snapshot=memory_session_snapshot,
                run_snapshot=run_snapshot,
            )
            if task is not None:
                blocking_before_next_model_request.append(task)
                background_tasks.append(task)

        def capture_cancelled_tool_call(
            tool_call: ChatToolCall,
            scope: ToolCancellationScope,
        ) -> None:
            cancelled_tool_scopes[tool_call.call_id] = scope

        try:
            existing_turn = await asyncio.to_thread(
                self._persistence.existing_request_turn,
                request,
            )
            if existing_turn is not None and existing_turn.reply is not None:
                run_user_message = existing_turn.user
                existing_status = (
                    "cancelled"
                    if existing_turn.reply.status == "cancelled"
                    else "error"
                    if existing_turn.reply.role == "error" or existing_turn.reply.status == "error" or existing_turn.reply.finish_reason == "output_limit"
                    else "done"
                )
                # The assistant reply can be durable before the process gets a
                # chance to persist the matching session runtime state. Replay
                # repairs only that derived state; model/memory inputs remain
                # untouched so an idempotent retry has no new side effects.
                await asyncio.to_thread(
                    self._persistence.save_runtime_status,
                    request,
                    "error" if existing_status == "error" else "idle",
                )
                await self._settlement.record_ai_run_elapsed(
                    run_user_message,
                    existing_turn.reply,
                    run_started_at=None,
                )
                started_payload = conversation_run_started_payload(run_user_message)
                if started_payload is not None:
                    yield {**started_payload, "run_id": request.run_id or f"run_{run_user_message.message_id}"}
                settled_payload = conversation_run_settled_payload(
                    run_user_message,
                    existing_turn.reply,
                    status=existing_status,
                )
                if settled_payload is not None:
                    yield settled_payload
                yield {"kind": "done", "finish_reason": "replayed"}
                return
            await asyncio.to_thread(self._persistence.sync_session_metadata, request)
            request = await self._prepare_image_references(request)
            user_message = None
            if existing_turn is not None:
                run_user_message = existing_turn.user
            else:
                user_message = await asyncio.to_thread(self._persistence.append_user_message, request)
                run_user_message = user_message or await asyncio.to_thread(
                    self._persistence.current_user_message,
                    request,
                )
            if run_user_message is not None:
                request = replace(
                    request,
                    run_id=request.run_id or f"run_{run_user_message.message_id}",
                    user_message_id=run_user_message.message_id,
                )
            existing_run = await asyncio.to_thread(
                self._persistence.run_outcome,
                request,
            )
            if existing_run is not None and existing_run.status in {"error", "cancelled"}:
                started_payload = conversation_run_started_payload(run_user_message)
                if started_payload is not None:
                    yield {**started_payload, "run_id": request.run_id or f"run_{run_user_message.message_id}"}
                settled_payload = conversation_run_settled_payload(
                    run_user_message,
                    None,
                    status=existing_run.status,
                )
                if settled_payload is not None:
                    yield settled_payload
                if existing_run.status == "error":
                    yield {
                        "kind": "error",
                        "error": existing_run.error_message or existing_run.error_code or "",
                        "error_code": existing_run.error_code or "upstream_response_failed",
                    }
                else:
                    yield {"kind": "done", "finish_reason": "cancelled"}
                return
            await asyncio.to_thread(
                self._persistence.begin_run,
                request,
                run_user_message,
            )
            memory_session_snapshot = await asyncio.to_thread(
                self._persistence.session_snapshot,
                request,
            )
            memory_compression_blocking = (
                await self._persistence.memory_compression_is_blocking()
            )
            await asyncio.to_thread(
                self._persistence.prepare_long_term_memory_delivery,
                request,
                run_user_message,
            )
            await asyncio.to_thread(self._persistence.save_runtime_status, request, "running")
            started_payload = conversation_run_started_payload(run_user_message)
            if started_payload is not None:
                yield {**started_payload, "run_id": request.run_id or f"run_{run_user_message.message_id}"}
            session_request = await asyncio.to_thread(
                self._context_builder.rebuild_session_request_messages,
                request,
                drop_matching_last_user=True,
            )
            session_request = await self._prepare_image_references(session_request)
            compressed_request = await asyncio.to_thread(
                self._context_builder.replace_session_compressed_history,
                session_request,
            )
            memory_request = await asyncio.to_thread(
                self._context_builder.inject_session_long_term_memory,
                compressed_request,
            )
            stream_request = replace(
                await asyncio.to_thread(self._context_builder.inject_session_tools, memory_request),
                record_usage=False,
            )
            if memory_compression_blocking:
                await self._persistence.run_memory_request_check(
                    request,
                    stream_request,
                    session_snapshot=memory_session_snapshot,
                )
                session_request = await asyncio.to_thread(
                    self._context_builder.rebuild_session_request_messages,
                    request,
                    drop_matching_last_user=True,
                )
                session_request = await self._prepare_image_references(session_request)
                compressed_request = await asyncio.to_thread(
                    self._context_builder.replace_session_compressed_history,
                    session_request,
                )
                memory_request = await asyncio.to_thread(
                    self._context_builder.inject_session_long_term_memory,
                    compressed_request,
                )
                stream_request = replace(
                    await asyncio.to_thread(
                        self._context_builder.inject_session_tools,
                        memory_request,
                    ),
                    record_usage=False,
                )
            else:
                request_check = self._persistence.schedule_memory_request_check(
                    request,
                    stream_request,
                    session_snapshot=memory_session_snapshot,
                )
                if request_check is not None:
                    background_tasks.append(request_check)
            await self._persistence.run_long_term_memory_request_check(
                request,
                stream_request,
                session_snapshot=memory_session_snapshot,
            )
            request_check = (
                self._persistence.schedule_long_term_memory_request_check(
                    request,
                    stream_request,
                    session_snapshot=memory_session_snapshot,
                )
            )
            if request_check is not None:
                background_tasks.append(request_check)
            model_events = self._stream_chat_events(
                request,
                stream_request,
                on_model_request=capture_model_request,
                on_model_round_completed=schedule_completed_model_round,
                on_tool_call_cancelled=capture_cancelled_tool_call,
                prepare_model_request=prepare_next_tool_loop_model_request,
            )
            notification_events = conversation_notifications.with_notifications(request.project_id, request.session_id, model_events)
            async with aclosing(notification_events):
                async for event in notification_events:
                    if isinstance(event, ProjectConversationMessage):
                        yield {"kind": "conversation_notice", "message": _output_limit_message_payload(event)}
                        continue
                    if isinstance(event, ConversationPersistenceCheckpoint):
                        if include_persistence_checkpoints:
                            yield persistence_checkpoint_payload(event)
                        continue
                    now = monotonic()
                    if now - last_heartbeat >= _STREAM_HEARTBEAT_SECONDS:
                        await asyncio.to_thread(self._persistence.save_runtime_status, request, "running")
                        last_heartbeat = now

                    if event.kind == ChatStreamEventKind.MODEL_RESPONSE_STARTED:
                        await conversation_notifications.start_response(request.project_id, request.session_id)
                        yield stream_event_to_payload(event)
                        continue
                    if event.kind == ChatStreamEventKind.MODEL_RESPONSE_FINISHED:
                        if event.error_code == "upstream_output_limit":
                            # A retained partial response is a real history row.
                            # Persist it before draining notices at this boundary.
                            final_response_boundary = event
                            continue
                        if event.has_tool_calls or event.error_code:
                            notices = await conversation_notifications.finish_response(request.project_id, request.session_id)
                            yield {**stream_event_to_payload(event), "notifications": [_output_limit_message_payload(item) for item in notices]}
                        else:
                            final_response_boundary = event
                        continue
                    if event.kind == ChatStreamEventKind.PROTOCOL_CONTINUATION:
                        continue

                    if event.kind == ChatStreamEventKind.OUTPUT_LIMIT:
                        policy = last_model_request or request
                        partial = event.partial_message
                        saved_message = None
                        if policy.output_limit_save_partial and partial is not None:
                            saved_message = await asyncio.to_thread(
                                self._persistence.append_assistant_message,
                                request, content=partial.content,
                                thinking_content=partial.thinking_content,
                                usage=usage_to_payload(event.usage) if event.usage else None,
                                context_tokens=event.usage.prompt_tokens if event.usage else None,
                                status="done", finish_reason="output_limit",
                                include_in_context=(policy.output_limit_action != "retry" and bool(partial.content.strip())),
                            )
                        answer_parts.clear()
                        thinking_parts.clear()
                        usage = None
                        usage_payload = None
                        if final_response_boundary is not None:
                            notices = await conversation_notifications.finish_response(request.project_id, request.session_id)
                            yield {**stream_event_to_payload(final_response_boundary), "notifications": [_output_limit_message_payload(item) for item in notices]}
                            final_response_boundary = None
                        next_user_message = None
                        if event.will_recover and event.recovery_action == "send_message":
                            automatic_message = ChatMessage(
                                role=ChatMessageRole.USER,
                                content=OUTPUT_LIMIT_MESSAGE_PREFIX + policy.output_limit_message,
                                message_id=f"msg_{uuid4().hex[:16]}",
                                internal_metadata={
                                    "message_source": "output_limit",
                                    "continuation_of": run_user_message.message_id if run_user_message else None,
                                },
                            )
                            automatic_request = replace(request, messages=(automatic_message,))
                            append_task = asyncio.create_task(asyncio.to_thread(
                                self._persistence.append_user_message, automatic_request,
                            ))
                            try:
                                next_user_message = await asyncio.shield(append_task)
                            except asyncio.CancelledError:
                                # The database write cannot be cancelled once the thread starts.
                                # Wait for its identity, then durably cancel it without starting a model request.
                                pending = await append_task
                                if pending is not None:
                                    cancelled_request = _output_limit_continuation_request(
                                        request, _output_limit_message_payload(pending),
                                    )
                                    await asyncio.to_thread(self._persistence.begin_run, cancelled_request, pending)
                                    await asyncio.to_thread(self._persistence.settle_run, cancelled_request, status="cancelled")
                                raise
                        yield {
                            "kind": "output_limit",
                            "action": event.recovery_action,
                            "will_recover": event.will_recover,
                            "saved_message": _output_limit_message_payload(saved_message),
                            "next_user_message": _output_limit_message_payload(next_user_message),
                            "usage": usage_to_payload(event.usage) if event.usage else None,
                        }
                        checkpoint_message = next_user_message or saved_message
                        if include_persistence_checkpoints and checkpoint_message is not None:
                            yield persistence_checkpoint_payload(ConversationPersistenceCheckpoint(checkpoint_message.message_id))
                        if event.will_recover and event.recovery_action == "retry":
                            continue
                        _, settled_payload = await self._settlement.settle_failed(
                            request, run_user_message, run_started_at=run_started_at,
                            assistant_message=saved_message,
                            content=event.error or "上游生成达到最大输出长度，回复未完成。",
                            error_code="upstream_output_limit",
                            attempt_count=event.attempt_index or 1,
                            usage=event.usage, usage_payload=None,
                            context_tokens=event.usage.prompt_tokens if event.usage else None,
                            context_tokens_estimated=False,
                            keep_running=event.will_recover and event.recovery_action == "send_message",
                        )
                        if settled_payload is not None:
                            yield settled_payload
                        if not event.will_recover:
                            yield {
                                "kind": "error",
                                "error": event.error or "上游生成达到最大输出长度，回复未完成。",
                                "error_code": "upstream_output_limit",
                                "attempt_index": event.attempt_index or 1,
                                "attempt_count": event.attempt_count or 1,
                            }
                        return

                    if event.kind == ChatStreamEventKind.RETRY_RESET:
                        upstream_attempt_index = max(
                            upstream_attempt_index,
                            event.attempt_index or upstream_attempt_index,
                        )
                        request = replace(
                            request,
                            upstream_attempt_index=upstream_attempt_index,
                        )
                        answer_parts.clear()
                        thinking_parts.clear()
                        yield stream_event_to_payload(
                            event,
                            usage_payload=usage_payload,
                            context_tokens=context_tokens,
                            context_tokens_estimated=context_tokens_estimated,
                        )
                        continue

                    if event.kind == ChatStreamEventKind.ERROR:
                        error = event.error or "上游供应商返回错误。"
                        failed_message, settled_payload = await self._settlement.settle_failed(
                            request,
                            run_user_message,
                            run_started_at=run_started_at,
                            content=error,
                            error_code=event.error_code or "upstream_response_failed",
                            attempt_count=upstream_attempt_index,
                            usage=usage,
                            usage_payload=usage_payload,
                            context_tokens=context_tokens,
                            context_tokens_estimated=context_tokens_estimated,
                        )
                        if last_model_request is not None and failed_message is not None:
                            schedule_model_exchange(
                                last_model_request,
                                failed_message,
                                round_index=model_round_serial,
                                round_usage=usage,
                            )
                        if settled_payload is not None:
                            yield settled_payload
                        yield {
                            "kind": "error",
                            "error": error,
                            "error_code": event.error_code or "upstream_response_failed",
                            "attempt_index": upstream_attempt_index,
                            "attempt_count": max(
                                upstream_attempt_index,
                                request.upstream_attempt_count,
                            ),
                        }
                        return
                    if event.kind == ChatStreamEventKind.DELTA and event.content:
                        answer_parts.append(event.content)
                    if event.kind == ChatStreamEventKind.THINKING_DELTA and event.content:
                        thinking_parts.append(event.content)
                    if event.kind == ChatStreamEventKind.USAGE and event.usage:
                        if event.usage.prompt_tokens is not None:
                            context_tokens = event.usage.prompt_tokens
                            context_tokens_estimated = (
                                "prompt_tokens" in event.usage.estimated_fields
                            )
                        usage = merge_usage(usage, event.usage)
                        usage_payload = usage_to_payload(usage)
                    if event.kind == ChatStreamEventKind.TOOL_RESULT:
                        answer_parts.clear()
                        thinking_parts.clear()
                    if event.kind == ChatStreamEventKind.DONE:
                        done_payload = stream_event_to_payload(
                            event,
                            usage_payload=usage_payload,
                            context_tokens=context_tokens,
                            context_tokens_estimated=context_tokens_estimated,
                        )
                        continue

                    yield stream_event_to_payload(
                        event,
                        usage_payload=usage_payload,
                        context_tokens=context_tokens,
                        context_tokens_estimated=context_tokens_estimated,
                    )

            if await self._discard_removed_conversation(request):
                await self._settlement.record_ai_run_elapsed(
                    run_user_message,
                    None,
                    run_started_at=run_started_at,
                )
                return
            assistant_message = await asyncio.to_thread(
                self._persistence.append_assistant_message,
                request,
                content="".join(answer_parts),
                thinking_content="".join(thinking_parts),
                content_parts=tuple(assistant_content_parts),
                usage=usage_payload,
                context_tokens=context_tokens,
                context_tokens_estimated=context_tokens_estimated,
                status="done",
                sync_session_model=False,
            )
            final_assistant_message = assistant_message
            if final_response_boundary is not None:
                notices = await conversation_notifications.finish_response(request.project_id, request.session_id)
                yield {**stream_event_to_payload(final_response_boundary), "notifications": [_output_limit_message_payload(item) for item in notices]}
            if assistant_message is None:
                empty_response_error = "模型未返回可持久化的回复内容。"
                final_assistant_message, settled_payload = await self._settlement.settle_failed(
                    request,
                    run_user_message,
                    run_started_at=run_started_at,
                    content=empty_response_error,
                    error_code="empty_model_response",
                    attempt_count=upstream_attempt_index,
                    usage=usage,
                    usage_payload=usage_payload,
                    context_tokens=context_tokens,
                    context_tokens_estimated=context_tokens_estimated,
                )
                if settled_payload is not None:
                    yield settled_payload
                if last_model_request is not None and final_assistant_message is not None:
                    schedule_model_exchange(
                        last_model_request,
                        final_assistant_message,
                        round_index=model_round_serial,
                        round_usage=usage,
                    )
                yield {
                    "kind": "error",
                    "error": empty_response_error,
                    "error_code": "empty_model_response",
                }
                return
            await self._settlement.record_ai_run_elapsed(
                run_user_message,
                assistant_message,
                run_started_at=run_started_at,
            )
            await self._settlement.record_assistant_usage_best_effort(
                request,
                assistant_message,
                usage,
            )
            if last_model_request is not None:
                schedule_model_exchange(
                    last_model_request,
                    assistant_message,
                    round_index=model_round_serial,
                    round_usage=usage,
                )
            if include_persistence_checkpoints and assistant_message is not None:
                yield persistence_checkpoint_payload(
                    ConversationPersistenceCheckpoint(assistant_message.message_id),
                )
            run_snapshot = build_conversation_run_snapshot(
                last_model_request,
                assistant_message,
            )
            naming_task = self._persistence.schedule_session_naming(
                request,
                assistant_message,
                run_snapshot=run_snapshot,
            )
            if naming_task is not None:
                background_tasks.append(naming_task)
            if memory_compression_blocking:
                await self._persistence.run_memory_compression(
                    request,
                    assistant_message,
                    session_snapshot=memory_session_snapshot,
                    run_snapshot=run_snapshot,
                )
            else:
                compression_task = self._persistence.schedule_memory_compression(
                    request,
                    assistant_message,
                    session_snapshot=memory_session_snapshot,
                    run_snapshot=run_snapshot,
                )
                if compression_task is not None:
                    background_tasks.append(compression_task)
            await self._persistence.run_long_term_memory_management(
                request,
                assistant_message,
                session_snapshot=memory_session_snapshot,
                run_snapshot=run_snapshot,
            )
            memory_task = (
                self._persistence.schedule_long_term_memory_management(
                    request,
                    assistant_message,
                    session_snapshot=memory_session_snapshot,
                    run_snapshot=run_snapshot,
                )
            )
            if memory_task is not None:
                background_tasks.append(memory_task)
            if await_background_tasks and background_tasks:
                await asyncio.gather(*background_tasks, return_exceptions=True)
            await asyncio.to_thread(self._persistence.save_runtime_status, request, "idle")
            await asyncio.to_thread(
                self._persistence.settle_run,
                request,
                status="done",
                attempt_count=upstream_attempt_index,
            )
            settled_payload = conversation_run_settled_payload(
                run_user_message,
                assistant_message,
                status="done",
            )
            if settled_payload is not None:
                yield settled_payload
            if done_payload is not None:
                yield done_payload
        except asyncio.CancelledError:
            final_assistant_message, settled_payload = (
                await self._settlement.settle_interrupted(
                    request,
                    run_user_message,
                    run_started_at=run_started_at,
                    assistant_message=final_assistant_message,
                    last_model_request=last_model_request,
                    current_round_already_persisted=(
                        persisted_tool_call_round_serial == model_round_serial
                    ),
                    persisted_tool_call_message_id=persisted_tool_call_message_id,
                    cancelled_tool_scopes=cancelled_tool_scopes,
                    usage=usage,
                    answer_parts=answer_parts,
                    thinking_parts=thinking_parts,
                    content_parts=assistant_content_parts,
                    usage_payload=usage_payload,
                    context_tokens=context_tokens,
                    context_tokens_estimated=context_tokens_estimated,
                )
            )
            if settled_payload is not None:
                yield settled_payload
            raise
        except GeneratorExit:
            # A closed async generator cannot legally yield another event, but it
            # must use the exact same durable settlement as an explicit cancel.
            final_assistant_message, _ = await self._settlement.settle_interrupted(
                request,
                run_user_message,
                run_started_at=run_started_at,
                assistant_message=final_assistant_message,
                last_model_request=last_model_request,
                current_round_already_persisted=(
                    persisted_tool_call_round_serial == model_round_serial
                ),
                persisted_tool_call_message_id=persisted_tool_call_message_id,
                cancelled_tool_scopes=cancelled_tool_scopes,
                usage=usage,
                answer_parts=answer_parts,
                thinking_parts=thinking_parts,
                content_parts=assistant_content_parts,
                usage_payload=usage_payload,
                context_tokens=context_tokens,
                context_tokens_estimated=context_tokens_estimated,
            )
            raise
        except httpx.HTTPStatusError as exc:
            if await self._discard_removed_conversation(request):
                await self._settlement.record_ai_run_elapsed(
                    run_user_message,
                    None,
                    run_started_at=run_started_at,
                )
                return
            error = upstream_http_error_message(exc)
            failed_message, settled_payload = await self._settlement.settle_failed(
                request,
                run_user_message,
                run_started_at=run_started_at,
                content=error,
                error_code="upstream_http_error",
                attempt_count=upstream_attempt_index,
                usage=usage,
                usage_payload=usage_payload,
                context_tokens=context_tokens,
                context_tokens_estimated=context_tokens_estimated,
            )
            if last_model_request is not None and failed_message is not None:
                schedule_model_exchange(
                    last_model_request,
                    failed_message,
                    round_index=model_round_serial,
                    round_usage=usage,
                )
            if settled_payload is not None:
                yield settled_payload
            yield {
                "kind": "error",
                "error": error,
                "error_code": "upstream_http_error",
            }
        except httpx.RequestError as exc:
            if await self._discard_removed_conversation(request):
                await self._settlement.record_ai_run_elapsed(
                    run_user_message,
                    None,
                    run_started_at=run_started_at,
                )
                return
            error = local_exception_message(exc)
            failed_message, settled_payload = await self._settlement.settle_failed(
                request,
                run_user_message,
                run_started_at=run_started_at,
                content=error,
                error_code="upstream_connection_error",
                attempt_count=upstream_attempt_index,
                usage=usage,
                usage_payload=usage_payload,
                context_tokens=context_tokens,
                context_tokens_estimated=context_tokens_estimated,
            )
            if last_model_request is not None and failed_message is not None:
                schedule_model_exchange(
                    last_model_request,
                    failed_message,
                    round_index=model_round_serial,
                    round_usage=usage,
                )
            if settled_payload is not None:
                yield settled_payload
            yield {
                "kind": "error",
                "error": error,
                "error_code": "upstream_connection_error",
            }
        except AppError as exc:
            if await self._discard_removed_conversation(request):
                await self._settlement.record_ai_run_elapsed(
                    run_user_message,
                    None,
                    run_started_at=run_started_at,
                )
                return
            failed_message, settled_payload = await self._settlement.settle_failed(
                request,
                run_user_message,
                run_started_at=run_started_at,
                content=exc.message,
                error_code=exc.code,
                attempt_count=upstream_attempt_index,
                usage=usage,
                usage_payload=usage_payload,
                context_tokens=context_tokens,
                context_tokens_estimated=context_tokens_estimated,
            )
            if last_model_request is not None and failed_message is not None:
                schedule_model_exchange(
                    last_model_request,
                    failed_message,
                    round_index=model_round_serial,
                    round_usage=usage,
                )
            if settled_payload is not None:
                yield settled_payload
            yield {"kind": "error", "error": exc.message, "error_code": exc.code}
        except Exception:
            logger.exception("Conversation generation failed unexpectedly.")
            if final_assistant_message is not None:
                await asyncio.to_thread(self._persistence.save_runtime_status, request, "idle")
                await asyncio.to_thread(
                    self._persistence.settle_run,
                    request,
                    status="done",
                    attempt_count=upstream_attempt_index,
                )
                await self._settlement.record_ai_run_elapsed(
                    run_user_message,
                    final_assistant_message,
                    run_started_at=run_started_at,
                )
                settled_payload = conversation_run_settled_payload(
                    run_user_message,
                    final_assistant_message,
                    status="done",
                )
            else:
                failed_message, settled_payload = await self._settlement.settle_failed(
                    request,
                    run_user_message,
                    run_started_at=run_started_at,
                    content="会话生成任务异常终止。",
                    error_code="conversation_generation_failed",
                    attempt_count=upstream_attempt_index,
                    usage=usage,
                    usage_payload=usage_payload,
                    context_tokens=context_tokens,
                    context_tokens_estimated=context_tokens_estimated,
                )
                if last_model_request is not None and failed_message is not None:
                    schedule_model_exchange(
                        last_model_request,
                        failed_message,
                        round_index=model_round_serial,
                        round_usage=usage,
                    )
            if settled_payload is not None:
                yield settled_payload
            raise
        else:
            if (
                not "".join(answer_parts).strip()
                and not "".join(thinking_parts).strip()
                and not assistant_content_parts
            ):
                await asyncio.to_thread(self._persistence.save_runtime_status, request, "idle")

    async def _discard_removed_conversation(self, request: ChatCompletionRequest) -> bool:
        if not request.project_id or not request.session_id:
            return False
        exists = await asyncio.to_thread(self._persistence.conversation_target_exists, request)
        if exists:
            return False
        await self._background_task_registry.cancel_session(
            request.project_id,
            request.session_id,
        )
        return True

    async def _stream_chat_events(
        self,
        original_request: ChatCompletionRequest,
        stream_request: ChatCompletionRequest,
        *,
        on_model_request: Callable[[ChatCompletionRequest], None] | None = None,
        on_model_round_completed: Callable[
            [ChatCompletionRequest, ProjectConversationMessage, ChatUsage | None],
            Awaitable[None],
        ]
        | None = None,
        on_tool_call_cancelled: Callable[
            [ChatToolCall, ToolCancellationScope],
            None,
        ]
        | None = None,
        prepare_model_request: Callable[
            [ChatCompletionRequest],
            Awaitable[ChatCompletionRequest],
        ]
        | None = None,
    ) -> AsyncGenerator[ChatStreamEvent | ConversationPersistenceCheckpoint, None]:
        if self._tool_loop.should_run(stream_request):
            tool_events = self._tool_loop.stream_events(
                original_request,
                stream_request,
                prepare_model_request=(
                    prepare_model_request or self._refresh_tool_loop_memory_context
                ),
                before_model_request=self._write_request_snapshot,
                resolve_model_request=self._resolve_model_request,
                on_model_request=on_model_request,
                on_model_round_completed=on_model_round_completed,
                on_tool_call_cancelled=on_tool_call_cancelled,
            )
            async with aclosing(tool_events):
                async for event in tool_events:
                    yield event
            return

        await self._write_request_snapshot(stream_request)
        resolved_request = await self._resolve_model_request(stream_request)
        if on_model_request is not None:
            on_model_request(resolved_request)
        async with aclosing(self._chat_service.stream(resolved_request)) as events:
            async for event in events:
                yield event

    async def _write_request_snapshot(self, request: ChatCompletionRequest) -> None:
        await asyncio.to_thread(self._context_builder.write_injection_preview, request)

    async def _refresh_tool_loop_memory_context(
        self,
        request: ChatCompletionRequest,
    ) -> ChatCompletionRequest:
        return await asyncio.to_thread(
            self._context_builder.replace_session_compressed_history,
            request,
        )

    async def _resolve_model_request(self, request: ChatCompletionRequest) -> ChatCompletionRequest:
        if self._image_reference_resolver is None:
            return request
        prepared_request = await self._prepare_image_references(request)
        return await asyncio.to_thread(self._image_reference_resolver.resolve, prepared_request)

    async def _prepare_image_references(self, request: ChatCompletionRequest) -> ChatCompletionRequest:
        if self._image_reference_resolver is None:
            return request
        return await asyncio.to_thread(self._image_reference_resolver.prepare, request)

    async def _run_functional_conversation(
        self,
        request: ChatCompletionRequest,
    ) -> None:
        subscription = await self._run_manager.start(request, self)
        error: str | None = None
        error_code: str | None = None
        async for payload in self._run_manager.stream(subscription):
            if payload.get("kind") == "error":
                value = payload.get("error")
                error = value if isinstance(value, str) else "功能会话执行失败。"
                code = payload.get("error_code")
                error_code = code if isinstance(code, str) else None
        if error:
            raise FunctionalConversationRunError(error, code=error_code)

@lru_cache
def get_project_conversation_stream_service() -> ProjectConversationStreamService:
    return ProjectConversationStreamService(
        get_chat_completion_service(),
        get_project_conversation_service(),
        get_llm_usage_service(),
        get_project_conversation_naming_service(),
        get_project_conversation_memory_service(),
        get_chat_tool_injection_service(),
        get_tool_execution_service(),
        get_tool_result_guidance_service(),
        get_project_service(),
        get_tool_call_record_service(),
        get_conversation_image_reference_resolver(),
        get_client_tool_bridge_service(),
        runtime_capabilities_service=get_llm_runtime_capabilities_service(),
        run_manager=get_conversation_run_manager(),
        long_term_memory_service=(
            get_project_conversation_long_term_memory_service()
        ),
    )


def _output_limit_message_payload(message: ProjectConversationMessage | None) -> dict | None:
    if message is None:
        return None
    return {
        "message_id": message.message_id, "session_id": message.session_id,
        "role": message.role, "content": message.content, "name": message.name,
        "thinking_content": message.thinking_content, "usage": message.usage,
        "provider_id": message.provider_id, "model_id": message.model_id,
        "target_provider_id": message.target_provider_id,
        "target_model_id": message.target_model_id,
        "status": message.status, "created_at": message.created_at,
        "updated_at": message.updated_at,
        "origin_message_id": message.origin_message_id or message.message_id,
        "finish_reason": message.finish_reason,
        "include_in_context": message.include_in_context,
        "message_source": message.message_source,
        "continuation_of": message.continuation_of,
    }


def _output_limit_continuation_request(request: ChatCompletionRequest, message: dict) -> ChatCompletionRequest:
    return replace(
        request, run_id="run_" + message["message_id"], user_message_id=message["message_id"],
        messages=(ChatMessage(
            role=ChatMessageRole.USER, content=message["content"], message_id=message["message_id"],
            internal_metadata={"message_source": "output_limit", "continuation_of": message.get("continuation_of")},
        ),),
    )
