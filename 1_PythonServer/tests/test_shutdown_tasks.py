import asyncio
import threading

import pytest

from app.core.errors import AppError
from app.core.shutdown_tasks import ShutdownTasks, shutdown_tasks
from tests.test_theme_market_update import _create_service, _version


def test_shutdown_cancels_downloads_rejects_new_work_and_waits_for_commit():
    async def run():
        registry = ShutdownTasks()
        downloading, committing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        stopped = []

        @registry.request
        async def download():
            downloading.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.append(True)

        @registry.request
        async def install():
            registry.commit_started()
            committing.set()
            await release.wait()
            return "installed"

        first, second = asyncio.create_task(download()), asyncio.create_task(install())
        await downloading.wait()
        await committing.wait()
        assert registry.begin_close() == 2
        assert registry.begin_close() == 2  # repeated polling must not re-cancel cleanup
        with pytest.raises(AppError, match="已停止"):
            await first
        assert stopped == [True]
        assert registry.begin_close() == 1
        with pytest.raises(AppError) as rejected:
            await download()
        assert rejected.value.code == "application_exiting"
        release.set()
        await registry.close()
        assert await second == "installed"
        assert registry.begin_close() == 0
        registry.resume()
        assert await install() == "installed"

    asyncio.run(run())


@pytest.mark.parametrize("rollback", [False, True])
def test_theme_exit_waits_for_real_install_or_rollback(tmp_path, rollback):
    service, root, _, _ = _create_service(tmp_path, fail_once=rollback)

    async def run():
        entered = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        original = service._commit_theme_install

        def commit(**kwargs):
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5), "test did not release worker"
            # Cancellation must not remove its downloaded archive.
            assert kwargs["archive_path"].is_file()
            return original(**kwargs)

        service._commit_theme_install = commit
        task = asyncio.create_task(service.install_theme(
            theme_id="sample-theme", category_id=None, replace_existing=True,
        ))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            assert shutdown_tasks.begin_close() == 1
            assert not task.done()
            assert list((root / ".downloads").iterdir())
            release.set()
            if rollback:
                with pytest.raises(RuntimeError, match="同步失败"):
                    await task
            else:
                await task
            await shutdown_tasks.close()
            assert not list((root / ".downloads").iterdir())
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            shutdown_tasks.resume()

    asyncio.run(run())
    assert _version(root / "sample-theme") == ("1.0.0" if rollback else "1.1.0")
    assert (root / "sample-theme/.Tiance/local.json").read_text() == "keep"
    assert (root / "sample-theme/notes.md").read_text() == "keep"


def test_repeated_external_cancellation_does_not_clean_up_under_running_thread(tmp_path):
    service, root, _, _ = _create_service(tmp_path)

    async def run():
        entered, second_turn = asyncio.Event(), asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        original = service._commit_theme_install

        def commit(**kwargs):
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5)
            assert kwargs["archive_path"].is_file()
            return original(**kwargs)

        service._commit_theme_install = commit
        task = asyncio.create_task(service.install_theme(
            theme_id="sample-theme", category_id=None, replace_existing=True,
        ))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            task.cancel()
            loop.call_soon(second_turn.set)
            await second_turn.wait()
            task.cancel()
            assert not task.done()
            assert list((root / ".downloads").iterdir())
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not list((root / ".downloads").iterdir())

    asyncio.run(run())
    assert _version(root / "sample-theme") == "1.1.0"


def test_theme_downloading_is_stopped_and_partial_file_removed(tmp_path):
    service, root, _, _ = _create_service(tmp_path)

    async def run():
        entered = asyncio.Event()

        async def download(*, target, **kwargs):
            target.parent.mkdir(parents=True)
            target.write_bytes(b"partial")
            entered.set()
            await asyncio.Event().wait()

        service._remote_client.download_package = download
        task = asyncio.create_task(service.install_theme(
            theme_id="sample-theme", category_id=None, replace_existing=True,
        ))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            await shutdown_tasks.close()
            with pytest.raises(AppError) as stopped:
                await task
            assert stopped.value.code == "operation_stopped"
            assert not list((root / ".downloads").iterdir())
        finally:
            shutdown_tasks.resume()

    asyncio.run(run())
    assert _version(root / "sample-theme") == "1.0.0"


def test_exit_endpoint_requires_owning_shell_and_reports_real_pending_state(monkeypatch):
    import httpx
    from fastapi import FastAPI
    from app.api.routes.desktop import router
    from app.core.shell_lease import LEASE_INSTANCE_HEADER, LEASE_TOKEN_HEADER
    from app.services.application.desktop_exit import DesktopExitCoordinator
    coordinator = DesktopExitCoordinator()
    monkeypatch.setattr("app.api.routes.desktop.get_desktop_exit_coordinator", lambda: coordinator)

    for key, value in {
        "TIANCE_SHELL_INSTANCE_ID": "test-instance",
        "TIANCE_SHELL_LEASE_TOKEN": "test-token",
        "TIANCE_SHELL_HEARTBEAT_URL": "http://127.0.0.1:9999/heartbeat",
    }.items():
        monkeypatch.setenv(key, value)
    app = FastAPI()
    app.include_router(router, prefix="/api")

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            url = "/api/desktop/exit-preparation"
            assert (await client.post(url)).status_code == 403
            headers = {LEASE_INSTANCE_HEADER: "test-instance", LEASE_TOKEN_HEADER: "wrong"}
            assert (await client.post(url, headers=headers)).status_code == 403
            headers[LEASE_TOKEN_HEADER] = "test-token"
            try:
                result = await client.post(url, headers=headers)
                assert result.json()["ready"] is False
                await coordinator.close()
                result = await client.post(url, headers=headers)
                assert result.json() == {"ready": True, "pending_tasks": 0}
                with pytest.raises(AppError):
                    shutdown_tasks.require_accepting()
                assert (await client.delete(url, headers=headers)).status_code == 204
                shutdown_tasks.require_accepting()
            finally:
                shutdown_tasks.resume()

    asyncio.run(run())


def test_queued_project_install_is_settled_when_exit_precedes_first_task_turn(tmp_path):
    from tests.test_project_market_contract import build_market_service
    service, _, projects, _, root, _ = build_market_service(tmp_path)
    category = projects.create_project_category(name="下载项目")

    async def run():
        operation = await service.start_install(market_project_id="sample-project", category_id=category.category_id)
        try:
            await shutdown_tasks.close()
            state = service.get_operation(operation.operation_id)
            assert state.phase == "failed"
            assert state.error == "项目安装已停止。"
            assert not service._active_market_projects
            assert not service._tasks
        finally:
            shutdown_tasks.resume()

    asyncio.run(run())


@pytest.mark.parametrize("rollback", [False, True])
def test_project_import_and_initial_conversation_settle_before_exit(tmp_path, rollback):
    from tests.test_project_market_contract import build_market_service
    service, _, projects, creation, _, catalog = build_market_service(tmp_path, creation_fails=rollback)
    category = projects.create_project_category(name="下载项目")

    async def run():
        entered = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        original = creation.ensure_initial_conversation

        def initialize(project_id):
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5)
            return original(project_id)

        creation.ensure_initial_conversation = initialize
        operation = await service.start_install(market_project_id="sample-project", category_id=category.category_id)
        try:
            await asyncio.wait_for(entered.wait(), 5)
            assert shutdown_tasks.begin_close() == 1
            release.set()
            await shutdown_tasks.close()
            state = service.get_operation(operation.operation_id)
            assert state.phase == ("failed" if rollback else "completed")
            assert len(catalog.list_projects()) == (0 if rollback else 1)
            assert not list(service._cache_repository.operations_root.iterdir())
        finally:
            release.set()
            await service.close()
            shutdown_tasks.resume()

    asyncio.run(run())
