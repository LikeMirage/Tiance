from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.event_socket import serve_event_socket
from app.api.routes.project import core, files
from app.api.routes import themes
from app.infra.projects.project_file_watcher import ProjectFileWatchEvent
from tests.test_project_file_watch_lifecycle import fake_watch  # noqa: F401


class Socket:
    def __init__(self, *, block_send=False, fail_send=False):
        self.messages = []
        self.sent = asyncio.Event()
        self.disconnect = asyncio.Event()
        self.block_send = block_send
        self.fail_send = fail_send
        self.closed = False

    async def accept(self):
        pass

    async def send_json(self, payload):
        self.messages.append(payload)
        self.sent.set()
        if self.fail_send:
            raise WebSocketDisconnect()
        if self.block_send:
            await asyncio.Event().wait()

    async def receive(self):
        await self.disconnect.wait()
        return {"type": "websocket.disconnect"}

    async def close(self, code=1000):
        self.closed = True


@pytest.mark.parametrize("phase", ["idle", "send", "send_failure"])
def test_socket_disconnect_reclaims_windows_watcher(fake_watch, phase):
    async def exercise():
        socket = Socket(block_send=phase == "send", fail_send=phase == "send_failure")
        task = asyncio.create_task(files.watch_project_files_socket(socket, "test"))
        await asyncio.wait_for(socket.sent.wait(), 5)
        socket.disconnect.set()
        await asyncio.wait_for(task, 5)
        assert all(p.closed and not p.alive for p in fake_watch.processes)
        assert all(q.closed and q.joined for q in fake_watch.queues)

    asyncio.run(exercise())


def test_heartbeats_preserve_pending_read_and_event_order():
    async def exercise():
        reads = 0
        closed = False
        release = asyncio.Event()

        async def events():
            nonlocal reads, closed
            try:
                yield {"kind": "ready"}
                reads += 1
                await release.wait()
                yield {"kind": "changed", "paths": ["图.png"]}
            finally:
                closed = True

        socket = Socket()
        task = asyncio.create_task(serve_event_socket(socket, events(), heartbeat_seconds=0.01))
        while sum(p["kind"] == "heartbeat" for p in socket.messages) < 2:
            await asyncio.sleep(0.005)
        assert reads == 1 and not closed
        release.set()
        await asyncio.wait_for(task, 2)
        assert socket.messages[0] == {"kind": "ready"}
        assert socket.messages[-1] == {"kind": "changed", "paths": ["图.png"]}
        assert socket.closed and closed

    asyncio.run(exercise())


def test_repeated_cancellation_waits_for_iterator_cleanup():
    async def exercise():
        cleaning = asyncio.Event()
        release = asyncio.Event()
        closed = False

        async def events():
            nonlocal closed
            try:
                yield {"kind": "ready"}
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
                closed = True

        socket = Socket(block_send=True)
        task = asyncio.create_task(serve_event_socket(socket, events()))
        await socket.sent.wait()
        task.cancel()
        await cleaning.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed

    asyncio.run(exercise())


def test_cleanup_failure_is_not_hidden():
    async def exercise():
        reading = asyncio.Event()

        async def events():
            try:
                yield {"kind": "ready"}
                reading.set()
                await asyncio.Event().wait()
            finally:
                raise RuntimeError("watcher cleanup failed")

        socket = Socket()
        task = asyncio.create_task(serve_event_socket(socket, events()))
        await reading.wait()
        socket.disconnect.set()
        with pytest.raises(RuntimeError, match="watcher cleanup failed"):
            await task

    asyncio.run(exercise())


def test_actual_routes_deliver_changes_and_close_all_subscriptions(monkeypatch):
    active = set()

    async def paths(name):
        active.add(name)
        try:
            yield ("图.png",)
            await asyncio.Event().wait()
        finally:
            active.remove(name)

    async def file_events(project_id):
        active.add(project_id)
        try:
            yield ProjectFileWatchEvent("ready")
            yield ProjectFileWatchEvent("changed", ("图.png",))
            await asyncio.Event().wait()
        finally:
            active.remove(project_id)

    monkeypatch.setattr(core, "get_project_workspace_event_broker", lambda: SimpleNamespace(subscribe=lambda: paths("projects")))
    monkeypatch.setattr(themes, "get_theme_workspace_event_broker", lambda: SimpleNamespace(subscribe=lambda: paths("themes")))
    monkeypatch.setattr(files, "get_project_file_service", lambda: SimpleNamespace(watch_file_changes=file_events))
    app = FastAPI()
    for router in [core.router, themes.router, files.router]:
        app.include_router(router, prefix="/api")
    with TestClient(app) as client:
        for route in ["/api/projects/events", "/api/themes/events", "/api/projects/test/files/events"]:
            with client.websocket_connect(route) as socket:
                assert socket.receive_json() == {"kind": "ready"}
                assert socket.receive_json() == {"kind": "changed", "paths": ["图.png"]}
            assert not active
