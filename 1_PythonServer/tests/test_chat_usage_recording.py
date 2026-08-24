import asyncio
from dataclasses import replace

import httpx
import pytest

from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatCompletionResult,
    ChatMessage,
    ChatMessageRole,
    ChatStreamEvent,
    ChatStreamEventKind,
    ChatUsage,
)
from app.domain.llm.provider_catalog import (
    AuthScheme,
    ProviderCatalogEntry,
    ProviderEndpointTemplate,
    ProviderProtocolFamily,
    default_model_discovery_strategy,
)
from app.domain.llm.provider_custom_model import ProviderCustomModel
from app.domain.llm.provider_config import ProviderApiKeyConfig, ProviderConfig
from app.domain.llm.token_estimation_settings import (
    DEFAULT_TOKEN_ESTIMATION_SETTINGS,
)
from app.services.llm.chat.service import ChatCompletionService
from app.services.llm.usage.service import LlmUsageService
from app.services.llm.provider.api_key_scheduler import ProviderRuntimeApiKey
from app.services.llm.provider import config_runtime as config_runtime_module
from app.repositories.llm.usage_repository import LlmUsageRepository


@pytest.fixture(autouse=True)
def _decrypt_test_api_key(monkeypatch):
    monkeypatch.setattr(
        config_runtime_module,
        "resolve_api_key_secret",
        lambda api_key: "sk-test" if api_key.api_key_ciphertext == "ciphertext" else None,
    )


def test_complete_records_usage_in_chat_service_layer():
    usage_service = _FakeUsageService()
    service = _build_service(
        remote_client=_FakeRemoteClient(
            complete_result=ChatCompletionResult(
                provider_id="deepseek",
                model_id="deepseek-v4",
                message=ChatMessage(role=ChatMessageRole.ASSISTANT, content="ok"),
                usage=ChatUsage(prompt_tokens=3, completion_tokens=5, total_tokens=8),
            ),
        ),
        usage_service=usage_service,
    )

    result = asyncio.run(service.complete(_request(project_id=None, session_id=None)))

    assert result.usage == ChatUsage(prompt_tokens=3, completion_tokens=5, total_tokens=8)
    assert usage_service.records == [
        {
            "project_id": None,
            "session_id": None,
            "message_id": None,
            "provider_id": "deepseek",
            "model_id": "deepseek-v4",
            "usage": ChatUsage(prompt_tokens=3, completion_tokens=5, total_tokens=8),
            "usage_feature_key": "main_chat",
        }
    ]


def test_usage_storage_failure_does_not_fail_completed_model_response():
    service = _build_service(
        remote_client=_FakeRemoteClient(
            complete_result=ChatCompletionResult(
                provider_id="deepseek",
                model_id="deepseek-v4",
                message=ChatMessage(role=ChatMessageRole.ASSISTANT, content="ok"),
                usage=ChatUsage(prompt_tokens=3, completion_tokens=5, total_tokens=8),
            ),
        ),
        usage_service=_FailingUsageService(),
    )

    result = asyncio.run(service.complete(_request(project_id="p1", session_id="s1")))

    assert result.message.content == "ok"


def test_complete_records_usage_with_message_id_when_provided():
    usage_service = _FakeUsageService()
    service = _build_service(
        remote_client=_FakeRemoteClient(
            complete_result=ChatCompletionResult(
                provider_id="deepseek",
                model_id="deepseek-v4",
                message=ChatMessage(role=ChatMessageRole.ASSISTANT, content="ok"),
                usage=ChatUsage(prompt_tokens=3, completion_tokens=5, total_tokens=8),
            ),
        ),
        usage_service=usage_service,
    )

    request = _request(project_id="p1", session_id="s1")
    request = replace(request, usage_message_id="msg-assistant")

    asyncio.run(service.complete(request))

    assert usage_service.records[0]["message_id"] == "msg-assistant"


def test_complete_skips_usage_when_disabled():
    usage_service = _FakeUsageService()
    service = _build_service(
        remote_client=_FakeRemoteClient(
            complete_result=ChatCompletionResult(
                provider_id="deepseek",
                model_id="deepseek-v4",
                message=ChatMessage(role=ChatMessageRole.ASSISTANT, content="ok"),
                usage=ChatUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            ),
        ),
        usage_service=usage_service,
    )

    request = _request(project_id="p1", session_id="s1")
    request = replace(request, record_usage=False)

    asyncio.run(service.complete(request))

    assert usage_service.records == []


def test_stream_records_usage_in_chat_service_layer():
    usage = ChatUsage(prompt_tokens=7, completion_tokens=11, total_tokens=18)
    usage_service = _FakeUsageService()
    service = _build_service(
        remote_client=_FakeRemoteClient(
            stream_events=(
                ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content="ok"),
                ChatStreamEvent(kind=ChatStreamEventKind.USAGE, usage=usage),
                ChatStreamEvent(kind=ChatStreamEventKind.DONE),
            ),
        ),
        usage_service=usage_service,
    )

    events = asyncio.run(_collect_stream(service, _request(project_id="p1", session_id="s1")))

    assert [event.kind for event in events] == [
        ChatStreamEventKind.DELTA,
        ChatStreamEventKind.USAGE,
        ChatStreamEventKind.DONE,
    ]
    assert usage_service.records == [
        {
            "project_id": "p1",
            "session_id": "s1",
            "message_id": None,
            "provider_id": "deepseek",
            "model_id": "deepseek-v4",
            "usage": usage,
            "usage_feature_key": "main_chat",
        }
    ]


def test_complete_estimates_missing_provider_usage():
    usage_service = _FakeUsageService()
    service = _build_service(
        remote_client=_FakeRemoteClient(
            complete_result=ChatCompletionResult(
                provider_id="deepseek",
                model_id="deepseek-v4",
                message=ChatMessage(role=ChatMessageRole.ASSISTANT, content="本地估算"),
                usage=None,
            ),
        ),
        usage_service=usage_service,
    )

    result = asyncio.run(service.complete(_request(project_id="p1", session_id="s1")))

    assert result.usage is not None
    assert result.usage.prompt_tokens > 0
    assert result.usage.completion_tokens > 0
    assert result.usage.total_tokens == (
        result.usage.prompt_tokens + result.usage.completion_tokens
    )
    assert set(result.usage.estimated_fields) == {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    }
    assert usage_service.records[0]["usage"] == result.usage


def test_stream_estimates_missing_provider_usage_before_done():
    usage_service = _FakeUsageService()
    service = _build_service(
        remote_client=_FakeRemoteClient(
            stream_events=(
                ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content="ok"),
                ChatStreamEvent(kind=ChatStreamEventKind.DONE),
            ),
        ),
        usage_service=usage_service,
    )

    events = asyncio.run(_collect_stream(service, _request(project_id="p1", session_id="s1")))

    assert [event.kind for event in events] == [
        ChatStreamEventKind.DELTA,
        ChatStreamEventKind.USAGE,
        ChatStreamEventKind.DONE,
    ]
    usage = events[1].usage
    assert usage is not None
    assert "prompt_tokens" in usage.estimated_fields
    assert usage_service.records[0]["usage"] == usage


def test_stream_retries_same_logical_request_after_incomplete_upstream_attempt():
    recorder = _FakeExchangeRecorder()
    remote_client = _SequencedRemoteClient(
        stream_attempts=(
            (ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content="partial"),),
            (
                ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content="ok"),
                ChatStreamEvent(kind=ChatStreamEventKind.DONE),
            ),
        )
    )
    service = _build_service(
        remote_client=remote_client,
        usage_service=_FakeUsageService(),
        http_exchange_recorder=recorder,
    )
    request = replace(
        _request(project_id="p1", session_id="s1"),
        upstream_retry_count=1,
    )

    events = asyncio.run(_collect_stream(service, request))

    assert [event.kind for event in events] == [
        ChatStreamEventKind.DELTA,
        ChatStreamEventKind.RETRY_RESET,
        ChatStreamEventKind.DELTA,
        ChatStreamEventKind.USAGE,
        ChatStreamEventKind.DONE,
    ]
    assert [(item.upstream_attempt_index, item.upstream_attempt_count) for item in remote_client.requests] == [
        (1, 2),
        (2, 2),
    ]
    assert [item["status"] for item in recorder.attempts] == ["failed", "completed"]
    assert recorder.attempts[0]["error_code"] == "upstream_stream_incomplete"


def test_stream_retry_preserves_provider_http_error_body():
    recorder = _FakeExchangeRecorder()
    upstream_request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    upstream_response = httpx.Response(
        402,
        request=upstream_request,
        json={"error": {"message": "Insufficient Balance"}},
    )
    remote_client = _SequencedRemoteClient(
        stream_attempts=(
            httpx.HTTPStatusError(
                "402 Payment Required",
                request=upstream_request,
                response=upstream_response,
            ),
            (
                ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content="ok"),
                ChatStreamEvent(kind=ChatStreamEventKind.DONE),
            ),
        )
    )
    service = _build_service(
        remote_client=remote_client,
        usage_service=_FakeUsageService(),
        http_exchange_recorder=recorder,
    )
    request = replace(
        _request(project_id="p1", session_id="s1"),
        upstream_retry_count=1,
    )

    events = asyncio.run(_collect_stream(service, request))

    retry_event = next(event for event in events if event.kind == ChatStreamEventKind.RETRY_RESET)
    assert retry_event.error_code == "upstream_http_error"
    assert retry_event.error == '{"error":{"message":"Insufficient Balance"}}'
    assert recorder.attempts[0]["error_code"] == retry_event.error_code
    assert recorder.attempts[0]["error_message"] == retry_event.error


def test_complete_retries_transport_failure_without_changing_logical_messages():
    recorder = _FakeExchangeRecorder()
    result = ChatCompletionResult(
        provider_id="deepseek",
        model_id="deepseek-v4",
        message=ChatMessage(role=ChatMessageRole.ASSISTANT, content="ok"),
    )
    remote_client = _SequencedRemoteClient(
        complete_attempts=(TimeoutError("temporary timeout"), result),
    )
    service = _build_service(
        remote_client=remote_client,
        usage_service=_FakeUsageService(),
        http_exchange_recorder=recorder,
    )
    request = replace(
        _request(project_id="p1", session_id="s1"),
        upstream_retry_count=1,
    )

    completed = asyncio.run(service.complete(request))

    assert completed.message.content == "ok"
    assert len(remote_client.requests) == 2
    assert remote_client.requests[0].messages == remote_client.requests[1].messages
    assert [item["status"] for item in recorder.attempts] == ["failed", "completed"]


def test_complete_retries_empty_upstream_result():
    recorder = _FakeExchangeRecorder()
    completed_result = ChatCompletionResult(
        provider_id="deepseek",
        model_id="deepseek-v4",
        message=ChatMessage(role=ChatMessageRole.ASSISTANT, content="ok"),
    )
    remote_client = _SequencedRemoteClient(
        complete_attempts=(None, completed_result),
    )
    service = _build_service(
        remote_client=remote_client,
        usage_service=_FakeUsageService(),
        http_exchange_recorder=recorder,
    )
    request = replace(
        _request(project_id="p1", session_id="s1"),
        upstream_retry_count=1,
    )

    completed = asyncio.run(service.complete(request))

    assert completed.message.content == "ok"
    assert len(remote_client.requests) == 2
    assert [item["status"] for item in recorder.attempts] == ["failed", "completed"]
    assert recorder.attempts[0]["error_code"] == "RuntimeError"


def test_stream_exhausts_retries_before_exposing_incomplete_response_error():
    recorder = _FakeExchangeRecorder()
    remote_client = _SequencedRemoteClient(
        stream_attempts=(
            (ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content="first partial"),),
            (ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content="second partial"),),
        )
    )
    service = _build_service(
        remote_client=remote_client,
        usage_service=_FakeUsageService(),
        http_exchange_recorder=recorder,
    )
    request = replace(
        _request(project_id="p1", session_id="s1"),
        upstream_retry_count=1,
    )

    events = asyncio.run(_collect_stream(service, request))

    assert [event.kind for event in events] == [
        ChatStreamEventKind.DELTA,
        ChatStreamEventKind.RETRY_RESET,
        ChatStreamEventKind.DELTA,
        ChatStreamEventKind.ERROR,
    ]
    assert events[-1].error_code == "upstream_stream_incomplete"
    assert [item["status"] for item in recorder.attempts] == ["failed", "failed"]


def test_cancelled_upstream_request_is_never_retried():
    recorder = _FakeExchangeRecorder()
    remote_client = _SequencedRemoteClient(
        complete_attempts=(asyncio.CancelledError(),),
    )
    service = _build_service(
        remote_client=remote_client,
        usage_service=_FakeUsageService(),
        http_exchange_recorder=recorder,
    )
    request = replace(
        _request(project_id="p1", session_id="s1"),
        upstream_retry_count=5,
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(service.complete(request))

    assert len(remote_client.requests) == 1
    assert [item["status"] for item in recorder.attempts] == ["cancelled"]


def test_session_usage_summary_groups_same_model_by_feature(tmp_path):
    repository = LlmUsageRepository(tmp_path / "usage")

    repository.record_usage(
        project_id="p1",
        session_id="s1",
        message_id="msg-main",
        provider_id="deepseek",
        model_id="deepseek-v4",
        usage=ChatUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        usage_feature_key="main_chat",
        is_estimated=True,
    )
    repository.record_usage(
        project_id="p1",
        session_id="s1",
        message_id="system:naming:p1:s1",
        provider_id="deepseek",
        model_id="deepseek-v4",
        usage=ChatUsage(prompt_tokens=4, completion_tokens=5, total_tokens=9),
        usage_feature_key="conversation_naming",
    )
    repository.record_usage(
        project_id="p1",
        session_id="s1",
        message_id="system:memory_compression:p1:s1",
        provider_id="deepseek",
        model_id="deepseek-v4",
        usage=ChatUsage(prompt_tokens=6, completion_tokens=7, total_tokens=13),
        usage_feature_key="memory_compression",
    )

    summary = repository.get_session_summary(project_id="p1", session_id="s1")

    assert [(item.model_id, item.usage_feature_key) for item in summary.by_models] == [
        ("deepseek-v4", "memory_compression"),
        ("deepseek-v4", "conversation_naming"),
        ("deepseek-v4", "main_chat"),
    ]
    assert {
        item.usage_feature_key: item.usage_feature_display_name
        for item in summary.by_models
    } == {
        "main_chat": "主会话",
        "conversation_naming": "会话命名模型",
        "memory_compression": "记忆压缩模型",
    }
    assert summary.total.estimated_record_count == 1
    assert next(
        item for item in summary.by_models if item.usage_feature_key == "main_chat"
    ).estimated_record_count == 1


def test_session_totals_only_include_requested_sessions(tmp_path):
    repository = LlmUsageRepository(tmp_path / "usage")
    repository.record_usage(
        project_id="p1",
        session_id="s1",
        message_id="msg-s1",
        provider_id="deepseek",
        model_id="deepseek-v4",
        usage=ChatUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    repository.record_usage(
        project_id="p1",
        session_id="s2",
        message_id="msg-s2",
        provider_id="deepseek",
        model_id="deepseek-v4",
        usage=ChatUsage(prompt_tokens=2, completion_tokens=3, total_tokens=5),
    )
    repository.record_usage(
        project_id="p1",
        session_id="deleted-session",
        message_id="msg-deleted",
        provider_id="deepseek",
        model_id="deepseek-v4",
        usage=ChatUsage(prompt_tokens=100, completion_tokens=100, total_tokens=200),
    )

    summaries = repository.get_session_totals(project_id="p1", session_ids=("s1", "s2"))

    assert set(summaries) == {"s1", "s2"}
    assert summaries["s1"].total_tokens == 15
    assert summaries["s2"].prompt_tokens == 2


def test_provider_usage_summary_includes_model_feature_breakdown(tmp_path):
    repository = LlmUsageRepository(tmp_path / "usage")
    repository.record_usage(
        project_id=None,
        session_id=None,
        message_id="msg-main",
        provider_id="deepseek",
        model_id="deepseek-v4",
        usage=ChatUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        usage_feature_key="main_chat",
    )
    repository.record_usage(
        project_id=None,
        session_id=None,
        message_id="system:memory_compression:p1:s1",
        provider_id="deepseek",
        model_id="deepseek-v4",
        usage=ChatUsage(prompt_tokens=4, completion_tokens=5, total_tokens=9),
        usage_feature_key="memory_compression",
    )

    summary = repository.get_model_summaries(provider_id="deepseek")[0]

    assert summary.total_tokens == 12
    assert [(item.usage_feature_key, item.usage_feature_display_name) for item in summary.by_features] == [
        ("memory_compression", "记忆压缩模型"),
        ("main_chat", "主会话"),
    ]


def test_usage_service_passes_feature_key_without_breaking_cost_calculation():
    repository = _FakeUsageRepositoryForUsageService()
    service = LlmUsageService(
        repository,
        _FakeProjectRepositoryForUsageService(),
        _FakeProviderCatalogRepositoryForUsageService(),
        _FakeCustomModelRepositoryForUsageService(),
    )

    service.record_message_usage(
        project_id="p1",
        session_id="s1",
        message_id="system:memory_compression:p1:s1",
        provider_id="deepseek",
        model_id="deepseek-v4",
        usage=ChatUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        usage_feature_key="memory_compression",
    )

    assert repository.records[0]["usage_feature_key"] == "memory_compression"
    assert repository.records[0]["cost_amount"] == 0.00005
    assert repository.records[0]["cost_currency"] == "CNY"
    assert repository.records[0]["is_estimated"] is False


def test_usage_service_marks_estimated_usage_record():
    repository = _FakeUsageRepositoryForUsageService()
    service = LlmUsageService(
        repository,
        _FakeProjectRepositoryForUsageService(),
        _FakeProviderCatalogRepositoryForUsageService(),
        _FakeCustomModelRepositoryForUsageService(),
    )

    service.record_message_usage(
        project_id="p1",
        session_id="s1",
        message_id="msg-estimated",
        provider_id="deepseek",
        model_id="deepseek-v4",
        usage=ChatUsage(
            prompt_tokens=10,
            completion_tokens=2,
            total_tokens=12,
            estimated_fields=("prompt_tokens",),
        ),
    )

    assert repository.records[0]["is_estimated"] is True


def _build_service(*, remote_client, usage_service, http_exchange_recorder=None):
    return ChatCompletionService(
        _FakeCatalogRepository(),
        _FakeConfigRepository(),
        remote_client,
        _FakeApiKeyScheduler(),
        usage_service,
        _FakeTokenEstimationSettingsService(),
        http_exchange_recorder,
    )


def _request(*, project_id: str | None, session_id: str | None) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        provider_id="deepseek",
        model_id="deepseek-v4",
        project_id=project_id,
        session_id=session_id,
        messages=(ChatMessage(role=ChatMessageRole.USER, content="hi"),),
    )


async def _collect_stream(service: ChatCompletionService, request: ChatCompletionRequest):
    return [event async for event in service.stream(request)]


class _FakeCatalogRepository:
    def get_entry(self, provider_id: str):
        return ProviderCatalogEntry(
            provider_id=provider_id,
            display_name="DeepSeek",
            profile_id="deepseek",
            protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE,
            generation_auth_schemes={
                ProviderProtocolFamily.OPENAI_COMPATIBLE: AuthScheme.BEARER_TOKEN
            },
            model_discovery_strategy=default_model_discovery_strategy(
                ProviderProtocolFamily.OPENAI_COMPATIBLE
            ),
            model_discovery_auth_scheme=AuthScheme.BEARER_TOKEN,
            endpoints=ProviderEndpointTemplate(
                api_base_url="https://example.test",
                text_generation_url_template="chat/completions",
                model_discovery_url=None,
            ),
        )


class _FakeConfigRepository:
    def get_config(self, provider_id: str):
        return ProviderConfig(
            provider_id=provider_id,
            api_base_url="https://example.test",
            enabled=True,
            api_keys=(
                ProviderApiKeyConfig(
                    key_id="key-1",
                    provider_id=provider_id,
                    api_key_hint="***",
                    api_key_ciphertext="ciphertext",
                    poll_weight=1,
                    sort_order=0,
                    created_at="now",
                    updated_at="now",
                ),
            ),
            created_at="now",
            updated_at="now",
        )


class _FakeRemoteClient:
    def __init__(
        self,
        *,
        complete_result: ChatCompletionResult | None = None,
        stream_events: tuple[ChatStreamEvent, ...] = (),
    ) -> None:
        self._complete_result = complete_result
        self._stream_events = stream_events

    async def complete(self, **_kwargs):
        return self._complete_result

    async def stream(self, **_kwargs):
        for event in self._stream_events:
            yield event


class _SequencedRemoteClient:
    def __init__(self, *, complete_attempts=(), stream_attempts=()) -> None:
        self._complete_attempts = list(complete_attempts)
        self._stream_attempts = list(stream_attempts)
        self.requests: list[ChatCompletionRequest] = []

    async def complete(self, **kwargs):
        self.requests.append(kwargs["request"])
        outcome = self._complete_attempts.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def stream(self, **kwargs):
        self.requests.append(kwargs["request"])
        outcome = self._stream_attempts.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        for event in outcome:
            yield event


class _FakeExchangeRecorder:
    def __init__(self) -> None:
        self.attempts: list[dict[str, object]] = []

    async def record_http_exchange(self, _request, _exchange) -> None:
        return None

    def record_attempt_outcome(self, request, **outcome) -> None:
        self.attempts.append(
            {
                "attempt_index": request.upstream_attempt_index,
                "attempt_count": request.upstream_attempt_count,
                **outcome,
            }
        )


class _FakeApiKeyScheduler:
    def select_next(self, provider_id: str, candidates):
        return ProviderRuntimeApiKey(
            key_id="key-1",
            api_key="sk-test",
            api_key_hint="***",
            poll_weight=1,
        )


class _FakeUsageService:
    def __init__(self) -> None:
        self.records = []

    def record_message_usage(self, **kwargs):
        self.records.append(kwargs)


class _FailingUsageService:
    def record_message_usage(self, **_kwargs):
        raise OSError("usage storage unavailable")


class _FakeTokenEstimationSettingsService:
    def get_settings(self):
        return DEFAULT_TOKEN_ESTIMATION_SETTINGS


class _FakeUsageRepositoryForUsageService:
    def __init__(self) -> None:
        self.records = []

    def record_usage(self, **kwargs):
        self.records.append(kwargs)
        return kwargs


class _FakeProjectRepositoryForUsageService:
    def get_project(self, _project_id):
        return object()


class _FakeProviderCatalogRepositoryForUsageService:
    def list_entries(self):
        return ()


class _FakeCustomModelRepositoryForUsageService:
    def get_model(self, *, provider_id: str, model_id: str):
        return ProviderCustomModel(
            provider_id=provider_id,
            model_id=model_id,
            display_name=model_id,
            family_group="test",
            price_currency="CNY",
            input_price_per_million=1,
            output_price_per_million=2,
        )
