from contextlib import aclosing
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import UTC, datetime
from functools import lru_cache
import logging

from app.core.errors import BadRequestError
from app.domain.llm.chat import ChatCompletionRequest, ChatCompletionResult, ChatStreamEvent
from app.domain.llm.chat_http_exchange import ChatHttpExchange
from app.domain.llm.response_body import ResponseBody
from app.infra.llm.response_capture import ResponseCapture
from app.domain.llm.provider_catalog import ProviderCatalogEntry, ProviderProtocolFamily
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.infra.http_client import lease_http_client, get_http_timeout, get_shared_http_client
from app.infra.llm.chat_adapters import (
    AnthropicMessagesChatAdapter,
    ChatAdapter,
    GeminiGenerateContentChatAdapter,
    OpenAICompatibleChatAdapter,
    OpenAIResponsesChatAdapter,
)
from app.infra.llm.request_headers import merge_request_headers, resolve_request_headers
from app.infra.llm.redaction import SENSITIVE_NAMES as _SENSITIVE_NAMES, redact_url as _redact_url


logger = logging.getLogger(__name__)
ChatExchangeCallback = Callable[
    [ChatCompletionRequest, ChatHttpExchange],
    Awaitable[None],
]


class ChatRemoteClient:
    def __init__(self) -> None:
        self._adapters: dict[ProviderProtocolFamily, ChatAdapter] = {
            ProviderProtocolFamily.OPENAI_COMPATIBLE: OpenAICompatibleChatAdapter(),
            ProviderProtocolFamily.OPENAI_RESPONSES: OpenAIResponsesChatAdapter(),
            ProviderProtocolFamily.ANTHROPIC_MESSAGES: AnthropicMessagesChatAdapter(),
            ProviderProtocolFamily.GEMINI_GENERATE_CONTENT: GeminiGenerateContentChatAdapter(),
        }

    async def complete(
        self,
        *,
        provider_template: ProviderCatalogEntry,
        runtime_config: ProviderRuntimeConfig,
        api_key: str,
        request: ChatCompletionRequest,
        on_exchange: ChatExchangeCallback | None = None,
    ) -> ChatCompletionResult:
        adapter = self._adapters.get(provider_template.protocol_family)
        if adapter is None:
            raise BadRequestError(
                f"Protocol family '{provider_template.protocol_family.value}' does not support chat completions yet."
            )
        declared_headers = resolve_request_headers(
            provider_template,
            model_id=request.model_id,
            session_id=request.session_id or request.transport_session_id,
        )
        async def post_json(
            url: str,
            headers: dict[str, str],
            body: dict[str, object],
        ) -> dict[str, object]:
            return await self._post_json(
                url,
                merge_request_headers(headers, declared_headers),
                body,
                request=request,
                on_exchange=on_exchange,
            )

        return await adapter.complete(
            provider_template=provider_template,
            runtime_config=runtime_config,
            api_key=api_key,
            request=request,
            post_json=post_json,
        )

    async def stream(
        self,
        *,
        provider_template: ProviderCatalogEntry,
        runtime_config: ProviderRuntimeConfig,
        api_key: str,
        request: ChatCompletionRequest,
        on_exchange: ChatExchangeCallback | None = None,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        adapter = self._adapters.get(provider_template.protocol_family)
        if adapter is None:
            raise BadRequestError(
                f"Protocol family '{provider_template.protocol_family.value}' does not support chat completions yet."
            )
        declared_headers = resolve_request_headers(
            provider_template,
            model_id=request.model_id,
            session_id=request.session_id or request.transport_session_id,
        )
        async def stream_body(
            url: str,
            headers: dict[str, str],
            body: dict[str, object],
        ) -> AsyncGenerator[bytes, None]:
            async with aclosing(self._stream_body(
                url,
                merge_request_headers(headers, declared_headers),
                body,
                request=request,
                on_exchange=on_exchange,
            )) as owned_stream:
                async for chunk in owned_stream:
                    yield chunk

        async with aclosing(adapter.stream(
            provider_template=provider_template,
            runtime_config=runtime_config,
            api_key=api_key,
            request=request,
            stream_body=stream_body,
        )) as owned_stream:
            async for event in owned_stream:
                yield event

    async def _post_json(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, object],
        *,
        request: ChatCompletionRequest | None = None,
        on_exchange: ChatExchangeCallback | None = None,
    ) -> dict[str, object]:
        started_at = datetime.now(UTC).isoformat()
        async with lease_http_client(get_shared_http_client()) as client:
            response = None
            failure: BaseException | None = None
            try:
                response = await client.post(url, headers=headers, json=body)
                response.raise_for_status()
                if not response.content:
                    return {}
                payload = response.json()
                return payload if isinstance(payload, dict) else {}
            except BaseException as exc:
                failure = exc
                raise
            finally:
                await _notify_exchange(
                    request=request,
                    on_exchange=on_exchange,
                    started_at=started_at,
                    url=url,
                    headers=headers,
                    body=body,
                    response_status=getattr(response, "status_code", None),
                    response_headers=dict(getattr(response, "headers", {}) or {}),
                    response_body=response.content if response is not None else b"",
                    failure=failure,
                )

    async def _stream_body(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, object],
        *,
        request: ChatCompletionRequest | None = None,
        on_exchange: ChatExchangeCallback | None = None,
    ) -> AsyncGenerator[bytes, None]:
        started_at = datetime.now(UTC).isoformat()
        async with lease_http_client(get_shared_http_client()) as client:
            response = None
            failure: BaseException | None = None
            capture = ResponseCapture() if on_exchange is not None and request is not None else None
            try:
                async with client.stream(
                    "POST",
                    url,
                    headers=headers,
                    json=body,
                    timeout=get_http_timeout(stream=True),
                ) as response:
                    if response.is_error:
                        async for chunk in response.aiter_bytes():
                            if capture is not None:
                                capture.write(chunk)
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        if capture is not None:
                            capture.write(chunk)
                        yield chunk
            except BaseException as exc:
                failure = exc
                raise
            finally:
                if capture is not None:
                    capture.seal()
                    try:
                        await _notify_exchange(
                            request=request, on_exchange=on_exchange, started_at=started_at,
                            url=url, headers=headers, body=body,
                            response_status=getattr(response, "status_code", None),
                            response_headers=dict(getattr(response, "headers", {}) or {}),
                            response_body=capture, failure=failure,
                        )
                    finally:
                        capture.release()


async def _notify_exchange(
    *,
    request: ChatCompletionRequest | None,
    on_exchange: ChatExchangeCallback | None,
    started_at: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, object],
    response_status: int | None,
    response_headers: dict[str, str],
    response_body: bytes | ResponseBody,
    failure: BaseException | None,
) -> None:
    if on_exchange is None or request is None:
        return
    safe_url = _redact_url(url)
    try:
        await on_exchange(
            request,
            ChatHttpExchange(
                started_at=started_at,
                completed_at=datetime.now(UTC).isoformat(),
                request_url=safe_url,
                request_headers=_redact_headers(headers),
                request_body=_redact_mapping(body),
                response_status=response_status,
                response_headers=_redact_headers(response_headers),
                response_body=response_body,
                error_type=type(failure).__name__ if failure is not None else None,
                error_message=(
                    _safe_error_message(failure, url=url, safe_url=safe_url, headers=headers)
                    if failure is not None
                    else None
                ),
            ),
        )
    except Exception:
        logger.exception("Failed to persist a model HTTP exchange audit record.")


def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        key: "[REDACTED]" if key.lower() in _SENSITIVE_NAMES else value
        for key, value in headers.items()
    }


def _redact_mapping(value: dict[str, object]) -> dict[str, object]:
    return {
        key: "[REDACTED]" if key.lower() in _SENSITIVE_NAMES else _redact_value(item)
        for key, item in value.items()
    }


def _redact_value(value: object) -> object:
    if isinstance(value, dict):
        return _redact_mapping({str(key): item for key, item in value.items()})
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def _safe_error_message(
    failure: BaseException,
    *,
    url: str,
    safe_url: str,
    headers: dict[str, str],
) -> str:
    message = str(failure).replace(url, safe_url)
    for key, value in headers.items():
        if key.lower() in _SENSITIVE_NAMES and value:
            message = message.replace(value, "[REDACTED]")
    return message


@lru_cache
def get_chat_remote_client() -> ChatRemoteClient:
    return ChatRemoteClient()
