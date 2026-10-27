from __future__ import annotations

import asyncio
from base64 import b64encode
from hashlib import sha256
import json
import sqlite3
import threading
import tracemalloc

import pytest

from app.domain.llm.chat import ChatCompletionRequest
from app.domain.llm.chat_http_exchange import ChatHttpExchange, exchange_payload
from app.domain.llm.response_body import body_chunks
from app.infra.llm import chat_remote_client as remote
from app.infra.llm.response_capture import ResponseCapture, RESPONSE_MEMORY_LIMIT
from app.repositories.project.conversation_audit_delta import json_bytes
from app.repositories.project.conversation_audit_snapshots import (
    create_audit_snapshot_schema, restore_audit_snapshot, store_prepared_audit_snapshot,
)
from app.repositories.project.conversation_audit_streaming import (
    AuditText, iter_json_bytes, prepare_audit_snapshot, response_text,
)


def connection():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE conversation_sessions(session_id TEXT PRIMARY KEY)")
    db.execute("INSERT INTO conversation_sessions VALUES ('session')")
    create_audit_snapshot_schema(db)
    return db


@pytest.mark.parametrize("value", [
    {"text": ('汉字🙂\n\r\t\b\f\0\\\"' * 4000), "float": 1.0, "bool": True, "none": None},
    {1: [False, 12.25, "短文"], None: {}, False: ()},
], ids=['unicode-escapes', 'mixed-values'])
def test_chunked_json_is_byte_identical(value):
    assert b"".join(iter_json_bytes(value)) == json_bytes(value)


@pytest.mark.parametrize("raw", [b"", b"short", b"a" * 65535 + '🙂汉字'.encode() * 1000,
                                  b"x" * 65535 + b"\xff\x80tail", b"x" * 65535 + b"\xf0\x9f"],
                         ids=['empty', 'short', 'split-unicode', 'invalid-utf8', 'incomplete-utf8'])
def test_raw_body_roundtrip_and_checksums(raw):
    capture = ResponseCapture(memory_limit=1024)
    capture.write(raw)
    capture.seal()
    encoding, text = response_text(capture)
    try:
        expected_text = raw.decode("utf-8")
        expected_encoding = "utf-8"
    except UnicodeDecodeError:
        expected_text, expected_encoding = b64encode(raw).decode(), "base64"
    assert encoding == expected_encoding
    payload = {"response": {"encoding": encoding, "body": text}, "request": {"tools": [{"value": "x" * 3000}]}}
    expected = {"response": {"encoding": encoding, "body": expected_text}, "request": payload['request']}
    db = connection()
    try:
        with prepare_audit_snapshot(payload) as prepared:
            assert prepared.digest == sha256(json_bytes(expected)).hexdigest()
            assert prepared.size_bytes == len(json_bytes(expected))
            manifest = store_prepared_audit_snapshot(db, 'session', 'model_http_exchange', prepared)
        assert restore_audit_snapshot(db, 'session', 'model_http_exchange', manifest) == expected
    finally:
        capture.release()
        db.close()
    assert capture.closed


def test_large_disk_body_preparation_has_bounded_python_memory():
    capture = ResponseCapture()
    chunk = b'data: {"delta":"' + b"x" * 16384 + b'"}\n\n'
    for _ in range(2048):
        capture.write(chunk)
    capture.seal()
    assert capture.size_bytes > 32 * 1024**2
    assert capture._file._rolled
    tracemalloc.start()
    try:
        encoding, text = response_text(capture)
        with prepare_audit_snapshot({"body": text}) as prepared:
            assert prepared.size_bytes > capture.size_bytes
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
        capture.release()
    assert encoding == 'utf-8'
    assert peak < 3 * 1024**2, peak


@pytest.mark.parametrize("size,rolled", [(4 * 1024**2, False), (9 * 1024**2, True)])
def test_stream_transfers_owned_buffer_without_materializing(monkeypatch, size, rolled):
    captures = []
    retained = []

    def capture_factory():
        capture = ResponseCapture()
        captures.append(capture)
        return capture

    class Response:
        is_error = False
        status_code = 200
        headers = {}
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def raise_for_status(self): pass
        async def aiter_bytes(self):
            for _ in range(size // 4096):
                yield b"x" * 4096

    class Client:
        def stream(self, *args, **kwargs): return Response()

    async def record(request, exchange):
        exchange.response_body.retain()
        retained.append(exchange.response_body)

    monkeypatch.setattr(remote, 'ResponseCapture', capture_factory)
    monkeypatch.setattr(remote, 'get_shared_http_client', lambda: Client())
    monkeypatch.setattr(remote, 'get_http_timeout', lambda **kwargs: None)

    async def run():
        request = ChatCompletionRequest(provider_id='provider', model_id='model', messages=())
        count = 0
        async for chunk in remote.ChatRemoteClient()._stream_body('https://test.invalid', {}, {}, request=request, on_exchange=record):
            count += len(chunk)
        assert count == size
        body = retained[0]
        assert body is captures[0]
        assert not body.closed
        assert body._file._rolled is rolled
        assert sum(map(len, body_chunks(body))) == size
        body.release()
        assert body.closed

    asyncio.run(run())
    assert RESPONSE_MEMORY_LIMIT == 8 * 1024**2


def test_capture_is_released_when_recorder_raises(monkeypatch):
    async def fail(*args): raise RuntimeError('disk full')
    capture = ResponseCapture()
    capture.write(b'partial')
    capture.seal()
    async def run():
        try:
            await remote._notify_exchange(request=ChatCompletionRequest(provider_id='p', model_id='m', messages=()),
                on_exchange=fail, started_at='now', url='https://test.invalid', headers={}, body={},
                response_status=200, response_headers={}, response_body=capture, failure=None)
        finally:
            capture.release()
    asyncio.run(run())
    assert capture.closed


def audit_fixture(tmp_path):
    from tests.test_conversation_database import _Projects
    from app.repositories.project.conversation_repository import ProjectConversationRepository
    from app.services.project.conversation_audit import ConversationAuditService
    projects = _Projects(tmp_path)
    session = ProjectConversationRepository(projects).create_session(
        'project-1', title='audit', provider_id='provider', model_id='model', reasoning_mode=None)
    request = ChatCompletionRequest(provider_id='provider', model_id='model', project_id='project-1',
                                    session_id=session.session_id, messages=())
    return ConversationAuditService(projects), request


def exchange(body):
    return ChatHttpExchange(started_at='2026-10-27T00:00:00Z', completed_at='2026-10-27T00:00:01Z',
        request_url='https://example.invalid', request_headers={}, request_body={'stream': True},
        response_status=200, response_headers={}, response_body=body)


def test_failed_write_keeps_source_and_retries_same_artifact(tmp_path, monkeypatch):
    audit, request = audit_fixture(tmp_path)
    original = audit._complete_http_exchange
    capture = ResponseCapture(memory_limit=1)
    capture.write('完整响应🙂'.encode() * 2000)
    capture.seal()
    def fail(*args): raise OSError('temporary disk failure')
    monkeypatch.setattr(audit, '_complete_http_exchange', fail)
    async def run():
        await audit.record_http_exchange(request, exchange(capture))
        capture.release()  # receiving owner is done, persistence still owns it
        with pytest.raises(RuntimeError, match='保存失败'):
            await audit.close()
        assert not capture.closed
        monkeypatch.setattr(audit, '_complete_http_exchange', original)
        await audit.close()
        assert capture.closed
    asyncio.run(run())
    with sqlite3.connect(tmp_path / '.Tiance/tiance.db') as db:
        assert db.execute('SELECT status FROM conversation_artifacts').fetchall() == [('complete',)]
        assert db.execute('SELECT count(*) FROM conversation_audit_snapshots').fetchone()[0] == 1


def test_writes_are_bounded_and_exit_joins_all_queued_work(tmp_path, monkeypatch):
    audit, request = audit_fixture(tmp_path)
    original = audit._complete_http_exchange
    release = threading.Event()
    lock = threading.Lock()
    active = maximum = completed = 0
    async def run():
        entered = asyncio.Event()
        loop = asyncio.get_running_loop()
        def write(*args):
            nonlocal active, maximum, completed
            with lock:
                active += 1
                maximum = max(maximum, active)
                if active == 2: loop.call_soon_threadsafe(entered.set)
            try:
                assert release.wait(5)
                original(*args)
                with lock: completed += 1
            finally:
                with lock: active -= 1
        monkeypatch.setattr(audit, '_complete_http_exchange', write)
        try:
            for _ in range(5):
                await audit.record_http_exchange(request, exchange(b'synthetic body'))
            await asyncio.wait_for(entered.wait(), 3)
            closing = asyncio.create_task(audit.close())
            await asyncio.sleep(0)
            assert not closing.done()
            assert maximum == 2
            release.set()
            await closing
        finally:
            release.set()
    asyncio.run(run())
    assert maximum == 2 and completed == 5


@pytest.mark.parametrize('cancel', [False, True], ids=['done-marker', 'cancelled-network'])
def test_real_adapter_closes_and_registers_audit_before_return(monkeypatch, cancel):
    from app.domain.llm.provider_catalog import ProviderProtocolFamily
    from tests.test_llm_protocol_continuation import _provider, _runtime
    captured, records = [], []
    first = b'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}\n\n'
    end = b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
    def factory():
        body = ResponseCapture()
        captured.append(body)
        return body
    async def run():
        waiting = asyncio.Event()
        class Response:
            is_error = False
            status_code = 200
            headers = {}
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def raise_for_status(self): pass
            async def aiter_bytes(self):
                yield first
                if cancel:
                    waiting.set()
                    await asyncio.Event().wait()
                yield end
        class Client:
            def stream(self, *args, **kwargs): return Response()
        async def record(request, item):
            records.append((b''.join(body_chunks(item.response_body)), item.error_type))
        monkeypatch.setattr(remote, 'get_shared_http_client', lambda: Client())
        monkeypatch.setattr(remote, 'get_http_timeout', lambda **kwargs: None)
        monkeypatch.setattr(remote, 'ResponseCapture', factory)
        async def consume():
            return [event async for event in remote.ChatRemoteClient().stream(
                provider_template=_provider(ProviderProtocolFamily.OPENAI_COMPATIBLE, 'openai'),
                runtime_config=_runtime('openai'), api_key='synthetic',
                request=ChatCompletionRequest(provider_id='openai', model_id='synthetic', messages=()),
                on_exchange=record)]
        task = asyncio.create_task(consume())
        if cancel:
            await waiting.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
        else:
            await task
        # No garbage collection / event-loop shutdown is needed to register it.
        assert len(records) == 1
        assert records[0][0] == first + (b'' if cancel else end)
        if cancel: assert records[0][1] == 'CancelledError'
        assert captured[0].closed
    asyncio.run(run())
