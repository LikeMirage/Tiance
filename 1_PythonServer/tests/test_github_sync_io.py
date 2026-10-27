from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from threading import Event, get_ident
from types import SimpleNamespace

import pytest

from app.core.shutdown_tasks import shutdown_tasks
from app.domain.github_sync import (
    GithubSyncBinding, GithubSyncChange, GithubSyncChangeKind, GithubSyncDirection,
    GithubSyncFile, GithubSyncPlan,
)
from app.domain.project import ProjectKind
from app.repositories.github_sync_binding_repository import GithubSyncBindingRepository
from app.services.application import github_sync as module
from app.services.application.github_sync_snapshot import collection_root
from tests.test_github_sync import _Github, _Projects, _git_sha, _settings


def _fixture(tmp_path, collection=ProjectKind.THEME):
    settings = _settings(tmp_path)
    github = _Github()
    service = module.GithubSyncService(
        settings=settings, github_client=github,
        binding_repository=GithubSyncBindingRepository(tmp_path / "sync.json"),
        project_repository=_Projects(),
    )
    root = collection_root(settings, collection)
    (root / "item").mkdir(parents=True)
    (root / "item/update.txt").write_bytes(b"old")
    (root / "item/delete.txt").write_bytes(b"remove")
    changes = (
        GithubSyncChange("item/delete.txt", GithubSyncChangeKind.DELETE, 6),
        GithubSyncChange("item/add.txt", GithubSyncChangeKind.ADD, 3),
        GithubSyncChange("item/update.txt", GithubSyncChangeKind.UPDATE, 3),
    )
    remote = {}
    for path in ("item/add.txt", "item/update.txt"):
        content = path.encode()
        sha = _git_sha(content)
        github.remote[path] = (sha, content)
        remote[path] = GithubSyncFile(path=path, size=len(content), sha=sha)
    binding = GithubSyncBinding(collection, "example/repo", "main", "", "now")
    plan = GithubSyncPlan(
        "test", collection, GithubSyncDirection.PULL, binding, "", "head", changes,
        None, None, None, "now", float("inf"),
    )
    return service, root, plan, remote


@pytest.mark.parametrize("collection", list(ProjectKind))
def test_pull_updates_adds_deletes_for_every_collection(tmp_path, monkeypatch, collection):
    service, root, plan, remote = _fixture(tmp_path, collection)
    main_thread = get_ident()
    io_threads = []
    staging_paths = []
    write = module._write_staged_file
    copy = module.shutil.copy2
    cleanup = module.TemporaryDirectory.cleanup

    def checked_write(path, content):
        io_threads.append(get_ident())
        staging_paths.append(path)
        return write(path, content)

    def checked_copy(*args, **kwargs):
        io_threads.append(get_ident())
        return copy(*args, **kwargs)

    def checked_cleanup(temporary):
        io_threads.append(get_ident())
        return cleanup(temporary)

    monkeypatch.setattr(module, "_write_staged_file", checked_write)
    monkeypatch.setattr(module.shutil, "copy2", checked_copy)
    monkeypatch.setattr(module.TemporaryDirectory, "cleanup", checked_cleanup)
    asyncio.run(service._apply_pull(plan, remote=remote, access_token="test"))
    assert not (root / "item/delete.txt").exists()
    assert (root / "item/add.txt").read_bytes() == b"item/add.txt"
    assert (root / "item/update.txt").read_bytes() == b"item/update.txt"
    assert io_threads and all(thread != main_thread for thread in io_threads)
    assert all(not path.exists() for path in staging_paths)
    assert not list(root.rglob("*.sync"))


@pytest.mark.parametrize("failure_stage", ["download", "staging", "backup", "replace"])
def test_pull_failure_preserves_old_files_and_cleans_temporary_files(tmp_path, monkeypatch, failure_stage):
    service, root, plan, remote = _fixture(tmp_path)
    temporary_roots = []
    temporary_directory = module.TemporaryDirectory

    def track_temporary(**kwargs):
        temporary = temporary_directory(**kwargs)
        temporary_roots.append(Path(temporary.name))
        return temporary

    monkeypatch.setattr(module, "TemporaryDirectory", track_temporary)
    if failure_stage == "download":
        async def fail_download(*args, **kwargs):
            raise OSError("injected download failure")
        monkeypatch.setattr(service._github, "fetch_blob", fail_download)
    elif failure_stage == "staging":
        def fail_stage(*args):
            raise OSError("injected staging failure")
        monkeypatch.setattr(module, "_write_staged_file", fail_stage)
    elif failure_stage == "backup":
        copy = module.shutil.copy2
        def fail_backup(source, target, *args, **kwargs):
            if "backup" in Path(target).parts and Path(source).name == "update.txt":
                raise OSError("injected backup failure")
            return copy(source, target, *args, **kwargs)
        monkeypatch.setattr(module.shutil, "copy2", fail_backup)
    else:
        replace = module.atomic_replace_path
        def fail_replace(source, target):
            if target.name == "update.txt":
                raise OSError("injected replace failure")
            return replace(source, target)
        monkeypatch.setattr(module, "atomic_replace_path", fail_replace)

    with pytest.raises(OSError, match="injected"):
        asyncio.run(service._apply_pull(plan, remote=remote, access_token="test"))
    assert (root / "item/update.txt").read_bytes() == b"old"
    assert (root / "item/delete.txt").read_bytes() == b"remove"
    assert not (root / "item/add.txt").exists()
    assert all(not path.exists() for path in temporary_roots)
    assert not list(root.rglob("*.sync"))


@pytest.mark.parametrize("cancel_mode", ["cancel", "shutdown"])
@pytest.mark.parametrize("phase", ["staging", "commit"])
def test_pull_cancellation_waits_for_worker_before_cleanup_and_unlock(tmp_path, monkeypatch, phase, cancel_mode):
    service, root, plan, remote = _fixture(tmp_path)
    release = Event()
    staging_paths = []

    async def run():
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        original = module._write_staged_file if phase == "staging" else service._commit_pull

        def blocked(*args):
            if phase == "staging":
                staging_paths.append(args[0])
            else:
                staging_paths.append(args[2] / "staged/item/add.txt")
            loop.call_soon_threadsafe(started.set)
            if not release.wait(3):
                raise TimeoutError("event loop did not release the worker")
            return original(*args)

        if phase == "staging":
            monkeypatch.setattr(module, "_write_staged_file", blocked)
        else:
            monkeypatch.setattr(service, "_commit_pull", blocked)

        lock = service._locks[plan.collection]
        async def locked_pull():
            async with lock:
                await service._apply_pull(plan, remote=remote, access_token="test")

        task = asyncio.create_task(locked_pull())
        try:
            # This event can only be delivered if file I/O does not block the loop.
            await asyncio.wait_for(started.wait(), 2)
            if cancel_mode == "shutdown":
                assert shutdown_tasks.begin_close() == 1
            else:
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
            await asyncio.sleep(0.02)
            assert not task.done()
            assert lock.locked()
            if phase == "commit":
                assert staging_paths[0].exists()
            release.set()
            if cancel_mode == "shutdown" and phase == "commit":
                await task
            elif cancel_mode == "shutdown":
                from app.core.errors import AppError
                with pytest.raises(AppError, match="本次操作已停止"):
                    await task
            else:
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert not lock.locked()
            assert all(not path.exists() for path in staging_paths)
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            shutdown_tasks.resume()

    asyncio.run(run())
    if phase == "staging":
        assert (root / "item/update.txt").read_bytes() == b"old"
        assert (root / "item/delete.txt").exists()
        assert not (root / "item/add.txt").exists()
    else:
        assert (root / "item/update.txt").read_bytes() == b"item/update.txt"
        assert not (root / "item/delete.txt").exists()


def test_public_apply_plan_uses_pull_worker(tmp_path):
    service, root, _, _ = _fixture(tmp_path)
    service._github.head_sha = "head"
    service._github.tree_sha = "tree"

    async def run():
        await service.save_binding(
            collection=ProjectKind.THEME, repository="example/repo", branch="main", remote_path="",
        )
        plan = await service.create_plan(collection=ProjectKind.THEME, direction=GithubSyncDirection.PULL)
        result, head = await service.apply_plan(plan.plan_id)
        assert result == plan and head == "head"
        assert plan.plan_id not in service._plans

    asyncio.run(run())
    assert (root / "item/update.txt").read_bytes() == b"item/update.txt"
    assert not (root / "item/delete.txt").exists()


def test_project_pull_preserves_external_root_and_merged_catalog(tmp_path):
    service, root, plan, remote = _fixture(tmp_path, ProjectKind.PROJECT)
    external = tmp_path / "external-project"
    external.mkdir()
    (external / "update.txt").write_bytes(b"external old")
    (external / "delete.txt").write_bytes(b"external remove")
    service._projects = _Projects((SimpleNamespace(project_id="item", root_path=str(external)),))
    catalog = b'{"schema_version":1,"projects":[]}'
    plan = replace(
        plan, catalog_content=catalog,
        changes=(*plan.changes, GithubSyncChange("catalog.json", GithubSyncChangeKind.ADD, len(catalog))),
    )
    # catalog.json is intentionally absent from remote: use the merged content.
    asyncio.run(service._apply_pull(plan, remote=remote, access_token="test"))
    assert (root / "catalog.json").read_bytes() == catalog
    assert (external / "update.txt").read_bytes() == b"item/update.txt"
    assert (external / "add.txt").read_bytes() == b"item/add.txt"
    assert not (external / "delete.txt").exists()
    assert (root / "item/update.txt").read_bytes() == b"old"
    assert not list(external.glob("*.sync"))
