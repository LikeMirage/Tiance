import asyncio
import threading
from types import SimpleNamespace

import pytest
from watchfiles import Change

from app.core.shutdown_tasks import ShutdownTasks
from app.domain.project import ProjectKind
from app.infra.projects import read_project_identity
from app.repositories.project import FileProjectCatalog
from app.services.application import desktop_exit
from app.services.application.project_workspace_reconciliation import (
    ProjectWorkspaceReconciliationService,
)
from app.services.project import project_workspace_watcher as watcher


@pytest.fixture
def registry(monkeypatch):
    value = ShutdownTasks()
    monkeypatch.setattr(watcher, "shutdown_tasks", value)
    return value


class WatchHarness:
    def __init__(self, monkeypatch, root, synchronize):
        self.changes = asyncio.Queue()
        self.notifications = asyncio.Queue()
        self.delivered = asyncio.Queue()
        self.loop_thread = threading.get_ident()
        self.root = root

        async def watch(*args, **kwargs):
            assert kwargs["debounce"] == 700
            assert kwargs["step"] == 100
            while (paths := await self.changes.get()) is not None:
                self.delivered.put_nowait(paths)
                yield {(Change.modified, str(root / path)) for path in paths}

        def publish(paths):
            assert threading.get_ident() == self.loop_thread
            self.notifications.put_nowait(paths)

        monkeypatch.setattr(watcher, "awatch", watch)
        self.task = asyncio.create_task(watcher.watch_project_workspace_changes(
            root, SimpleNamespace(synchronize=synchronize), SimpleNamespace(publish=publish),
        ))

    def emit(self, *paths):
        self.changes.put_nowait(paths)

    async def notification(self):
        return await asyncio.wait_for(self.notifications.get(), 5)

    async def finish(self):
        self.changes.put_nowait(None)
        await asyncio.wait_for(self.task, 5)

    async def cancel(self):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)


def test_scans_leave_loop_responsive_and_process_later_batches_serially(
    monkeypatch, tmp_path, registry,
):
    async def run():
        loop = asyncio.get_running_loop()
        entered = asyncio.Event()
        release = threading.Event()
        calls = []
        active = 0
        maximum = 0

        def synchronize():
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            calls.append(threading.get_ident())
            try:
                if len(calls) == 1:
                    loop.call_soon_threadsafe(entered.set)
                    assert release.wait(5), "event loop did not release scan"
            finally:
                active -= 1

        harness = WatchHarness(monkeypatch, tmp_path, synchronize)
        try:
            harness.emit("first")
            await asyncio.wait_for(entered.wait(), 5)
            assert len(calls) == 1 and calls[0] != harness.loop_thread
            # The loop can accept another event while the first scan is blocked.
            harness.emit("second", "second/.Tiance/project.json")
            await asyncio.sleep(0)
            assert len(calls) == 1 and active == 1
            assert harness.notifications.empty()
            release.set()
            assert await harness.notification() == ("first",)
            assert await harness.notification() == ("second", "second/.Tiance/project.json")
            await harness.finish()
            assert len(calls) == 2 and maximum == 1 and active == 0
            assert all(thread != harness.loop_thread for thread in calls)
            assert registry.begin_close() == 0
        finally:
            release.set()
            await harness.cancel()

    asyncio.run(run())


def test_failed_scan_is_logged_without_success_notification_and_next_batch_runs(
    monkeypatch, tmp_path, registry, caplog,
):
    async def run():
        calls = []

        def synchronize():
            calls.append(True)
            if len(calls) == 1:
                raise OSError("temporary catalog failure")

        harness = WatchHarness(monkeypatch, tmp_path, synchronize)
        try:
            harness.emit("first")
            harness.emit("second")
            await harness.finish()
            assert len(calls) == 2
            assert await harness.notification() == ("second",)
            assert harness.notifications.empty()
            assert "temporary catalog failure" in caplog.text
        finally:
            await harness.cancel()

    asyncio.run(run())


def test_exit_waits_for_active_scan_not_watcher_and_resume_handles_pending_changes(
    monkeypatch, tmp_path, registry,
):
    async def run():
        loop = asyncio.get_running_loop()
        entered = asyncio.Event()
        release = threading.Event()
        calls = []

        async def close_other_owner():
            pass

        owner = SimpleNamespace(close=close_other_owner)
        monkeypatch.setattr(desktop_exit, "shutdown_tasks", registry)
        for factory in (
            "get_conversation_run_manager",
            "get_conversation_background_task_registry",
            "get_conversation_audit_service",
        ):
            monkeypatch.setattr(desktop_exit, factory, lambda: owner)
        coordinator = desktop_exit.DesktopExitCoordinator()

        def synchronize():
            calls.append(True)
            if len(calls) == 1:
                loop.call_soon_threadsafe(entered.set)
                assert release.wait(5)

        harness = WatchHarness(monkeypatch, tmp_path, synchronize)
        closing = None
        try:
            harness.emit("first")
            await asyncio.wait_for(entered.wait(), 5)
            assert coordinator.begin() > 0
            assert registry.begin_close() == 1
            closing = asyncio.create_task(coordinator.close())
            harness.emit("second")
            await asyncio.sleep(0)
            assert not closing.done()
            release.set()
            await asyncio.wait_for(closing, 5)
            assert coordinator.begin() == 0
            assert not harness.task.done()  # An idle watcher cannot hold exit open.
            assert await harness.notification() == ("first",)
            assert await harness.delivered.get() == ("first",)
            assert await harness.delivered.get() == ("second",)
            assert len(calls) == 1 and registry.begin_close() == 0
            await coordinator.abandon()
            assert await harness.notification() == ("second",)
            await harness.finish()
            assert len(calls) == 2
        finally:
            release.set()
            await harness.cancel()
            if closing is not None:
                await closing

    asyncio.run(run())


@pytest.mark.parametrize("worker_fails", [False, True])
def test_repeated_watcher_cancellation_joins_worker_even_when_worker_fails(
    monkeypatch, tmp_path, registry, worker_fails, caplog,
):
    async def run():
        loop = asyncio.get_running_loop()
        entered = asyncio.Event()
        release = threading.Event()
        finished = threading.Event()

        def synchronize():
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5)
            finished.set()
            if worker_fails:
                raise OSError("failure during cancelled scan")

        harness = WatchHarness(monkeypatch, tmp_path, synchronize)
        try:
            harness.emit("first")
            await asyncio.wait_for(entered.wait(), 5)
            harness.task.cancel()
            await asyncio.sleep(0)
            harness.task.cancel()
            await asyncio.sleep(0)
            assert not harness.task.done() and not finished.is_set()
            assert harness.notifications.empty()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(harness.task, 5)
            assert finished.is_set() and harness.notifications.empty()
            assert registry.begin_close() == 0
            if worker_fails:
                assert "failure during cancelled scan" in caplog.text
        finally:
            release.set()
            await harness.cancel()

    asyncio.run(run())


@pytest.mark.parametrize("resume", [False, True])
def test_exit_admission_wait_keeps_batch_for_resume_and_remains_cancellable(
    monkeypatch, tmp_path, registry, resume,
):
    async def run():
        calls = []
        registry.begin_close()
        harness = WatchHarness(monkeypatch, tmp_path, lambda: calls.append(True))
        try:
            harness.emit("first")
            await asyncio.wait_for(harness.delivered.get(), 5)
            assert calls == [] and not harness.task.done()
            if resume:
                registry.resume()
                assert await harness.notification() == ("first",)
                await harness.finish()
                assert calls == [True]
            else:
                harness.task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(harness.task, 5)
                assert calls == [] and registry.begin_close() == 0
        finally:
            await harness.cancel()

    asyncio.run(run())


def test_exit_before_worker_start_does_not_permanently_stop_watcher(
    monkeypatch, tmp_path, registry,
):
    async def run():
        admitted = asyncio.Event()
        original_track = registry.track

        def track(task):
            original_track(task)
            if not admitted.is_set():
                registry.begin_close()  # Task was registered but has not run yet.
                admitted.set()

        monkeypatch.setattr(registry, "track", track)
        calls = []
        harness = WatchHarness(monkeypatch, tmp_path, lambda: calls.append(True))
        try:
            harness.emit("first")
            await asyncio.wait_for(admitted.wait(), 5)
            await registry.close()
            assert calls == [] and not harness.task.done()
            registry.resume()
            assert await harness.notification() == ("first",)
            await harness.finish()
            assert calls == [True]
        finally:
            await harness.cancel()

    asyncio.run(run())


def test_internal_text_and_trash_changes_do_not_start_scan(monkeypatch, tmp_path, registry):
    async def run():
        calls = []
        harness = WatchHarness(monkeypatch, tmp_path, lambda: calls.append(True))
        try:
            harness.emit("project/README.md", ".trash/old-project")
            await harness.finish()
            assert calls == [] and harness.notifications.empty()
        finally:
            await harness.cancel()

    asyncio.run(run())


def test_real_catalog_and_identity_are_ready_when_worker_notifies(monkeypatch, tmp_path, registry):
    async def run():
        root = tmp_path / "projects"
        project_root = root / "original"
        project_root.mkdir(parents=True)
        catalog = FileProjectCatalog(root, project_kind=ProjectKind.PROJECT, allow_external_roots=True)
        service = ProjectWorkspaceReconciliationService(projects_root=root, catalog=catalog)
        harness = WatchHarness(monkeypatch, root, service.synchronize)
        try:
            harness.emit("original")
            assert await harness.notification() == ("original",)
            identity = read_project_identity(project_root)
            assert identity is not None
            assert catalog.get_project(identity.project_id).root_path == str(project_root.resolve())
            renamed = root / "renamed"
            project_root.rename(renamed)
            harness.emit("original", "renamed")
            assert await harness.notification() == ("original", "renamed")
            assert read_project_identity(renamed).project_id == identity.project_id
            assert catalog.get_project(identity.project_id).root_path == str(renamed.resolve())
            assert len(catalog.list_projects()) == 1
            await harness.finish()
        finally:
            await harness.cancel()

    asyncio.run(run())
