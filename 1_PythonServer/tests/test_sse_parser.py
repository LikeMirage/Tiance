import asyncio
from contextlib import aclosing
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import UpstreamProviderError
from app.domain.llm.chat import ChatCompletionRequest, ChatStreamEventKind
from app.domain.llm.provider_catalog import ProviderProtocolFamily
from app.domain.llm.response_body import body_chunks
from app.infra.llm import chat_remote_client as remote
from app.infra.llm.chat_adapters import sse
from app.infra.llm.response_capture import ResponseCapture
from app.services.llm.chat.service import _attempt_error
from tests.test_llm_protocol_continuation import _provider, _runtime


async def source(parts, closed=None):
    try:
        for part in parts:
            yield part
    finally:
        if closed is not None:
            closed.append(True)


def parse(parts):
    closed = []
    async def run():
        result = [p async for p in sse._iter_sse_payloads(source(parts, closed))]
        assert closed == [True]
        return result
    return asyncio.run(run())


def set_limit(monkeypatch, limit):
    monkeypatch.setattr(sse, 'get_settings', lambda: SimpleNamespace(llm_sse_max_event_bytes=limit))


@pytest.mark.parametrize('newline', [b'\n', b'\r\n', b'\r'])
@pytest.mark.parametrize('width', [1, 2, 7, 65536])
@pytest.mark.parametrize('bom', [b'', b'\xef\xbb\xbf'])
def test_chunk_boundaries_unicode_multiline_and_done(newline, width, bom):
    raw = bom + newline.join([
        b': heartbeat', b'event: message', b'id: ignored', b'data: {"text":',
        'data: "中文🙂"}'.encode(), b'', b'data:  [DONE]  ', b'',
        b'data: {"ignored":true}', b'', b'',
    ])
    assert parse([raw[i:i+width] for i in range(0, len(raw), width)]) == [{'text': '中文🙂'}, sse.SSE_DONE]


@pytest.mark.parametrize('ending', [b'', b'\n', b'\r', b'\r\n'])
def test_existing_eof_compatibility(ending):
    assert parse([b'data: {"text":"last event"}' + ending]) == [{'text': 'last event'}]
    assert parse([b'data: [DONE]' + ending]) == [sse.SSE_DONE]


@pytest.mark.parametrize('raw', [b'garbage', b'{"partial":', b'[]', b'null', b'', b'"\xff"', b'[' * 3000])
def test_malformed_data_remains_explicit_protocol_failure(raw):
    assert parse([b'data: ' + raw + b'\n\n']) == [None]


def test_empty_data_without_colon_is_an_event():
    assert parse([b'data\n\n']) == [None]


def test_unicode_line_separators_inside_json_are_not_sse_delimiters():
    expected = {'text': '甲\u0085乙\u2028丙\u2029丁'}
    raw = b'data: ' + json.dumps(expected, ensure_ascii=False).encode() + b'\n\n'
    assert parse([raw]) == [expected]


def test_crlf_split_across_internal_scan_blocks():
    prefix, suffix = b'data: {"text":"', b'"}'
    value = b'x' * (65535 - len(prefix) - len(suffix))
    raw = prefix + value + suffix + b'\r\n\r\ndata: [DONE]\r\n\r\n'
    assert parse([raw]) == [{'text': value.decode()}, sse.SSE_DONE]


@pytest.mark.parametrize('extra', [0, 1])
def test_exact_line_limit(monkeypatch, extra):
    set_limit(monkeypatch, 64)
    prefix, suffix = b'data: {"text":"', b'"}'
    value = b'x' * (64 - len(prefix) - len(suffix) + extra)
    line = prefix + value + suffix
    assert len(line) == 64 + extra
    if extra:
        with pytest.raises(UpstreamProviderError):
            parse([line + b'\n\n'])
    else:
        assert parse([line + b'\n\n']) == [{'text': value.decode()}]


def test_large_valid_event_preserved_beyond_audit_spill_threshold():
    expected = 'x' * (16 * 1024 * 1024)
    raw = b'data: ' + json.dumps({'text': expected}).encode() + b'\n\n'
    assert parse([raw[i:i+16384] for i in range(0, len(raw), 16384)]) == [{'text': expected}]


def test_limit_is_not_a_total_response_limit(monkeypatch):
    set_limit(monkeypatch, 64)
    assert parse([b'data: {"n":1}\n\n' * 10000]) == [{'n': 1}] * 10000


@pytest.mark.parametrize('parts,unit', [
    ([b'data: "', b'x' * 40, b'x' * 40, b'"\n\n'], '单行'),
    ([b': ' + b'x' * 65], '单行'),
    ([b'data: ' + b'x' * 40 + b'\n', b'data: ' + b'x' * 40 + b'\n'], '单条事件'),
    ([b'data:\n' * 66], '单条事件'),
])
def test_unfinished_line_or_event_fails_and_closes(monkeypatch, parts, unit):
    set_limit(monkeypatch, 64)
    closed = []
    async def run():
        with pytest.raises(UpstreamProviderError) as caught:
            async for _ in sse._iter_sse_payloads(source(parts, closed)):
                pytest.fail('No incomplete payload may be emitted')
        assert caught.value.code == 'upstream_stream_event_too_large'
        assert caught.value.details['unit'] == unit
        assert caught.value.details['limit_bytes'] == 64
        assert caught.value.details['observed_bytes'] > 64
        assert 'LLM_SSE_MAX_EVENT_BYTES' in str(caught.value)
        assert closed == [True]
    asyncio.run(run())


@pytest.mark.parametrize('extra', [0, 1])
def test_exact_multiline_event_limit(monkeypatch, extra):
    set_limit(monkeypatch, 64)
    # The joined JSON is exactly 64 (+ extra) bytes, each wire line is smaller.
    raw = b'data: {"text":\ndata: "' + b'x' * (52 + extra) + b'"}\n\n'
    if extra:
        with pytest.raises(UpstreamProviderError):
            parse([raw])
    else:
        assert parse([raw]) == [{'text': 'x' * 52}]


@pytest.mark.parametrize('kind', ['long-line', 'many-events', 'comments', 'empty-chunks'])
def test_ready_input_yields_for_cancellation_and_closes(kind):
    closed, consumed, emitted = [], [], []
    if kind == 'long-line':
        parts = [b'data: {"text":"'] + [b'x' * 16384] * 512 + [b'"}\n\n']
    elif kind == 'many-events':
        parts = [b'data: {"n":1}\n\n' * 10000]
    elif kind == 'comments':
        parts = [b': heartbeat\n' * 10000]
    else:
        parts = [b''] * 10000
    async def chunks():
        try:
            for part in parts:
                consumed.append(len(part))
                yield part
        finally:
            closed.append(True)
    async def run():
        async def consume():
            async for payload in sse._iter_sse_payloads(chunks()):
                emitted.append(payload)
        task = asyncio.create_task(consume())
        # A ready async generator must not starve this second task.
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed == [True]
        if kind == 'long-line':
            assert len(consumed) < len(parts) and not emitted
        if kind == 'many-events':
            assert len(emitted) < 10000
    asyncio.run(run())


def test_downstream_close_closes_source_immediately():
    closed = []
    async def run():
        async with aclosing(sse._iter_sse_payloads(source([b'data: {}\n\n' * 20], closed))) as stream:
            assert await anext(stream) == {}
        assert closed == [True]
    asyncio.run(run())


@pytest.mark.parametrize('value', ['0', '-1', 'not-a-number'])
def test_invalid_config_is_rejected(monkeypatch, value):
    monkeypatch.setenv('LLM_SSE_MAX_EVENT_BYTES', value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_protection_config_can_be_raised(monkeypatch):
    monkeypatch.setenv('LLM_SSE_MAX_EVENT_BYTES', str(128 * 1024 * 1024))
    assert Settings(_env_file=None).llm_sse_max_event_bytes == 128 * 1024 * 1024


@pytest.mark.parametrize('family', list(ProviderProtocolFamily))
@pytest.mark.parametrize('malformed', [False, True], ids=['oversized', 'invalid-json'])
def test_all_protocols_close_transport_and_preserve_received_audit(monkeypatch, family, malformed):
    set_limit(monkeypatch, 64)
    sent, closed, captured, audits = [], [], [], []
    parts = [b'data: {broken}\n\n'] if malformed else [b'data: "', b'x' * 48, b'y' * 48]
    class Response:
        is_error = False
        status_code = 200
        headers = {}
        async def __aenter__(self): return self
        async def __aexit__(self, *args): closed.append(True)
        def raise_for_status(self): pass
        async def aiter_bytes(self):
            for part in parts:
                sent.append(part)
                yield part
            pytest.fail('The parser must stop without draining the rest of an invalid stream')
    class Client:
        def stream(self, *args, **kwargs): return Response()
    def factory():
        capture = ResponseCapture(memory_limit=16)
        captured.append(capture)
        return capture
    monkeypatch.setattr(remote, 'get_shared_http_client', lambda: Client())
    monkeypatch.setattr(remote, 'get_http_timeout', lambda **kwargs: None)
    monkeypatch.setattr(remote, 'ResponseCapture', factory)
    async def record(request, exchange):
        audits.append(b''.join(body_chunks(exchange.response_body)))
    async def run():
        events = []
        try:
            async for event in remote.ChatRemoteClient().stream(
                provider_template=_provider(family, 'synthetic'), runtime_config=_runtime('synthetic'),
                api_key='synthetic', request=ChatCompletionRequest(provider_id='synthetic', model_id='synthetic', messages=()),
                on_exchange=record,
            ):
                events.append(event)
        except UpstreamProviderError as error:
            assert not malformed
            assert _attempt_error(error)[0] == 'upstream_stream_event_too_large'
        else:
            assert malformed
            assert events[-1].error_code == 'upstream_stream_protocol_error'
        assert all(event.kind != ChatStreamEventKind.DONE for event in events)
        assert closed == [True]
        assert audits == [b''.join(sent)] == [b''.join(parts)]
        assert captured[0].closed
    asyncio.run(run())
