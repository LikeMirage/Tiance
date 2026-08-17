from collections.abc import AsyncGenerator
import asyncio
from dataclasses import replace
from functools import lru_cache
import logging

from app.core.errors import BadRequestError, NotFoundError
from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatCompletionResult,
    ChatMessage,
    ChatMessageRole,
    ChatProtocolContinuation,
    ChatStreamEvent,
    ChatStreamEventKind,
    ChatToolCall,
    ChatUsage,
)
from app.domain.llm.chat_http_exchange import ChatHttpExchange, ChatHttpExchangeRecorder
from app.domain.llm.token_estimation_settings import (
    DEFAULT_TOKEN_ESTIMATION_SETTINGS,
    TokenEstimationSettings,
)
from app.infra.llm.chat_remote_client import ChatRemoteClient, get_chat_remote_client
from app.repositories.llm.provider_catalog_repository import (
    ProviderCatalogRepository,
    get_provider_catalog_repository,
)
from app.repositories.llm.provider_config_repository import (
    ProviderConfigRepository,
    get_provider_config_repository,
)
from app.services.llm.provider.api_key_scheduler import (
    ProviderApiKeyScheduler,
    get_provider_api_key_scheduler,
)
from app.services.llm.provider.config_runtime import ProviderConfigRuntimeResolver
from app.services.llm.usage import LlmUsageService, get_llm_usage_service
from app.services.llm.usage.estimation import (
    complete_usage_with_estimates,
)
from app.services.llm.token_estimation_settings import (
    TokenEstimationSettingsService,
    get_token_estimation_settings_service,
)
from app.domain.llm.provider_catalog import ProviderCatalogEntry
from app.infra.llm.provider_profiles import resolve_provider_profile
from app.services.llm.chat.request_validation import validate_chat_request_capabilities


logger = logging.getLogger(__name__)


class ChatCompletionService:
    def __init__(
        self,
        catalog_repository: ProviderCatalogRepository,
        config_repository: ProviderConfigRepository,
        remote_client: ChatRemoteClient,
        api_key_scheduler: ProviderApiKeyScheduler,
        usage_service: LlmUsageService,
        token_estimation_settings_service: TokenEstimationSettingsService,
        http_exchange_recorder: ChatHttpExchangeRecorder | None = None,
    ) -> None:
        self._catalog_repository = catalog_repository
        self._config_repository = config_repository
        self._remote_client = remote_client
        self._usage_service = usage_service
        self._token_estimation_settings_service = token_estimation_settings_service
        self._runtime_resolver = ProviderConfigRuntimeResolver(
            api_key_scheduler,
        )
        self._http_exchange_recorder = http_exchange_recorder

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResult:
        provider_template = self._catalog_repository.get_entry(request.provider_id)
        if provider_template is None:
            raise NotFoundError(f"Provider template '{request.provider_id}' was not found.")

        provider_config = self._config_repository.get_config(provider_template.provider_id)
        if provider_config is None:
            raise NotFoundError(f"Provider config '{request.provider_id}' was not found.")
        if not provider_config.enabled:
            raise BadRequestError(f"Provider config '{request.provider_id}' is disabled.")

        request = replace(
            request,
            reasoning_replay_mode=provider_config.reasoning_replay_mode,
        )

        self._validate_request(provider_template, request)

        runtime_credentials = self._runtime_resolver.resolve_runtime_credentials(
            provider_template,
            provider_config,
        )
        if runtime_credentials is None:
            raise BadRequestError(f"Provider config '{request.provider_id}' has no saved API key.")

        runtime_config, selected_api_key = runtime_credentials
        result = await self._remote_client.complete(
            provider_template=provider_template,
            runtime_config=runtime_config,
            api_key=selected_api_key.api_key,
            request=request,
            on_exchange=self._record_http_exchange,
        )
        usage = complete_usage_with_estimates(
            request=request,
            provider_usage=result.usage,
            response_message=result.message,
            thinking_content=result.thinking_content,
            settings=self._estimation_settings_for(result.usage),
        )
        self._record_usage_if_present(request=request, usage=usage)
        return ChatCompletionResult(
            provider_id=result.provider_id,
            model_id=result.model_id,
            message=result.message,
            thinking_content=result.thinking_content,
            finish_reason=result.finish_reason,
            usage=usage,
            selected_key_id=selected_api_key.key_id or None,
            selected_api_key_hint=selected_api_key.api_key_hint,
            raw_response=result.raw_response,
        )

    async def stream(self, request: ChatCompletionRequest) -> AsyncGenerator[ChatStreamEvent, None]:
        provider_template = self._catalog_repository.get_entry(request.provider_id)
        if provider_template is None:
            raise NotFoundError(f"Provider template '{request.provider_id}' was not found.")

        provider_config = self._config_repository.get_config(provider_template.provider_id)
        if provider_config is None:
            raise NotFoundError(f"Provider config '{request.provider_id}' was not found.")
        if not provider_config.enabled:
            raise BadRequestError(f"Provider config '{request.provider_id}' is disabled.")

        request = replace(
            request,
            reasoning_replay_mode=provider_config.reasoning_replay_mode,
        )

        self._validate_request(provider_template, request)

        runtime_credentials = self._runtime_resolver.resolve_runtime_credentials(
            provider_template, provider_config,
        )
        if runtime_credentials is None:
            raise BadRequestError(f"Provider config '{request.provider_id}' has no saved API key.")

        runtime_config, selected_api_key = runtime_credentials
        provider_usage: ChatUsage | None = None
        done_event: ChatStreamEvent | None = None
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_calls: list[ChatToolCall] = []
        protocol_continuation: ChatProtocolContinuation | None = None
        failed = False
        async for event in self._remote_client.stream(
            provider_template=provider_template,
            runtime_config=runtime_config,
            api_key=selected_api_key.api_key,
            request=request,
            on_exchange=self._record_http_exchange,
        ):
            if event.kind == ChatStreamEventKind.USAGE and event.usage is not None:
                provider_usage = _overlay_usage(provider_usage, event.usage)
                continue
            if event.kind == ChatStreamEventKind.DONE:
                done_event = event
                continue
            if event.kind == ChatStreamEventKind.DELTA and event.content:
                content_parts.append(event.content)
            elif event.kind == ChatStreamEventKind.THINKING_DELTA and event.content:
                thinking_parts.append(event.content)
            elif event.kind == ChatStreamEventKind.TOOL_CALL and event.tool_call is not None:
                tool_calls.append(event.tool_call)
            elif (
                event.kind == ChatStreamEventKind.PROTOCOL_CONTINUATION
                and event.protocol_continuation is not None
            ):
                protocol_continuation = event.protocol_continuation
            elif event.kind == ChatStreamEventKind.ERROR:
                failed = True
                if provider_usage is not None:
                    self._record_usage_if_present(
                        request=request,
                        usage=provider_usage,
                    )
                    yield ChatStreamEvent(
                        kind=ChatStreamEventKind.USAGE,
                        usage=provider_usage,
                    )
                    provider_usage = None
            yield event

        if not failed:
            usage = complete_usage_with_estimates(
                request=request,
                provider_usage=provider_usage,
                response_message=ChatMessage(
                    role=ChatMessageRole.ASSISTANT,
                    content="".join(content_parts),
                    thinking_content="".join(thinking_parts),
                    tool_calls=tuple(tool_calls),
                    protocol_continuation=protocol_continuation,
                ),
                settings=self._estimation_settings_for(provider_usage),
            )
            self._record_usage_if_present(request=request, usage=usage)
            yield ChatStreamEvent(kind=ChatStreamEventKind.USAGE, usage=usage)
        elif provider_usage is not None:
            self._record_usage_if_present(request=request, usage=provider_usage)
            yield ChatStreamEvent(kind=ChatStreamEventKind.USAGE, usage=provider_usage)

        if done_event is not None:
            yield done_event

    def _record_usage_if_present(
        self,
        *,
        request: ChatCompletionRequest,
        usage: ChatUsage | None,
    ) -> None:
        if usage is None or not request.record_usage:
            return
        try:
            self._usage_service.record_message_usage(
                project_id=request.project_id,
                session_id=request.session_id,
                message_id=request.usage_message_id,
                provider_id=request.provider_id,
                model_id=request.model_id,
                usage=usage,
                usage_feature_key=request.usage_feature_key,
            )
        except Exception:
            logger.exception("Failed to record usage for a completed model request.")

    async def _record_http_exchange(
        self,
        request: ChatCompletionRequest,
        exchange: ChatHttpExchange,
    ) -> None:
        if self._http_exchange_recorder is None:
            return
        await asyncio.to_thread(
            self._http_exchange_recorder.record_http_exchange,
            request,
            exchange,
        )

    @staticmethod
    def _validate_request(
        provider_template: ProviderCatalogEntry,
        request: ChatCompletionRequest,
    ) -> None:
        profile = resolve_provider_profile(provider_template, request.model_id)
        validate_chat_request_capabilities(
            request,
            profile.resolve_capabilities(provider_template, request.model_id),
        )

    def _estimation_settings_for(
        self,
        usage: ChatUsage | None,
    ) -> TokenEstimationSettings:
        if (
            usage is not None
            and usage.prompt_tokens is not None
            and usage.completion_tokens is not None
        ):
            return DEFAULT_TOKEN_ESTIMATION_SETTINGS
        return self._token_estimation_settings_service.get_settings()


def _overlay_usage(current: ChatUsage | None, incoming: ChatUsage) -> ChatUsage:
    if current is None:
        return incoming
    return ChatUsage(
        prompt_tokens=incoming.prompt_tokens
        if incoming.prompt_tokens is not None
        else current.prompt_tokens,
        completion_tokens=incoming.completion_tokens
        if incoming.completion_tokens is not None
        else current.completion_tokens,
        total_tokens=incoming.total_tokens
        if incoming.total_tokens is not None
        else current.total_tokens,
        prompt_cache_hit_tokens=incoming.prompt_cache_hit_tokens
        if incoming.prompt_cache_hit_tokens is not None
        else current.prompt_cache_hit_tokens,
        prompt_cache_miss_tokens=incoming.prompt_cache_miss_tokens
        if incoming.prompt_cache_miss_tokens is not None
        else current.prompt_cache_miss_tokens,
        reasoning_tokens=incoming.reasoning_tokens
        if incoming.reasoning_tokens is not None
        else current.reasoning_tokens,
        estimated_fields=tuple(sorted({
            *current.estimated_fields,
            *incoming.estimated_fields,
        })),
    )


@lru_cache
def get_chat_completion_service() -> ChatCompletionService:
    from app.services.project.conversation_audit import get_conversation_audit_service

    return ChatCompletionService(
        get_provider_catalog_repository(),
        get_provider_config_repository(),
        get_chat_remote_client(),
        get_provider_api_key_scheduler(),
        get_llm_usage_service(),
        get_token_estimation_settings_service(),
        get_conversation_audit_service(),
    )
