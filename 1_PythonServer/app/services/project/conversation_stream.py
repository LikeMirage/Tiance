import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import replace
from functools import lru_cache
from time import monotonic
from typing import Any

import httpx

from app.core.errors import AppError, normalize_upstream_http_error
from app.domain.llm.chat import (
    ChatCompletionRequest,
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
from app.services.project.conversation_stream_persistence import ConversationStreamPersistence
from app.services.project.conversation_stream_settlement import ConversationStreamSettlement
from app.services.project.conversation_stream_events import stream_event_to_payload
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
        answer_parts: list[str] = []
        thinking_parts: list[str] = []
        assistant_content_parts: list[ChatMessageContentPart] = []
        usage_payload: dict[str, object] | None = None
        usage: ChatUsage | None = None
        context_tokens: int | None = None
        context_tokens_estimated = False
        done_payload: dict[str, object | None] | None = None
        background_tasks: list[asyncio.Task] = []
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

        def capture_model_request(model_request: ChatCompletionRequest) -> None:
            nonlocal usage, usage_payload
            nonlocal context_tokens, context_tokens_estimated, last_model_request
            nonlocal model_round_serial
            last_model_request = model_request
            model_round_serial += 1
            usage = None
            usage_payload = None
            context_tokens = None
            context_tokens_estimated = False

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
            usage = None
            usage_payload = None
            context_tokens = None
            context_tokens_estimated = False
            run_snapshot = build_conversation_run_snapshot(
                model_request,
                assistant_message,
            )
            if memory_compression_blocking:
                await self._persistence.run_memory_compression(
                    request,
                    assistant_message,
                    session_snapshot=memory_session_snapshot,
                    run_snapshot=run_snapshot,
                )
            else:
                task = self._persistence.schedule_memory_compression(
                    request,
                    assistant_message,
                    session_snapshot=memory_session_snapshot,
                    run_snapshot=run_snapshot,
                )
                if task is not None:
                    background_tasks.append(task)

            await self._persistence.run_long_term_memory_management(
                request,
                assistant_message,
                session_snapshot=memory_session_snapshot,
                run_snapshot=run_snapshot,
            )
            task = self._persistence.schedule_long_term_memory_management(
                request,
                assistant_message,
                session_snapshot=memory_session_snapshot,
                run_snapshot=run_snapshot,
            )
            if task is not None:
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
                    if existing_turn.reply.role == "error" or existing_turn.reply.status == "error"
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
                    yield started_payload
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
                yield started_payload
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
            async for event in self._stream_chat_events(
                request,
                stream_request,
                on_model_request=capture_model_request,
                on_model_round_completed=schedule_completed_model_round,
                on_tool_call_cancelled=capture_cancelled_tool_call,
            ):
                if isinstance(event, ConversationPersistenceCheckpoint):
                    if include_persistence_checkpoints:
                        yield persistence_checkpoint_payload(event)
                    continue
                now = monotonic()
                if now - last_heartbeat >= _STREAM_HEARTBEAT_SECONDS:
                    await asyncio.to_thread(self._persistence.save_runtime_status, request, "running")
                    last_heartbeat = now

                if event.kind == ChatStreamEventKind.PROTOCOL_CONTINUATION:
                    continue

                if event.kind == ChatStreamEventKind.ERROR:
                    error = event.error or "上游供应商返回错误。"
                    _, settled_payload = await self._settlement.settle_failed(
                        request,
                        run_user_message,
                        run_started_at=run_started_at,
                        content=error,
                        usage=usage,
                        usage_payload=usage_payload,
                        context_tokens=context_tokens,
                        context_tokens_estimated=context_tokens_estimated,
                    )
                    if settled_payload is not None:
                        yield settled_payload
                    yield {
                        "kind": "error",
                        "error": error,
                        "error_code": event.error_code or "upstream_response_failed",
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
            if assistant_message is None:
                empty_response_error = "模型未返回可持久化的回复内容。"
                final_assistant_message, settled_payload = await self._settlement.settle_failed(
                    request,
                    run_user_message,
                    run_started_at=run_started_at,
                    content=empty_response_error,
                    usage=usage,
                    usage_payload=usage_payload,
                    context_tokens=context_tokens,
                    context_tokens_estimated=context_tokens_estimated,
                )
                if settled_payload is not None:
                    yield settled_payload
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
            upstream_error = normalize_upstream_http_error(exc)
            _, settled_payload = await self._settlement.settle_failed(
                request,
                run_user_message,
                run_started_at=run_started_at,
                content=upstream_error.message,
                usage=usage,
                usage_payload=usage_payload,
                context_tokens=context_tokens,
                context_tokens_estimated=context_tokens_estimated,
            )
            if settled_payload is not None:
                yield settled_payload
            yield {
                "kind": "error",
                "error": upstream_error.message,
                "error_code": upstream_error.code,
            }
        except httpx.RequestError as exc:
            if await self._discard_removed_conversation(request):
                await self._settlement.record_ai_run_elapsed(
                    run_user_message,
                    None,
                    run_started_at=run_started_at,
                )
                return
            error = f"上游供应商连接失败：{exc}"
            _, settled_payload = await self._settlement.settle_failed(
                request,
                run_user_message,
                run_started_at=run_started_at,
                content=error,
                usage=usage,
                usage_payload=usage_payload,
                context_tokens=context_tokens,
                context_tokens_estimated=context_tokens_estimated,
            )
            if settled_payload is not None:
                yield settled_payload
            yield {"kind": "error", "error": error}
        except AppError as exc:
            if await self._discard_removed_conversation(request):
                await self._settlement.record_ai_run_elapsed(
                    run_user_message,
                    None,
                    run_started_at=run_started_at,
                )
                return
            _, settled_payload = await self._settlement.settle_failed(
                request,
                run_user_message,
                run_started_at=run_started_at,
                content=exc.message,
                usage=usage,
                usage_payload=usage_payload,
                context_tokens=context_tokens,
                context_tokens_estimated=context_tokens_estimated,
            )
            if settled_payload is not None:
                yield settled_payload
            yield {"kind": "error", "error": exc.message, "error_code": exc.code}
        except Exception:
            logger.exception("Conversation generation failed unexpectedly.")
            if final_assistant_message is not None:
                await asyncio.to_thread(self._persistence.save_runtime_status, request, "idle")
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
                _, settled_payload = await self._settlement.settle_failed(
                    request,
                    run_user_message,
                    run_started_at=run_started_at,
                    content="会话生成任务异常终止。",
                    usage=usage,
                    usage_payload=usage_payload,
                    context_tokens=context_tokens,
                    context_tokens_estimated=context_tokens_estimated,
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
    ) -> AsyncGenerator[ChatStreamEvent | ConversationPersistenceCheckpoint, None]:
        if self._tool_loop.should_run(stream_request):
            async for event in self._tool_loop.stream_events(
                original_request,
                stream_request,
                prepare_model_request=self._refresh_tool_loop_memory_context,
                before_model_request=self._write_request_snapshot,
                resolve_model_request=self._resolve_model_request,
                on_model_request=on_model_request,
                on_model_round_completed=on_model_round_completed,
                on_tool_call_cancelled=on_tool_call_cancelled,
            ):
                yield event
            return

        await self._write_request_snapshot(stream_request)
        resolved_request = await self._resolve_model_request(stream_request)
        if on_model_request is not None:
            on_model_request(resolved_request)
        async for event in self._chat_service.stream(resolved_request):
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
