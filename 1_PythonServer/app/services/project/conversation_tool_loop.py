import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import replace
from time import monotonic
from typing import Protocol

from app.core.errors import AppError
from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatMessage,
    ChatMessageRole,
    ChatProtocolContinuation,
    ChatStreamEvent,
    ChatStreamEventKind,
    ChatToolCall,
    ChatToolResult,
    ChatUsage,
)
from app.domain.project.project_conversation import ProjectConversationMessage
from app.domain.llm.runtime_capabilities import LlmRuntimeCapabilities
from app.services.llm.chat.service import ChatCompletionService
from app.services.project.conversation_stream_checkpoints import (
    ConversationPersistenceCheckpoint,
)
from app.services.project.conversation_stream_events import (
    tool_call_failure_result,
    tool_result_message_content,
)
from app.services.project.conversation_request_provenance import tag_conversation_message
from app.services.project.conversation_stream_usage import merge_usage, usage_to_payload
from app.services.project.project_conversations import ProjectConversationService
from app.services.project.projects import ProjectService
from app.services.project.conversation_attachments import ConversationAttachmentService
from app.services.project.conversation_audit import ConversationAuditService
from app.services.tools.client_tool_bridge import (
    ClientToolBridgeService,
    ClientToolResultPayload,
    client_tool_result_to_chat_tool_result,
)
from app.services.tools.dynamic_tool_contract import (
    DYNAMIC_TOOL_EXECUTOR_NAME,
    DYNAMIC_TOOL_INFRASTRUCTURE_NAMES,
)
from app.services.tools.tool_call_records import ToolCallRecordService
from app.services.tools.tool_cancellation import ToolCancellationScope
from app.services.tools.tool_execution import (
    PreparedClientToolExecution,
    ToolExecutionContext,
    ToolExecutionService,
)
from app.services.project.conversation_tool_call_recovery import (
    INVALID_TOOL_ARGUMENTS,
    prepare_tool_calls_for_replay,
)
from app.services.tools.tool_metadata import normalize_tool_name
from app.services.tools.tool_execution_runtime import ToolExecutionCancellation
from app.services.tools.tool_result_guidance import ToolResultGuidanceService
from app.services.tools.tool_result_content import (
    image_parts_from_tool_content,
    tool_resource_message,
)

_DEFAULT_MAX_TOOL_CALLS = 99999
logger = logging.getLogger(__name__)


def _deduplicate_image_parts(parts):
    unique = []
    seen = set()
    for part in parts:
        if part.image_ref is None or part.image_ref.path in seen:
            continue
        seen.add(part.image_ref.path)
        unique.append(part)
    return tuple(unique)


class _RuntimeCapabilitiesProvider(Protocol):
    def get_capabilities(
        self,
        *,
        provider_id: str,
        model_id: str | None = None,
    ) -> LlmRuntimeCapabilities:
        ...


class ConversationToolLoop:
    def __init__(
        self,
        *,
        chat_service: ChatCompletionService,
        conversation_service: ProjectConversationService,
        tool_execution_service: ToolExecutionService | None,
        tool_result_guidance_service: ToolResultGuidanceService | None,
        project_service: ProjectService | None,
        tool_call_record_service: ToolCallRecordService | None,
        client_tool_bridge_service: ClientToolBridgeService | None,
        runtime_capabilities_service: _RuntimeCapabilitiesProvider | None = None,
        attachment_service: ConversationAttachmentService | None = None,
        audit_service: ConversationAuditService | None = None,
    ) -> None:
        self._chat_service = chat_service
        self._conversation_service = conversation_service
        self._tool_execution_service = tool_execution_service
        self._tool_result_guidance_service = tool_result_guidance_service
        self._project_service = project_service
        self._tool_call_record_service = tool_call_record_service
        self._client_tool_bridge_service = client_tool_bridge_service
        self._runtime_capabilities_service = runtime_capabilities_service
        self._attachment_service = attachment_service
        self._audit_service = audit_service

    def should_run(self, request: ChatCompletionRequest) -> bool:
        return bool(request.tools and self._tool_execution_service is not None)

    async def stream_events(
        self,
        original_request: ChatCompletionRequest,
        stream_request: ChatCompletionRequest,
        *,
        prepare_model_request: Callable[
            [ChatCompletionRequest],
            Awaitable[ChatCompletionRequest],
        ]
        | None = None,
        before_model_request: Callable[[ChatCompletionRequest], Awaitable[None]] | None = None,
        resolve_model_request: Callable[[ChatCompletionRequest], Awaitable[ChatCompletionRequest]] | None = None,
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
        current_request = stream_request
        max_tool_calls = _normalize_tool_call_limit(original_request.max_tool_calls)
        executed_tool_calls = 0
        while True:
            round_answer_parts: list[str] = []
            round_thinking_parts: list[str] = []
            round_tool_calls: list[ChatToolCall] = []
            round_protocol_continuation: ChatProtocolContinuation | None = None
            round_usage: ChatUsage | None = None
            round_context_tokens: int | None = None
            round_context_tokens_estimated = False

            if prepare_model_request is not None:
                current_request = await prepare_model_request(current_request)
            if before_model_request is not None:
                await before_model_request(current_request)
            model_request = (
                await resolve_model_request(current_request)
                if resolve_model_request is not None
                else current_request
            )
            if on_model_request is not None:
                on_model_request(model_request)
            async for event in self._chat_service.stream(model_request):
                if event.kind == ChatStreamEventKind.RETRY_RESET:
                    round_answer_parts.clear()
                    round_thinking_parts.clear()
                    round_tool_calls.clear()
                    round_protocol_continuation = None
                    round_usage = None
                    round_context_tokens = None
                    round_context_tokens_estimated = False
                    yield event
                    continue
                if event.kind == ChatStreamEventKind.DELTA and event.content:
                    round_answer_parts.append(event.content)
                    yield event
                    continue
                if event.kind == ChatStreamEventKind.THINKING_DELTA and event.content:
                    round_thinking_parts.append(event.content)
                    yield event
                    continue
                if event.kind == ChatStreamEventKind.TOOL_CALL_DELTA:
                    yield event
                    continue
                if event.kind == ChatStreamEventKind.TOOL_CALL and event.tool_call is not None:
                    round_tool_calls.append(event.tool_call)
                    continue
                if (
                    event.kind == ChatStreamEventKind.PROTOCOL_CONTINUATION
                    and event.protocol_continuation is not None
                ):
                    round_protocol_continuation = event.protocol_continuation
                    continue
                if event.kind == ChatStreamEventKind.USAGE and event.usage is not None:
                    round_usage = merge_usage(round_usage, event.usage)
                    if event.usage.prompt_tokens is not None:
                        round_context_tokens = event.usage.prompt_tokens
                        round_context_tokens_estimated = (
                            "prompt_tokens" in event.usage.estimated_fields
                        )
                if event.kind == ChatStreamEventKind.DONE and round_tool_calls:
                    continue
                yield event
                if event.kind == ChatStreamEventKind.ERROR:
                    return

            if not round_tool_calls:
                return
            if executed_tool_calls + len(round_tool_calls) > max_tool_calls:
                yield ChatStreamEvent(
                    kind=ChatStreamEventKind.ERROR,
                    error=f"工具调用次数过多，已停止本轮生成。（上限 {max_tool_calls} 次）",
                    error_code="tool_call_limit_exceeded",
                )
                return

            prepared_tool_calls = prepare_tool_calls_for_replay(
                tuple(round_tool_calls)
            )
            round_answer = "".join(round_answer_parts)
            round_thinking = "".join(round_thinking_parts)
            assistant_message = await asyncio.to_thread(
                self._append_assistant_tool_call_message,
                model_request,
                content=round_answer,
                thinking_content=round_thinking,
                tool_calls=prepared_tool_calls.replay_calls,
                protocol_continuation=round_protocol_continuation,
                usage=usage_to_payload(round_usage) if round_usage is not None else None,
                context_tokens=round_context_tokens,
                context_tokens_estimated=round_context_tokens_estimated,
            )
            if assistant_message is not None:
                if on_model_round_completed is not None:
                    await on_model_round_completed(
                        model_request,
                        assistant_message,
                        round_usage,
                    )
                yield ConversationPersistenceCheckpoint(assistant_message.message_id)
            next_messages = [
                *current_request.messages,
                tag_conversation_message(
                    ChatMessage(
                        role=ChatMessageRole.ASSISTANT,
                        content=round_answer,
                        tool_calls=prepared_tool_calls.replay_calls,
                        thinking_content=round_thinking,
                        protocol_continuation=round_protocol_continuation,
                    ),
                    assistant_message.message_id if assistant_message is not None else None,
                ),
            ]
            round_resource_parts = []
            for invalid_call, invalid_result in prepared_tool_calls.invalid_results:
                yield ChatStreamEvent(
                    kind=ChatStreamEventKind.TOOL_CALL,
                    tool_call=invalid_call,
                )
                await self._record_tool_event(
                    original_request,
                    invalid_call,
                    event_type="tool.failed",
                    payload={
                        "tool_name": invalid_call.name,
                        "ok": False,
                        "error_code": INVALID_TOOL_ARGUMENTS,
                    },
                )
                tool_message = await self._persist_tool_result(
                    original_request,
                    invalid_result,
                )
                yield ChatStreamEvent(
                    kind=ChatStreamEventKind.TOOL_RESULT,
                    tool_result=invalid_result,
                )
                if tool_message is not None:
                    yield ConversationPersistenceCheckpoint(tool_message.message_id)
                next_messages.append(
                    tag_conversation_message(
                        ChatMessage(
                            role=ChatMessageRole.TOOL,
                            content=invalid_result.content,
                            name=invalid_result.name,
                            tool_call_id=invalid_result.call_id,
                            content_parts=(
                                tool_message.content_parts
                                if tool_message is not None
                                else ()
                            ),
                        ),
                        tool_message.message_id if tool_message is not None else None,
                    )
                )
                if tool_message is not None:
                    round_resource_parts.extend(tool_message.content_parts)

            tool_call_batches = await asyncio.to_thread(
                self._build_tool_call_batches,
                prepared_tool_calls.executable_calls,
            )
            for tool_call_batch in tool_call_batches:
                for tool_call in tool_call_batch:
                    yield ChatStreamEvent(
                        kind=ChatStreamEventKind.TOOL_CALL,
                        tool_call=tool_call,
                    )
                if await self._batch_has_client_tool(tool_call_batch):
                    async for event in self._execute_streamed_tool_call_batch_events(
                        original_request,
                        tool_call_batch,
                        on_tool_call_cancelled=on_tool_call_cancelled,
                    ):
                        checkpoint = None
                        if event.kind == ChatStreamEventKind.TOOL_RESULT and event.tool_result is not None:
                            tool_message = await self._persist_tool_result(
                                original_request,
                                event.tool_result,
                            )
                            if tool_message is not None:
                                checkpoint = ConversationPersistenceCheckpoint(
                                    tool_message.message_id,
                                )
                            next_messages.append(
                                tag_conversation_message(
                                    ChatMessage(
                                        role=ChatMessageRole.TOOL,
                                        content=event.tool_result.content,
                                        name=event.tool_result.name,
                                        tool_call_id=event.tool_result.call_id,
                                        content_parts=(
                                            tool_message.content_parts
                                            if tool_message is not None
                                            else ()
                                        ),
                                    ),
                                    tool_message.message_id if tool_message is not None else None,
                                )
                            )
                            if tool_message is not None:
                                round_resource_parts.extend(tool_message.content_parts)
                        yield event
                        if checkpoint is not None:
                            yield checkpoint
                    continue

                tasks = [
                    asyncio.create_task(
                        self._execute_tool_call_with_audit(
                            original_request,
                            tool_call,
                            cancellation_call=tool_call,
                            on_tool_call_cancelled=on_tool_call_cancelled,
                        )
                    )
                    for tool_call in tool_call_batch
                ]
                try:
                    tool_results = await asyncio.gather(*tasks)
                except asyncio.CancelledError:
                    settled_results = await asyncio.gather(*tasks, return_exceptions=True)
                    for settled_result in settled_results:
                        if isinstance(settled_result, ChatToolResult):
                            await self._persist_tool_result(original_request, settled_result)
                    raise
                for tool_result in tool_results:
                    tool_message = await self._persist_tool_result(
                        original_request,
                        tool_result,
                    )
                    yield ChatStreamEvent(
                        kind=ChatStreamEventKind.TOOL_RESULT,
                        tool_result=tool_result,
                    )
                    if tool_message is not None:
                        yield ConversationPersistenceCheckpoint(tool_message.message_id)
                    next_messages.append(
                        tag_conversation_message(
                            ChatMessage(
                                role=ChatMessageRole.TOOL,
                                content=tool_result.content,
                                name=tool_result.name,
                                tool_call_id=tool_result.call_id,
                                content_parts=(
                                    tool_message.content_parts
                                    if tool_message is not None
                                    else ()
                                ),
                            ),
                            tool_message.message_id if tool_message is not None else None,
                        )
                    )
                    if tool_message is not None:
                        round_resource_parts.extend(tool_message.content_parts)
            resource_message = tool_resource_message(
                _deduplicate_image_parts(round_resource_parts)
            )
            if resource_message is not None:
                next_messages.append(resource_message)
            executed_tool_calls += len(round_tool_calls)
            if (
                prepared_tool_calls.invalid_results
                and not original_request.malformed_tool_call_recovery_enabled
            ):
                return
            current_request = replace(current_request, messages=tuple(next_messages))

    def _build_tool_call_batches(
        self,
        tool_calls: tuple[ChatToolCall, ...],
    ) -> tuple[tuple[ChatToolCall, ...], ...]:
        batches: list[tuple[ChatToolCall, ...]] = []
        parallel_batch: list[ChatToolCall] = []
        for tool_call in tool_calls:
            if self._is_parallel_tool_call(tool_call):
                parallel_batch.append(tool_call)
                continue
            if parallel_batch:
                batches.append(tuple(parallel_batch))
                parallel_batch = []
            batches.append((tool_call,))
        if parallel_batch:
            batches.append(tuple(parallel_batch))
        return tuple(batches)

    def _is_parallel_tool_call(self, tool_call: ChatToolCall) -> bool:
        if self._tool_execution_service is None:
            return False
        return self._tool_execution_service.is_parallel_tool(tool_call.name)

    async def _batch_has_client_tool(
        self,
        tool_calls: tuple[ChatToolCall, ...],
    ) -> bool:
        if self._tool_execution_service is None:
            return False

        def check_batch() -> bool:
            return any(
                self._tool_execution_service.is_client_tool(tool_call.name)
                or _is_dynamic_tool_executor_name(tool_call.name)
                for tool_call in tool_calls
            )

        return await asyncio.to_thread(check_batch)

    async def _execute_streamed_tool_call_batch_events(
        self,
        request: ChatCompletionRequest,
        tool_calls: tuple[ChatToolCall, ...],
        *,
        on_tool_call_cancelled: Callable[
            [ChatToolCall, ToolCancellationScope],
            None,
        ]
        | None = None,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        queue: asyncio.Queue[
            tuple[int, ChatStreamEvent | None, Exception | None]
        ] = asyncio.Queue()

        async def execute(index: int, tool_call: ChatToolCall) -> None:
            error: Exception | None = None
            try:
                async for event in self._execute_tool_call_events(
                    request,
                    tool_call,
                    on_tool_call_cancelled=on_tool_call_cancelled,
                ):
                    await queue.put((index, event, None))
            except Exception as exc:
                error = exc
            finally:
                await queue.put((index, None, error))

        tasks = [
            asyncio.create_task(execute(index, tool_call))
            for index, tool_call in enumerate(tool_calls)
        ]
        completed = 0
        first_error: Exception | None = None
        results: dict[int, ChatStreamEvent] = {}
        try:
            while completed < len(tasks):
                index, event, error = await queue.get()
                if event is None:
                    completed += 1
                    if first_error is None and error is not None:
                        first_error = error
                    continue
                if event.kind == ChatStreamEventKind.TOOL_RESULT:
                    results[index] = event
                    continue
                yield event
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        if first_error is not None:
            raise first_error
        for index in range(len(tool_calls)):
            result_event = results.get(index)
            if result_event is None:
                raise RuntimeError("工具调用未返回结果。")
            yield result_event

    async def _execute_tool_call_events(
        self,
        request: ChatCompletionRequest,
        tool_call: ChatToolCall,
        *,
        on_tool_call_cancelled: Callable[
            [ChatToolCall, ToolCancellationScope],
            None,
        ]
        | None = None,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        await self._record_tool_event(
            request,
            tool_call,
            event_type="tool.started",
            payload={"tool_name": tool_call.name},
        )
        try:
            async for event in self._execute_tool_call_events_impl(
                request,
                tool_call,
                on_tool_call_cancelled=on_tool_call_cancelled,
            ):
                if event.kind == ChatStreamEventKind.TOOL_RESULT and event.tool_result is not None:
                    result = event.tool_result
                    await self._record_tool_event(
                        request,
                        tool_call,
                        event_type="tool.completed" if result.ok else "tool.failed",
                        payload={
                            "tool_name": tool_call.name,
                            "ok": result.ok,
                            "elapsed_ms": result.elapsed_ms,
                        },
                    )
                yield event
        except asyncio.CancelledError:
            await self._record_tool_event(
                request,
                tool_call,
                event_type="tool.cancelled",
                payload={"tool_name": tool_call.name},
            )
            raise

    async def _execute_tool_call_events_impl(
        self,
        request: ChatCompletionRequest,
        tool_call: ChatToolCall,
        *,
        on_tool_call_cancelled: Callable[
            [ChatToolCall, ToolCancellationScope],
            None,
        ]
        | None = None,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        if (
            self._tool_execution_service is not None
            and _is_dynamic_tool_executor_name(tool_call.name)
        ):
            async for event in self._execute_dynamic_tool_call_events(
                request,
                tool_call,
                on_tool_call_cancelled=on_tool_call_cancelled,
            ):
                yield event
            return

        is_client_tool = False
        if self._tool_execution_service is not None:
            is_client_tool = await asyncio.to_thread(
                self._tool_execution_service.is_client_tool,
                tool_call.name,
            )
        if is_client_tool:
            async for event in self._execute_client_tool_call_events(
                request,
                tool_call,
                cancellation_call=tool_call,
                on_tool_call_cancelled=on_tool_call_cancelled,
            ):
                yield event
            return

        result = await self._execute_tool_call(
            request,
            tool_call,
            cancellation_call=tool_call,
            on_tool_call_cancelled=on_tool_call_cancelled,
        )
        yield ChatStreamEvent(
            kind=ChatStreamEventKind.TOOL_RESULT,
            tool_result=result,
        )

    async def _record_tool_event(
        self,
        request: ChatCompletionRequest,
        tool_call: ChatToolCall,
        *,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        if self._audit_service is None:
            return
        try:
            await asyncio.to_thread(
                self._audit_service.record_event,
                request,
                event_type=event_type,
                payload=payload,
                tool_call_id=tool_call.call_id,
            )
        except Exception:
            logger.exception("Failed to persist a tool audit event.")

    async def _execute_dynamic_tool_call_events(
        self,
        request: ChatCompletionRequest,
        executor_call: ChatToolCall,
        *,
        on_tool_call_cancelled: Callable[
            [ChatToolCall, ToolCancellationScope],
            None,
        ]
        | None = None,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        started_at = monotonic()
        if self._tool_execution_service is None:
            result = tool_call_failure_result(executor_call, "工具执行服务不可用。")
        else:
            permission_error = await asyncio.to_thread(
                self._session_tool_permission_error,
                request,
                executor_call.name,
            )
            if permission_error:
                result = tool_call_failure_result(executor_call, permission_error)
            else:
                enabled_tool_names = await asyncio.to_thread(
                    self._session_enabled_tool_names,
                    request,
                )
                prepared = await asyncio.to_thread(
                    self._tool_execution_service.prepare_dynamic_tool_execution,
                    executor_call,
                    enabled_tool_names=enabled_tool_names,
                )
                if isinstance(prepared, ChatToolResult):
                    result = prepared
                else:
                    target_result: ChatToolResult | None = None
                    if self._tool_execution_service.is_client_tool(prepared.target_call.name):
                        async for event in self._execute_client_tool_call_events(
                            request,
                            prepared.target_call,
                            cancellation_call=executor_call,
                            on_tool_call_cancelled=on_tool_call_cancelled,
                        ):
                            if event.kind == ChatStreamEventKind.CLIENT_TOOL_REQUEST:
                                yield event
                            elif event.kind == ChatStreamEventKind.TOOL_RESULT:
                                target_result = event.tool_result
                    else:
                        target_result = await self._execute_tool_call(
                            request,
                            prepared.target_call,
                            cancellation_call=executor_call,
                            on_tool_call_cancelled=on_tool_call_cancelled,
                        )
                    if target_result is None:
                        result = tool_call_failure_result(
                            executor_call,
                            "目标动态工具没有返回执行结果。",
                        )
                    else:
                        result = self._tool_execution_service.wrap_dynamic_tool_execution(
                            executor_call,
                            prepared,
                            target_result,
                        )

        yield ChatStreamEvent(
            kind=ChatStreamEventKind.TOOL_RESULT,
            tool_result=self._with_tool_elapsed(
                self._add_tool_failure_guidance(result),
                started_at,
            ),
        )

    async def _execute_client_tool_call_events(
        self,
        request: ChatCompletionRequest,
        tool_call: ChatToolCall,
        *,
        cancellation_call: ChatToolCall,
        on_tool_call_cancelled: Callable[
            [ChatToolCall, ToolCancellationScope],
            None,
        ]
        | None = None,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        started_at = monotonic()
        result: ChatToolResult | None = None
        try:
            if self._tool_execution_service is None:
                result = tool_call_failure_result(tool_call, "工具执行服务不可用。")
            elif self._client_tool_bridge_service is None:
                result = tool_call_failure_result(tool_call, "前端工具桥不可用。")
            else:
                permission_error = await asyncio.to_thread(
                    self._session_tool_permission_error,
                    request,
                    tool_call.name,
                )
                if permission_error:
                    result = tool_call_failure_result(tool_call, permission_error)
                else:
                    prepared = await asyncio.to_thread(
                        self._tool_execution_service.prepare_client_tool,
                        tool_call,
                    )
                    if isinstance(prepared, ChatToolResult):
                        result = prepared
                    elif isinstance(prepared, PreparedClientToolExecution):
                        input_modalities = await asyncio.to_thread(
                            self._model_input_modalities,
                            request,
                        )
                        client_request = await self._client_tool_bridge_service.create_request(
                            tool_call,
                            project_id=request.project_id,
                            session_id=request.session_id,
                            timeout_seconds=prepared.timeout_seconds,
                            model_context={
                                "provider_id": request.provider_id,
                                "model_id": request.model_id,
                                "input_modalities": list(input_modalities),
                            },
                            capability=prepared.capability,
                        )
                        yield ChatStreamEvent(
                            kind=ChatStreamEventKind.CLIENT_TOOL_REQUEST,
                            client_tool_request=client_request,
                        )
                        try:
                            client_result = await self._client_tool_bridge_service.wait_for_result(
                                client_request.request_id,
                                timeout_seconds=prepared.timeout_seconds,
                            )
                        except asyncio.TimeoutError:
                            client_result = ClientToolResultPayload(
                                ok=False,
                                error="客户端工具执行超时。",
                            )
                        result = client_tool_result_to_chat_tool_result(
                            tool_call,
                            client_result,
                            tool_project_id=prepared.tool_project_id,
                            dynamic=prepared.dynamic,
                        )
                    else:
                        result = await self._execute_tool_call(
                            request,
                            tool_call,
                            cancellation_call=cancellation_call,
                            on_tool_call_cancelled=on_tool_call_cancelled,
                        )

        except asyncio.CancelledError:
            if on_tool_call_cancelled is not None:
                on_tool_call_cancelled(cancellation_call, ToolCancellationScope.WAIT)
            raise

        yield ChatStreamEvent(
            kind=ChatStreamEventKind.TOOL_RESULT,
            tool_result=self._with_tool_elapsed(
                self._add_tool_failure_guidance(result),
                started_at,
            ),
        )

    async def _execute_tool_call(
        self,
        request: ChatCompletionRequest,
        tool_call: ChatToolCall,
        *,
        cancellation_call: ChatToolCall | None = None,
        on_tool_call_cancelled: Callable[
            [ChatToolCall, ToolCancellationScope],
            None,
        ]
        | None = None,
    ) -> ChatToolResult:
        started_at = monotonic()
        if self._tool_execution_service is None:
            return self._with_tool_elapsed(
                self._add_tool_failure_guidance(
                    tool_call_failure_result(tool_call, "工具执行服务不可用。")
                ),
                started_at,
            )
        permission_error = await asyncio.to_thread(
            self._session_tool_permission_error,
            request,
            tool_call.name,
        )
        if permission_error:
            return self._with_tool_elapsed(
                self._add_tool_failure_guidance(
                    tool_call_failure_result(tool_call, permission_error)
                ),
                started_at,
            )
        workspace_root = await asyncio.to_thread(self._project_root_path, request.project_id)
        input_modalities = await asyncio.to_thread(
            self._model_input_modalities,
            request,
        )
        context = ToolExecutionContext(
            workspace_root=workspace_root,
            project_id=request.project_id,
            session_id=request.session_id,
            provider_id=request.provider_id,
            model_id=request.model_id,
            input_modalities=input_modalities,
            enabled_tool_names=await asyncio.to_thread(
                self._session_enabled_tool_names,
                request,
            ),
        )
        cancellation = ToolExecutionCancellation()
        controlled_execute = getattr(
            self._tool_execution_service,
            "execute_cancellable",
            None,
        )
        if callable(controlled_execute):
            execution_task = asyncio.create_task(
                asyncio.to_thread(
                    controlled_execute,
                    tool_call,
                    context=context,
                    cancellation=cancellation,
                )
            )
        else:
            execution_task = asyncio.create_task(
                asyncio.to_thread(
                    self._tool_execution_service.execute,
                    tool_call,
                    context=context,
                )
            )
        try:
            result = await asyncio.shield(execution_task)
        except asyncio.CancelledError:
            cancellation.cancel()
            if callable(controlled_execute):
                try:
                    await asyncio.wait_for(asyncio.shield(execution_task), timeout=5)
                except Exception:
                    pass
            if on_tool_call_cancelled is not None:
                on_tool_call_cancelled(
                    cancellation_call or tool_call,
                    ToolCancellationScope.EXECUTION,
                )
            raise
        return self._with_tool_elapsed(self._add_tool_failure_guidance(result), started_at)

    async def _execute_tool_call_with_audit(
        self,
        request: ChatCompletionRequest,
        tool_call: ChatToolCall,
        *args,
        **kwargs,
    ) -> ChatToolResult:
        await self._record_tool_event(
            request,
            tool_call,
            event_type="tool.started",
            payload={"tool_name": tool_call.name},
        )
        try:
            result = await self._execute_tool_call(request, tool_call, *args, **kwargs)
        except asyncio.CancelledError:
            await self._record_tool_event(
                request,
                tool_call,
                event_type="tool.cancelled",
                payload={"tool_name": tool_call.name},
            )
            raise
        await self._record_tool_event(
            request,
            tool_call,
            event_type="tool.completed" if result.ok else "tool.failed",
            payload={
                "tool_name": tool_call.name,
                "ok": result.ok,
                "elapsed_ms": result.elapsed_ms,
            },
        )
        return result

    def _model_input_modalities(
        self,
        request: ChatCompletionRequest,
    ) -> tuple[str, ...]:
        if self._runtime_capabilities_service is None:
            return ()
        try:
            capabilities = self._runtime_capabilities_service.get_capabilities(
                provider_id=request.provider_id,
                model_id=request.model_id,
            )
        except AppError:
            return ()
        return capabilities.input_modalities

    async def _persist_tool_result(
        self,
        request: ChatCompletionRequest,
        tool_result: ChatToolResult,
    ) -> ProjectConversationMessage | None:
        tool_message = await asyncio.to_thread(
            self._append_tool_message,
            request,
            tool_result,
        )
        await asyncio.to_thread(
            self._record_tool_call,
            request,
            tool_result,
        )
        return tool_message

    def _with_tool_elapsed(
        self,
        result: ChatToolResult,
        started_at: float,
    ) -> ChatToolResult:
        return replace(
            result,
            elapsed_ms=max(0, round((monotonic() - started_at) * 1000)),
        )

    def _add_tool_failure_guidance(self, result: ChatToolResult) -> ChatToolResult:
        if result.ok or self._tool_result_guidance_service is None:
            return result
        return self._tool_result_guidance_service.add_failure_guidance(result)

    def _session_tool_permission_error(
        self,
        request: ChatCompletionRequest,
        tool_name: str,
    ) -> str:
        if not request.project_id or not request.session_id:
            return ""
        try:
            session = self._conversation_service.get_session(request.project_id, request.session_id)
        except AppError:
            return "无法确认当前会话的工具启用状态。"
        if session is None:
            return "当前会话不存在，无法执行工具。"
        if not session.settings.tools_enabled:
            return "会话工具总开关已关闭。"
        enabled_tool_names = session.settings.enabled_tool_names
        if enabled_tool_names is None:
            return ""
        try:
            normalized_tool_name = normalize_tool_name(tool_name)
        except AppError:
            return "工具调用名称无效。"
        if normalized_tool_name in DYNAMIC_TOOL_INFRASTRUCTURE_NAMES:
            return ""
        normalized_enabled_names: set[str] = set()
        for enabled_tool_name in enabled_tool_names:
            try:
                normalized_enabled_names.add(normalize_tool_name(enabled_tool_name))
            except AppError:
                return "会话工具启用配置无效。"
        if normalized_tool_name not in normalized_enabled_names:
            return "此工具已关闭。"
        return ""

    def _session_enabled_tool_names(
        self,
        request: ChatCompletionRequest,
    ) -> tuple[str, ...] | None:
        if not request.project_id or not request.session_id:
            return None
        try:
            session = self._conversation_service.get_session(request.project_id, request.session_id)
        except AppError:
            return ()
        if session is None:
            return ()
        if not session.settings.tools_enabled:
            return ()
        return session.settings.enabled_tool_names

    def _project_root_path(self, project_id: str | None) -> str | None:
        if not project_id or self._project_service is None:
            return None
        try:
            project = self._project_service.get_project(project_id)
        except AppError:
            return None
        return project.root_path if project is not None else None

    def _append_tool_message(
        self,
        request: ChatCompletionRequest,
        tool_result: ChatToolResult,
    ) -> ProjectConversationMessage | None:
        if not request.project_id or not request.session_id:
            return None
        status = "done" if tool_result.ok else "error"
        content = tool_result_message_content(tool_result)
        content_parts = image_parts_from_tool_content(tool_result.content)
        if self._attachment_service is not None:
            content_parts = tuple(
                replace(
                    part,
                    image_ref=self._attachment_service.snapshot_image_ref(
                        request.project_id,
                        request.session_id,
                        part.image_ref,
                        source_kind="tool_artifact",
                    ),
                )
                for part in content_parts
                if part.image_ref is not None
            )
        return self._append_conversation_message(
            request.project_id,
            request.session_id,
            role="tool",
            content=content,
            name=tool_result.name,
            tool_call_id=tool_result.call_id,
            content_parts=content_parts,
            status=status,
            sync_session_model=False,
        )

    def _append_assistant_tool_call_message(
        self,
        request: ChatCompletionRequest,
        *,
        content: str,
        thinking_content: str,
        tool_calls: tuple[ChatToolCall, ...],
        protocol_continuation: ChatProtocolContinuation | None,
        usage: dict[str, object] | None,
        context_tokens: int | None,
        context_tokens_estimated: bool,
    ) -> ProjectConversationMessage | None:
        if not request.project_id or not request.session_id or not tool_calls:
            return None
        message = self._append_conversation_message(
            request.project_id,
            request.session_id,
            role="assistant",
            content=content,
            thinking_content=thinking_content,
            tool_calls=tool_calls,
            protocol_continuation=protocol_continuation,
            usage=usage,
            context_tokens=context_tokens,
            context_tokens_estimated=context_tokens_estimated,
            provider_id=request.provider_id,
            model_id=request.model_id,
            status="done",
            sync_session_model=False,
        )
        self._save_runtime_status(request, "running")
        return message

    def _record_tool_call(
        self,
        request: ChatCompletionRequest,
        tool_result: ChatToolResult,
    ) -> None:
        if self._tool_call_record_service is None:
            return
        self._tool_call_record_service.append_result(
            tool_result,
            project_id=request.project_id,
            session_id=request.session_id,
        )

    def _save_runtime_status(self, request: ChatCompletionRequest, status: str) -> None:
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

    def _append_conversation_message(
        self,
        project_id: str,
        session_id: str,
        **kwargs,
    ) -> ProjectConversationMessage:
        return self._conversation_service.append_message(
            project_id,
            session_id,
            **kwargs,
        )


def _is_dynamic_tool_executor_name(tool_name: str) -> bool:
    try:
        return normalize_tool_name(tool_name) == DYNAMIC_TOOL_EXECUTOR_NAME
    except AppError:
        return False


def _normalize_tool_call_limit(value: int | None) -> int:
    if value is None:
        return _DEFAULT_MAX_TOOL_CALLS
    return max(value, 1)
