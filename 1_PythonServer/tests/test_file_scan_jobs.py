import asyncio
from concurrent.futures import CancelledError
from threading import Event

import anyio
import pytest

from app.infra.file_workspace.content_scan import content_snapshot
from app.services.file_workspace_scan import FileScanJobs


def test_scoped_snapshot_reads_only_changed_scope_without_losing_files(tmp_path, monkeypatch):
    import app.infra.file_workspace.content_scan as scanning
    (tmp_path / 'logs').mkdir()
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'logs' / 'server.log').write_text('old')
    (tmp_path / 'docs' / 'report.md').write_text('report')
    initial = {item.path for item in content_snapshot(str(tmp_path)).items}
    assert initial == {'logs/server.log', 'docs/report.md'}
    calls = []
    real_scan = scanning.os.scandir
    def scan(path):
        calls.append(path)
        return real_scan(path)
    monkeypatch.setattr(scanning.os, 'scandir', scan)
    (tmp_path / 'logs' / 'server.log').write_text('new')
    changed = content_snapshot(str(tmp_path), paths=('logs/server.log',))
    assert [item.path for item in changed.items] == ['logs/server.log']
    assert calls == []  # No enumeration, including unrelated directories.
    (tmp_path / 'docs' / 'report.md').rename(tmp_path / 'docs' / 'renamed.md')
    changed = content_snapshot(str(tmp_path), paths=('docs', 'docs/renamed.md'))
    assert [item.path for item in changed.items] == ['docs/renamed.md']
    assert len(calls) == 1
    assert not content_snapshot(str(tmp_path), paths=('docs/report.md',)).items


def test_scoped_snapshot_rejects_external_paths_and_link_ancestors(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'secret.txt').write_text('outside')
    with pytest.raises(ValueError):
        content_snapshot(str(root), paths=('../outside',))
    link = root / 'link'
    if __import__('os').name == 'nt':
        import subprocess
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)], capture_output=True)
        if result.returncode:
            pytest.skip('Cannot create junction')
    else:
        link.symlink_to(outside, target_is_directory=True)
    try:
        assert not content_snapshot(str(root)).items
        assert not content_snapshot(str(root), paths=('link/secret.txt',)).items
    finally:
        if __import__('os').name == 'nt':
            link.rmdir()  # Remove only the junction, never its target.
        else:
            link.unlink()
    assert (outside / 'secret.txt').read_text() == 'outside'


def test_scan_cancellation_never_returns_a_partial_snapshot(tmp_path):
    cancelled = Event()
    cancelled.set()
    with pytest.raises(CancelledError):
        content_snapshot(str(tmp_path), cancelled=cancelled)


def test_shared_scan_survives_one_reader_leaving_and_reaps_after_last_reader():
    async def scenario():
        jobs = FileScanJobs()
        started, exited = Event(), Event()
        calls = []
        def scan(cancelled):
            calls.append(1)
            started.set()
            try:
                assert cancelled.wait(3)
            finally:
                exited.set()
        first = asyncio.create_task(jobs.read(('project',), scan))
        assert await asyncio.to_thread(started.wait, 2)
        second = asyncio.create_task(jobs.read(('project',), scan))
        await asyncio.sleep(0)
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        assert not exited.is_set()
        assert calls == [1]
        second.cancel()
        await asyncio.wait_for(asyncio.gather(second, return_exceptions=True), 2)
        assert exited.is_set()
        assert not jobs._jobs
        assert await jobs.read(('project',), lambda _: 'fresh') == 'fresh'
    asyncio.run(scenario())


def test_long_scans_do_not_occupy_lightweight_request_capacity():
    async def scenario():
        jobs = FileScanJobs()
        default = anyio.to_thread.current_default_thread_limiter()
        default.total_tokens = 1
        started = [Event(), Event()]
        tasks = []
        def scan(cancelled, index):
            started[index].set()
            assert cancelled.wait(3)
        try:
            for index in range(2):
                tasks.append(asyncio.create_task(jobs.read((index,), lambda stop, i=index: scan(stop, i))))
            assert all(await asyncio.gather(*(asyncio.to_thread(event.wait, 2) for event in started)))
            # A normal sync endpoint remains runnable while both scans are busy.
            assert await asyncio.wait_for(anyio.to_thread.run_sync(lambda: 'files and exit ready'), 1) == 'files and exit ready'
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        assert not jobs._jobs
    asyncio.run(scenario())


def test_disconnected_request_stops_its_actual_worker(monkeypatch):
    from app.services import file_workspace_scan as service
    from app.core.errors import AppError
    async def scenario():
        started, stopped = Event(), Event()
        disconnected = False
        class Request:
            async def is_disconnected(self):
                return disconnected
        def scan(_root, *, paths, cancelled):
            started.set()
            try:
                assert cancelled.wait(3)
                raise CancelledError()
            finally:
                stopped.set()
        monkeypatch.setattr(service, 'scan_jobs', FileScanJobs())
        monkeypatch.setattr(service, 'content_snapshot', scan)
        task = asyncio.create_task(service.read_content_snapshot(Request(), 'p', 'root'))
        assert await asyncio.to_thread(started.wait, 2)
        disconnected = True
        with pytest.raises(AppError) as error:
            await asyncio.wait_for(task, 2)
        assert error.value.status_code == 499
        assert stopped.is_set()
        assert not service.scan_jobs._jobs
    asyncio.run(scenario())


def test_real_routes_keep_file_tree_and_authenticated_exit_responsive_during_scans(tmp_path, monkeypatch):
    import httpx
    from fastapi import FastAPI
    from types import SimpleNamespace
    from app.api.routes.project import files
    from app.api.routes import desktop
    from app.services import file_workspace_scan as service
    async def scenario():
        started = Event()
        stopped = Event()
        def scan(_root, *, paths, cancelled):
            started.set()
            try:
                assert cancelled.wait(3)
                raise CancelledError()
            finally:
                stopped.set()
        monkeypatch.setattr(service, 'scan_jobs', FileScanJobs())
        monkeypatch.setattr(service, 'content_snapshot', scan)
        monkeypatch.setattr(files, 'get_project_file_service', lambda: SimpleNamespace(
            get_project_root=lambda _id: str(tmp_path),
            list_tree_result=lambda *_args, **_kwargs: SimpleNamespace(items=[])))
        monkeypatch.setattr(desktop, 'is_managed_shell_request', lambda *_: True)
        monkeypatch.setattr(desktop, 'get_desktop_exit_coordinator', lambda: SimpleNamespace(begin=lambda: 0))
        app = FastAPI()
        app.include_router(files.router)
        app.include_router(desktop.router)
        anyio.to_thread.current_default_thread_limiter().total_tokens = 1
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            scanning = asyncio.create_task(client.get('/projects/p/files/snapshot'))
            try:
                assert await asyncio.to_thread(started.wait, 2)
                tree, exit_response = await asyncio.wait_for(asyncio.gather(
                    client.get('/projects/p/files'), client.post('/desktop/exit-preparation')), 1)
                assert tree.status_code == exit_response.status_code == 200
                assert exit_response.json()['ready']
                monkeypatch.setattr(desktop, 'is_managed_shell_request', lambda *_: False)
                assert (await client.post('/desktop/exit-preparation')).status_code == 403
            finally:
                scanning.cancel()
                await asyncio.gather(scanning, return_exceptions=True)
            assert stopped.is_set()
    asyncio.run(scenario())


def test_partial_and_full_snapshot_http_contract(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from app.api.routes.project import files
    from app.services import file_workspace_scan as service
    (tmp_path / 'one.md').write_text('one')
    (tmp_path / 'two.md').write_text('two')
    monkeypatch.setattr(service, 'scan_jobs', FileScanJobs())
    monkeypatch.setattr(files, 'get_project_file_service', lambda: SimpleNamespace(get_project_root=lambda _: str(tmp_path)))
    app = FastAPI()
    app.include_router(files.router)
    with TestClient(app) as client:
        full = client.get('/projects/p/files/snapshot').json()
        partial = client.post('/projects/p/files/snapshot', json={'paths': ['one.md']}).json()
    assert full['project_id'] == partial['project_id'] == 'p'
    assert {item['path'] for item in full['items']} == {'one.md', 'two.md'}
    assert [item['path'] for item in partial['items']] == ['one.md']
    assert partial['unreadable_paths'] == []


def test_exit_cancels_and_drains_active_scan_workers(monkeypatch):
    from app.services import file_workspace_scan as service
    from app.core.shutdown_tasks import shutdown_tasks
    from app.core.errors import AppError
    async def scenario():
        started, stopped = Event(), Event()
        class Request:
            async def is_disconnected(self): return False
        def scan(_root, *, paths, cancelled):
            started.set()
            try:
                assert cancelled.wait(3)
                raise CancelledError()
            finally:
                stopped.set()
        monkeypatch.setattr(service, 'scan_jobs', FileScanJobs())
        monkeypatch.setattr(service, 'content_snapshot', scan)
        task = asyncio.create_task(service.read_content_snapshot(Request(), 'p', 'root'))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            await asyncio.wait_for(shutdown_tasks.close(), 2)
            with pytest.raises(AppError) as error:
                await task
            assert error.value.status_code == 503
            assert stopped.is_set()
            assert not service.scan_jobs._jobs
        finally:
            shutdown_tasks.resume()
    asyncio.run(scenario())
