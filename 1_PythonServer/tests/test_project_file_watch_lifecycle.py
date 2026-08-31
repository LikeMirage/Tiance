from __future__ import annotations

import asyncio
import multiprocessing
import queue
import sys
from types import SimpleNamespace

import pytest
from starlette.requests import ClientDisconnect

from app.api.routes.project import files as file_routes
from app.api.event_stream import EventStreamResponse
from app.infra.projects import project_file_watcher as watcher


class FakeQueue(queue.Queue):
    closed = False
    joined = False

    def close(self):
        self.closed = True

    def join_thread(self):
        self.joined = True


class FakeProcess:
    def __init__(self, *, args, **_kwargs):
        self.event_queue = args[1]
        self.pid = None
        self.alive = False
        self.closed = False
        self.exitcode = None

    def start(self):
        self.pid = 123
        self.alive = True
        self.event_queue.put(("ready", ()))

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.alive = False
        self.exitcode = -15

    def kill(self):
        self.alive = False
        self.exitcode = -9

    def join(self, timeout):
        pass

    def close(self):
        assert not self.alive
        self.closed = True


@pytest.fixture
def fake_watch(monkeypatch, tmp_path):
    processes = []
    queues = []
    streams = []

    def make_queue(**kwargs):
        result = FakeQueue(**kwargs)
        queues.append(result)
        return result

    def make_process(**kwargs):
        result = FakeProcess(**kwargs)
        processes.append(result)
        return result

    context = SimpleNamespace(Queue=make_queue, Process=make_process)
    monkeypatch.setattr(multiprocessing, "get_context", lambda _method: context)
    monkeypatch.setattr(watcher, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(watcher, "_WATCH_PROCESS_POLL_SECONDS", 0.01)
    original_watch = watcher._watch_windows_process

    def track_watch(*args, **kwargs):
        result = original_watch(*args, **kwargs)
        # Retain the iterator so GC cannot hide missing explicit ownership.
        streams.append(result)
        return result

    monkeypatch.setattr(watcher, "_watch_windows_process", track_watch)
    monkeypatch.setattr(
        file_routes,
        "get_project_file_service",
        lambda: SimpleNamespace(
            watch_file_changes=lambda project_id: watcher.watch_project_file_changes(
                str(tmp_path), project_id=project_id
            )
        ),
    )
    return SimpleNamespace(processes=processes, queues=queues, streams=streams, context=context)


async def disconnect_during_send(response):
    sending = asyncio.Event()

    async def receive():
        await sending.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body":
            sending.set()
            await asyncio.Event().wait()

    await asyncio.wait_for(
        response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send),
        timeout=5,
    )


def test_closing_outer_watch_reclaims_worker(fake_watch, tmp_path):
    async def exercise():
        source = watcher.watch_project_file_changes(str(tmp_path), project_id="test")
        try:
            assert (await anext(source)).kind == "ready"
            await source.aclose()
            assert not fake_watch.processes[0].is_alive()
            assert fake_watch.processes[0].closed
            assert fake_watch.queues[0].closed and fake_watch.queues[0].joined
        finally:
            await source.aclose()
            for stream in fake_watch.streams:
                await stream.aclose()

    asyncio.run(exercise())


def test_disconnect_during_send_reclaims_worker(fake_watch):
    async def exercise():
        response = await file_routes.watch_project_files("test")
        try:
            await disconnect_during_send(response)
            assert not fake_watch.processes[0].is_alive()
            assert fake_watch.processes[0].closed
        finally:
            await response.body_iterator.aclose()
            for stream in fake_watch.streams:
                await stream.aclose()

    asyncio.run(exercise())


def test_reconnect_does_not_accumulate_workers(fake_watch):
    async def exercise():
        for _ in range(3):
            response = await file_routes.watch_project_files("test")
            await disconnect_during_send(response)
            assert all(process.closed and not process.alive for process in fake_watch.processes)
            assert all(event_queue.closed and event_queue.joined for event_queue in fake_watch.queues)
        assert len(fake_watch.processes) == 3

    asyncio.run(exercise())


def test_start_failure_closes_process_and_queue(fake_watch, monkeypatch, tmp_path):
    def fail_start(self):
        raise OSError("process could not start")

    monkeypatch.setattr(FakeProcess, "start", fail_start)

    async def exercise():
        source = watcher.watch_project_file_changes(str(tmp_path), project_id="test")
        try:
            assert (await anext(source)).kind == "unavailable"
            assert fake_watch.processes[0].closed
            assert fake_watch.queues[0].closed and fake_watch.queues[0].joined
        finally:
            await source.aclose()

    asyncio.run(exercise())


def test_worker_failure_reclaims_before_unavailable(fake_watch, tmp_path):
    async def exercise():
        source = watcher.watch_project_file_changes(str(tmp_path), project_id="test")
        try:
            assert (await anext(source)).kind == "ready"
            fake_watch.queues[0].put(("failed", ("native reader failed",)))
            assert (await anext(source)).kind == "unavailable"
            assert fake_watch.processes[0].closed
        finally:
            await source.aclose()
        assert len(fake_watch.processes) == 1

    asyncio.run(exercise())


def test_stop_escalates_to_kill_and_closes_handles():
    event_queue = FakeQueue()
    process = FakeProcess(args=("project", event_queue))
    process.start()
    process.terminate = lambda: None
    watcher._stop_watch_process(process, event_queue)
    assert process.exitcode == -9 and process.closed
    assert event_queue.closed and event_queue.joined


def test_stop_failure_is_not_silently_ignored():
    event_queue = FakeQueue()
    process = FakeProcess(args=("project", event_queue))
    process.start()
    process.terminate = process.kill = lambda: None
    with pytest.raises(RuntimeError, match="did not exit"):
        watcher._stop_watch_process(process, event_queue)
    assert not process.closed
    assert event_queue.closed and event_queue.joined


def test_heartbeats_keep_same_read_and_preserve_event_order():
    async def exercise():
        released = asyncio.Event()
        closed = False
        reads = 0
        bodies = []

        async def events():
            nonlocal closed, reads
            try:
                reads += 1
                yield 'data: {"kind":"ready"}\n\n'
                reads += 1
                await released.wait()
                yield 'data: {"kind":"changed","paths":["report.txt"]}\n\n'
            finally:
                closed = True

        async def send(message):
            if message["type"] == "http.response.body":
                bodies.append(message["body"])
                if bodies.count(b": keep-alive\n\n") == 2:
                    released.set()

        response = EventStreamResponse(events(), heartbeat_seconds=0.01)
        await asyncio.wait_for(response.stream_response(send), 3)
        assert closed and reads == 2
        assert bodies.count(b": keep-alive\n\n") >= 2
        assert [body for body in bodies if body.startswith(b"data:")] == [
            b'data: {"kind":"ready"}\n\n',
            b'data: {"kind":"changed","paths":["report.txt"]}\n\n',
        ]
        assert bodies[-1] == b""

    asyncio.run(exercise())


@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
def test_send_error_closes_source(spec_version):
    async def exercise():
        closed = False

        async def events():
            nonlocal closed
            try:
                yield "data: ready\n\n"
            finally:
                closed = True

        async def send(message):
            if message["type"] == "http.response.body":
                raise OSError("connection lost")

        async def receive():
            await asyncio.Event().wait()

        response = EventStreamResponse(events(), heartbeat_seconds=15)
        with pytest.raises((OSError, ClientDisconnect)):
            await response({"asgi": {"spec_version": spec_version}}, receive, send)
        assert closed

    asyncio.run(exercise())


def test_idle_disconnect_waits_for_source_cleanup():
    async def exercise():
        reading = asyncio.Event()
        closed = False

        async def events():
            nonlocal closed
            try:
                yield "data: ready\n\n"
                reading.set()
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0.01)
                closed = True

        async def send(_message):
            pass

        async def receive():
            await reading.wait()
            return {"type": "http.disconnect"}

        response = EventStreamResponse(events(), heartbeat_seconds=15)
        await response({"asgi": {"spec_version": "2.3"}}, receive, send)
        assert closed

    asyncio.run(exercise())


def test_repeated_cancellation_does_not_abandon_cleanup():
    async def exercise():
        sending = asyncio.Event()
        cleaning = asyncio.Event()
        release_cleanup = asyncio.Event()
        closed = False

        async def events():
            nonlocal closed
            try:
                yield "data: ready\n\n"
            finally:
                cleaning.set()
                await release_cleanup.wait()
                closed = True

        async def send(message):
            if message["type"] == "http.response.body":
                sending.set()
                await asyncio.Event().wait()

        response = EventStreamResponse(events(), heartbeat_seconds=15)
        task = asyncio.create_task(response.stream_response(send))
        await sending.wait()
        task.cancel()
        await cleaning.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed

    asyncio.run(exercise())


def test_pending_read_cleanup_failure_is_reported():
    async def exercise():
        reading = asyncio.Event()

        async def events():
            try:
                yield "data: ready\n\n"
                reading.set()
                await asyncio.Event().wait()
            finally:
                raise RuntimeError("watcher cleanup failed")

        async def send(_message):
            pass

        response = EventStreamResponse(events(), heartbeat_seconds=15)
        task = asyncio.create_task(response.stream_response(send))
        await reading.wait()
        task.cancel()
        with pytest.raises(RuntimeError, match="watcher cleanup failed"):
            await task

    asyncio.run(exercise())


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows watcher subprocesses")
def test_real_windows_workers_exit_after_each_disconnect(monkeypatch, tmp_path):
    context = multiprocessing.get_context("spawn")
    processes = []
    exits = []

    class TrackedProcess:
        def __init__(self, process):
            self.process = process

        def __getattr__(self, name):
            return getattr(self.process, name)

        def close(self):
            process = self.process
            exits.append((process.pid, process.exitcode, process.is_alive()))
            process.close()

    def make_process(**kwargs):
        process = TrackedProcess(context.Process(**kwargs))
        processes.append(process)
        return process

    monkeypatch.setattr(
        multiprocessing, "get_context",
        lambda _method: SimpleNamespace(Queue=context.Queue, Process=make_process),
    )
    monkeypatch.setattr(
        file_routes, "get_project_file_service",
        lambda: SimpleNamespace(
            watch_file_changes=lambda project_id: watcher.watch_project_file_changes(
                str(tmp_path), project_id=project_id
            )
        ),
    )

    async def exercise():
        for cycle in range(3):
            response = await file_routes.watch_project_files("lifecycle-test")
            try:
                await disconnect_during_send(response)
                assert len(exits) == cycle + 1
                assert exits[-1][0] is not None
                assert exits[-1][1] is not None and exits[-1][2] is False
            finally:
                await response.body_iterator.aclose()

    try:
        asyncio.run(exercise())
    finally:
        # Test failure must not leave a real watcher on the user's machine.
        for process in processes:
            if not process._closed:
                if process.is_alive():
                    process.kill()
                process.join(timeout=5)
                process.close()
