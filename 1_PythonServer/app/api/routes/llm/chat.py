import asyncio
import json

import httpx
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.errors import (
    BadRequestError,
    NotFoundError,
    UpstreamProviderError,
    to_upstream_provider_error,
)
from app.schemas.llm.chat import (
    ChatCompletionRequestBody,
    ChatCompletionResponse,
    ChatStreamStopRequestBody,
    ChatStreamStopResponse,
)
from app.services.llm.chat.service import get_chat_completion_service
from app.services.project.conversation_run_manager import get_conversation_run_manager
from app.services.project import get_project_conversation_service
from app.services.project.conversation_stream import get_project_conversation_stream_service

router = APIRouter(prefix="/llm/chat", tags=["llm"])


@router.post(
    "/completions",
    response_model=ChatCompletionResponse,
    summary="Create a non-streaming chat completion",
)
async def create_chat_completion(
    payload: ChatCompletionRequestBody,
) -> ChatCompletionResponse:
    _ensure_request_messages(payload)
    service = get_chat_completion_service()
    try:
        result = await service.complete(payload.to_domain())
    except httpx.HTTPStatusError as exc:
        raise to_upstream_provider_error(exc) from exc
    except httpx.RequestError as exc:
        raise UpstreamProviderError(f"上游供应商连接失败：{exc}") from exc
    return ChatCompletionResponse.from_domain(result)


@router.post(
    "/completions/stream",
    summary="Create a streaming chat completion (SSE)",
)
async def create_chat_completion_stream(payload: ChatCompletionRequestBody):
    _ensure_request_messages(payload)
    request = payload.to_domain()
    service = get_project_conversation_stream_service()
    await asyncio.to_thread(service.validate_conversation_target, request)
    if not request.project_id or not request.session_id:
        async def direct_event_generator():
            async for stream_payload in service.stream_payloads(request):
                yield _sse_event(stream_payload)

        return StreamingResponse(direct_event_generator(), media_type="text/event-stream")

    run_manager = get_conversation_run_manager()
    subscription = await run_manager.start(request, service)

    async def event_generator():
        async for stream_payload in run_manager.stream(subscription):
            yield _sse_event(stream_payload)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post(
    "/completions/stream/stop",
    response_model=ChatStreamStopResponse,
    summary="Stop a running project conversation completion",
)
async def stop_chat_completion_stream(
    payload: ChatStreamStopRequestBody,
) -> ChatStreamStopResponse:
    stopped = await get_conversation_run_manager().stop(
        payload.project_id,
        payload.session_id,
    )
    if not stopped:
        await asyncio.to_thread(
            get_project_conversation_service().reconcile_missing_run_runtime_status,
            payload.project_id,
            payload.session_id,
        )
    return ChatStreamStopResponse(stopped=stopped)


@router.get(
    "/completions/stream/active",
    summary="Subscribe to an active project conversation completion (SSE)",
)
async def subscribe_active_chat_completion_stream(
    project_id: str,
    session_id: str,
    checkpoint_message_id: str | None = None,
):
    run_manager = get_conversation_run_manager()
    try:
        subscription = await run_manager.subscribe(
            project_id,
            session_id,
            checkpoint_message_id,
        )
    except NotFoundError:
        await asyncio.to_thread(
            get_project_conversation_service().reconcile_missing_run_runtime_status,
            project_id,
            session_id,
        )
        raise

    async def event_generator():
        async for stream_payload in run_manager.stream(subscription):
            yield _sse_event(stream_payload)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post(
    "/injection-preview",
    summary="Update the conversation injection preview without sending a completion request",
)
async def update_chat_injection_preview(payload: ChatCompletionRequestBody):
    request = payload.to_domain()
    service = get_project_conversation_stream_service()
    preview = await service.update_injection_preview(request)
    return {"ok": preview is not None, "preview": preview}


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _ensure_request_messages(payload: ChatCompletionRequestBody) -> None:
    if not payload.messages:
        raise BadRequestError("发送消息内容不能为空。")
