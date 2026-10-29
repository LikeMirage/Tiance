import asyncio
from dataclasses import replace

import httpx
import pytest

from app.domain.network_settings import DEFAULT_NETWORK_SETTINGS
from app.infra import http_client as shared
from app.infra.llm.chat_remote_client import ChatRemoteClient


def _factory(monkeypatch, handler):
    clients = []

    class Client(httpx.AsyncClient):
        def __init__(self):
            super().__init__(transport=httpx.MockTransport(handler))
            self.closed_event = asyncio.Event()
            self.close_count = 0

        async def aclose(self):
            self.close_count += 1
            await super().aclose()
            self.closed_event.set()

    def build():
        client = Client()
        clients.append(client)
        return client

    monkeypatch.setattr(shared, "_build_http_client", build)
    return clients


def test_repeated_configuration_changes_close_idle_pools_without_another_request(monkeypatch):
    async def run():
        await shared.close_shared_http_clients()
        clients = _factory(monkeypatch, lambda request: httpx.Response(200, text="ok"))
        try:
            shared.configure_shared_http_client(DEFAULT_NETWORK_SETTINGS)
            for number in range(10):
                async with shared.lease_http_client(shared.get_shared_http_client()) as client:
                    assert (await client.get("https://example.test")).text == "ok"
                assert shared.get_shared_http_client() is client
                # Network settings are saved from a synchronous API worker.
                await asyncio.to_thread(shared.configure_shared_http_client,
                    replace(DEFAULT_NETWORK_SETTINGS, read_timeout_seconds=500 + number))
                await asyncio.wait_for(client.closed_event.wait(), 2)
            assert len(clients) == 10
            assert all(c.is_closed and c.close_count == 1 for c in clients)
            assert not shared._CLIENT_ENTRIES
        finally:
            await shared.close_shared_http_clients()
    asyncio.run(run())


def test_chat_stream_survives_settings_change_until_body_is_finished(monkeypatch):
    async def run():
        await shared.close_shared_http_clients()
        release = asyncio.Event()

        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"first"
                await release.wait()
                yield b"last"

        calls = 0
        def handle(request):
            nonlocal calls
            calls += 1
            return httpx.Response(200, stream=Body()) if calls == 1 else httpx.Response(200, text="new")

        clients = _factory(monkeypatch, handle)
        shared.configure_shared_http_client(DEFAULT_NETWORK_SETTINGS)
        stream = ChatRemoteClient()._stream_body("https://example.test", {}, {})
        try:
            assert await anext(stream) == b"first"
            old = clients[0]
            await asyncio.to_thread(shared.configure_shared_http_client,
                replace(DEFAULT_NETWORK_SETTINGS, read_timeout_seconds=301))
            async with shared.lease_http_client(shared.get_shared_http_client()) as current:
                assert current is not old
                assert (await current.get("https://example.test")).text == "new"
            assert not old.is_closed
            release.set()
            assert await anext(stream) == b"last"
            with pytest.raises(StopAsyncIteration):
                await anext(stream)
            await asyncio.wait_for(old.closed_event.wait(), 2)
            assert not current.is_closed
        finally:
            await stream.aclose()
            await shared.close_shared_http_clients()
    asyncio.run(run())


@pytest.mark.parametrize("outcome", ["complete", "error", "cancel"])
def test_buffered_request_releases_retired_pool_on_every_exit(monkeypatch, outcome):
    async def run():
        await shared.close_shared_http_clients()
        entered, release = asyncio.Event(), asyncio.Event()

        async def handle(request):
            entered.set()
            await release.wait()
            if outcome == "error":
                raise httpx.ConnectError("test failure", request=request)
            return httpx.Response(200, json={"answer": "complete"})

        clients = _factory(monkeypatch, handle)
        shared.configure_shared_http_client(DEFAULT_NETWORK_SETTINGS)
        task = asyncio.create_task(ChatRemoteClient()._post_json("https://example.test", {}, {}))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            shared.configure_shared_http_client(replace(DEFAULT_NETWORK_SETTINGS, read_timeout_seconds=302))
            await asyncio.sleep(0)
            assert not clients[0].is_closed
            if outcome == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            elif outcome == "error":
                release.set()
                with pytest.raises(httpx.ConnectError):
                    await task
            else:
                release.set()
                assert await task == {"answer": "complete"}
            await asyncio.wait_for(clients[0].closed_event.wait(), 2)
            assert clients[0].close_count == 1
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await shared.close_shared_http_clients()
    asyncio.run(run())


def test_same_settings_reuse_pool_and_nested_leases_wait_for_last_user(monkeypatch):
    async def run():
        await shared.close_shared_http_clients()
        clients = _factory(monkeypatch, lambda request: httpx.Response(200))
        shared.configure_shared_http_client(DEFAULT_NETWORK_SETTINGS)
        try:
            async with shared.lease_http_client(shared.get_shared_http_client()) as first:
                shared.configure_shared_http_client(DEFAULT_NETWORK_SETTINGS)
                async with shared.lease_http_client(shared.get_shared_http_client()) as second:
                    assert first is second
                    shared.configure_shared_http_client(replace(DEFAULT_NETWORK_SETTINGS, read_timeout_seconds=303))
                await asyncio.sleep(0)
                assert not first.is_closed
            # Shutdown and retirement may race; closure must still happen once.
            await shared.close_shared_http_clients()
            assert len(clients) == 1 and first.close_count == 1 and first.is_closed
        finally:
            await shared.close_shared_http_clients()
    asyncio.run(run())


def test_closing_an_unfinished_chat_stream_releases_its_retired_pool(monkeypatch):
    async def run():
        await shared.close_shared_http_clients()
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"partial"
                await asyncio.Event().wait()
        clients = _factory(monkeypatch, lambda request: httpx.Response(200, stream=Body()))
        shared.configure_shared_http_client(DEFAULT_NETWORK_SETTINGS)
        stream = ChatRemoteClient()._stream_body("https://example.test", {}, {})
        try:
            assert await anext(stream) == b"partial"
            shared.configure_shared_http_client(replace(DEFAULT_NETWORK_SETTINGS, read_timeout_seconds=304))
            await stream.aclose()
            await asyncio.wait_for(clients[0].closed_event.wait(), 2)
            assert clients[0].close_count == 1
        finally:
            await stream.aclose()
            await shared.close_shared_http_clients()
    asyncio.run(run())
