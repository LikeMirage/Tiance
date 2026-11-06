import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from app.domain.llm.chat import ChatCompletionResult, ChatMessage, ChatMessageRole, ChatStreamEvent, ChatStreamEventKind
from app.services.llm.chat import retry, service as service_module
from app.services.llm.provider import config_runtime
from app.schemas.llm.chat import ChatCompletionRequestBody
from pydantic import ValidationError
from tests import test_chat_usage_recording as support


def upstream_error(header=None):
    request = httpx.Request("POST", "https://example.test/responses")
    response = httpx.Response(429, request=request, json={"error": "capacity"},
                              headers={"Retry-After": header} if header is not None else {})
    return httpx.HTTPStatusError("capacity", request=request, response=response)


def test_request_contract_preserves_zero_and_rejects_negative_interval():
    payload = {"provider_id": "deepseek", "model_id": "deepseek-v4"}
    assert ChatCompletionRequestBody(**payload).to_domain().upstream_retry_interval_seconds == 5
    assert ChatCompletionRequestBody(**payload, upstream_retry_interval_seconds=0).to_domain().upstream_retry_interval_seconds == 0
    with pytest.raises(ValidationError):
        ChatCompletionRequestBody(**payload, upstream_retry_interval_seconds=-1)


@pytest.mark.parametrize(("header", "expected"), [
    ("5", 5), ("0", 0), ("-8", 0), (None, 0), ("bad", 0),
    ("nan", 0), ("inf", 0), ("1e309", 0),
    ("Fri, 06 Nov 2026 02:06:16 GMT", 5),
    ("Fri, 06 Nov 2026 02:06:10 GMT", 0),
])
def test_standard_retry_after(header, expected):
    assert retry.retry_after_seconds(upstream_error(header), now=datetime(2026, 11, 6, 2, 6, 11, tzinfo=UTC)) == expected
    assert retry.retry_after_seconds(TimeoutError()) == 0


@pytest.mark.parametrize(("configured", "provider", "expected"), [(2, 5, [5]), (17, 5, [17]), (0, 0, []), (0, 5, [5])])
def test_wait_uses_larger_interval_without_hidden_backoff(monkeypatch, configured, provider, expected):
    delays = []
    async def sleep(seconds):
        delays.append(seconds)
    monkeypatch.setattr(retry, "asyncio", SimpleNamespace(sleep=sleep))
    asyncio.run(retry.wait_for_upstream_retry(configured, provider))
    assert delays == expected


@pytest.fixture(autouse=True)
def decrypt_test_key(monkeypatch):
    monkeypatch.setattr(config_runtime, "resolve_api_key_secret", lambda _key: "sk-test")


def setup_attempts(streaming, failure=None):
    result = ChatCompletionResult(provider_id="deepseek", model_id="deepseek-v4",
                                  message=ChatMessage(role=ChatMessageRole.ASSISTANT, content="ok"))
    success = (ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content="ok"),
               ChatStreamEvent(kind=ChatStreamEventKind.DONE)) if streaming else result
    attempts = (failure or upstream_error("5"), success)
    remote = support._SequencedRemoteClient(**{"stream_attempts" if streaming else "complete_attempts": attempts})
    recorder = support._FakeExchangeRecorder()
    service = support._build_service(remote_client=remote, usage_service=support._FakeUsageService(), http_exchange_recorder=recorder)
    request = replace(support._request(project_id="p", session_id="s"), upstream_retry_interval_seconds=9)
    async def consume(req=request):
        return await support._collect_stream(service, req) if streaming else await service.complete(req)
    return remote, recorder, request, consume


@pytest.mark.parametrize("streaming", [False, True])
def test_retry_waits_between_attempts_and_preserves_request(monkeypatch, streaming):
    remote, recorder, request, consume = setup_attempts(streaming)
    waits = []
    async def wait(configured, provider):
        assert len(remote.requests) == 1
        assert [a["status"] for a in recorder.attempts] == ["failed"]
        waits.append((configured, provider))
    monkeypatch.setattr(service_module, "wait_for_upstream_retry", wait)
    asyncio.run(consume())
    assert waits == [(9, 5)]
    assert len(remote.requests) == 2
    assert remote.requests[0].messages == remote.requests[1].messages == request.messages
    assert [a["status"] for a in recorder.attempts] == ["failed", "completed"]


@pytest.mark.parametrize("streaming", [False, True])
def test_no_wait_or_extra_request_when_retries_disabled(monkeypatch, streaming):
    remote, recorder, request, consume = setup_attempts(streaming)
    async def unexpected_wait(*_):
        pytest.fail("No wait after the final attempt")
    monkeypatch.setattr(service_module, "wait_for_upstream_retry", unexpected_wait)
    async def run():
        if streaming:
            events = await consume(replace(request, upstream_retry_count=0))
            assert events[-1].kind == ChatStreamEventKind.ERROR
        else:
            with pytest.raises(httpx.HTTPStatusError):
                await consume(replace(request, upstream_retry_count=0))
    asyncio.run(run())
    assert len(remote.requests) == 1


@pytest.mark.parametrize("streaming", [False, True])
def test_cancel_during_wait_never_sends_next_attempt(monkeypatch, streaming):
    remote, recorder, request, consume = setup_attempts(streaming)
    async def run():
        entered = asyncio.Event()
        async def wait(configured, provider):
            entered.set()
            await retry.wait_for_upstream_retry(configured, provider)
        monkeypatch.setattr(service_module, "wait_for_upstream_retry", wait)
        task = asyncio.create_task(consume())
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert not task.done()  # The event loop remains available while waiting.
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
    asyncio.run(run())
    assert len(remote.requests) == 1
    assert [a["status"] for a in recorder.attempts] == ["failed"]
