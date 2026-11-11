import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.errors import BadRequestError, ConflictError
from app.domain.project import ProjectKind
from app.infra.database import ensure_database_schema
from app.infra.projects import ProjectStorage, project_storage
from app.infra.projects.workspace_lifecycle import workspace_access, workspace_removal
from app.repositories.project.conversation_database import ensure_database, write_meta
from app.repositories.project.conversation_storage import ProjectWorkspaceDirectoryResolver
from app.repositories.project.file_project_catalog import FileProjectCatalog
from app.services.application.project_removal import ProjectRemovalApplicationService
from app.services.project.projects import ProjectService
from tests.project_test_support import make_project_repository


@pytest.fixture
def setup(tmp_path):
    database = tmp_path / 'global.db'
    ensure_database_schema(database)
    managed = tmp_path / 'managed'
    repository = make_project_repository(database, file_catalogs=(
        FileProjectCatalog(managed, project_kind=ProjectKind.PROJECT, allow_external_roots=True),
    ))
    storage = ProjectStorage(managed)
    service = ProjectService(repository, storage)
    root = tmp_path / 'work'
    root.mkdir()
    (root / 'work.txt').write_text('work file untouched')
    # Nested projects and their metadata must not be cleaned recursively.
    nested = root / 'nested' / '.Tiance'
    nested.mkdir(parents=True)
    (nested / 'proof').write_text('nested untouched')
    project = service.create_project(name='work', root_path=str(root))
    workspace = root / '.Tiance'
    ensure_database(workspace)
    write_meta(workspace / 'conversations', 'proof', {'data': 'preserved in recycle bin'})
    (workspace / 'attachment.png').write_bytes(b'test attachment')
    owners = [SimpleNamespace(has_project_activity=lambda _: False) for _ in range(3)]
    app = ProjectRemovalApplicationService(service, storage, *owners)
    return app, service, repository, project, root, workspace, owners


def test_default_remove_preserves_workspace(setup, fake_system_recycle):
    _, service, repo, project, root, workspace, _ = setup
    service.delete_project(project.project_id)
    assert repo.get_project(project.project_id) is None
    assert (workspace / 'tiance.db').is_file()
    assert (root / 'work.txt').is_file()
    assert not fake_system_recycle


def test_cleanup_only_recycles_root_metadata_and_allows_explicit_reimport(setup, fake_system_recycle):
    app, service, repo, project, root, workspace, _ = setup
    asyncio.run(app.remove_with_data(project.project_id))
    assert repo.get_project(project.project_id) is None
    assert len(fake_system_recycle) == 1
    assert fake_system_recycle[0][0] == workspace
    assert (fake_system_recycle[0][1] / 'attachment.png').read_bytes() == b'test attachment'
    assert (root / 'work.txt').read_text() == 'work file untouched'
    assert (root / 'nested/.Tiance/proof').read_text() == 'nested untouched'
    assert not workspace.exists()
    # Requests that already resolved a path may arrive after deregistration.
    with pytest.raises(ConflictError):
        write_meta(workspace / 'conversations', 'late', 1)
    with pytest.raises(ConflictError):
        ProjectWorkspaceDirectoryResolver().resolve_workspace_dir(root, for_write=True)
    assert not workspace.exists()
    service.create_project(name='again', root_path=str(root))
    ensure_database(workspace)
    assert workspace.is_dir()


@pytest.mark.parametrize('owner', [0, 1, 2])
def test_active_run_background_or_audit_prevents_cleanup(setup, fake_system_recycle, owner):
    app, _, repo, project, _, workspace, owners = setup
    owners[owner].has_project_activity = lambda _: True
    with pytest.raises(ConflictError, match='后台任务'):
        asyncio.run(app.remove_with_data(project.project_id))
    assert repo.get_project(project.project_id)
    assert workspace.is_dir() and not fake_system_recycle
    write_meta(workspace / 'conversations', 'still_writable', True)


def test_inflight_database_writer_prevents_cleanup(setup, fake_system_recycle):
    from app.repositories.project.conversation_database import connection_for_path
    app, _, repo, project, _, workspace, _ = setup
    with connection_for_path(workspace / 'tiance.db'):
        with pytest.raises(ConflictError, match='读写'):
            asyncio.run(app.remove_with_data(project.project_id))
    assert repo.get_project(project.project_id) and not fake_system_recycle


def test_recycle_failure_keeps_registration_and_restores_access(setup, monkeypatch):
    app, _, repo, project, _, workspace, _ = setup
    def fail(_):
        raise OSError('locked')
    monkeypatch.setattr(project_storage, 'recycle_path', fail)
    with pytest.raises(BadRequestError, match='登记已保留'):
        asyncio.run(app.remove_with_data(project.project_id))
    assert repo.get_project(project.project_id)
    write_meta(workspace / 'conversations', 'still_writable', True)


def test_deregistration_failure_can_retry_without_recreating_metadata(setup, fake_system_recycle, monkeypatch):
    app, _, repo, project, root, workspace, _ = setup
    original = repo.delete_project
    def fail(_):
        raise OSError('catalog locked')
    monkeypatch.setattr(repo, 'delete_project', fail)
    with pytest.raises(BadRequestError) as error:
        asyncio.run(app.remove_with_data(project.project_id))
    assert error.value.details['tiance_data_cleared']
    assert repo.get_project(project.project_id) and not workspace.exists()
    with pytest.raises(ConflictError):
        ensure_database(workspace)
    monkeypatch.setattr(repo, 'delete_project', original)
    asyncio.run(app.remove_with_data(project.project_id))
    assert len(fake_system_recycle) == 1 and repo.get_project(project.project_id) is None
    assert (root / 'work.txt').is_file()


def test_missing_metadata_is_not_created_to_remove_it(setup, fake_system_recycle):
    app, service, repo, _, root, _, _ = setup
    empty = root.parent / 'empty'
    empty.mkdir()
    project = service.create_project(name='empty', root_path=str(empty))
    asyncio.run(app.remove_with_data(project.project_id))
    assert repo.get_project(project.project_id) is None
    assert not (empty / '.Tiance').exists() and not fake_system_recycle


def test_managed_project_rejects_data_only_removal(setup, fake_system_recycle):
    app, service, repo, _, _, _, _ = setup
    project = service.create_project(name='managed')
    with pytest.raises(BadRequestError, match='外部项目'):
        asyncio.run(app.remove_with_data(project.project_id))
    assert repo.get_project(project.project_id) and not fake_system_recycle


def test_workspace_link_is_rejected_before_recycling(tmp_path, monkeypatch):
    storage = ProjectStorage(tmp_path / 'managed')
    root = tmp_path / 'external'
    root.mkdir()
    monkeypatch.setattr(project_storage, '_is_link_like', lambda p: p.name == '.Tiance')
    monkeypatch.setattr(project_storage, 'recycle_path', lambda _: pytest.fail('must not recycle link'))
    with pytest.raises(ValueError, match='符号链接'):
        storage.recycle_project_data(str(root))


def test_data_cleanup_can_target_external_app_root_without_touching_collections(tmp_path, fake_system_recycle):
    storage = ProjectStorage(tmp_path / 'app' / 'Data' / 'projects')
    workspace = tmp_path / 'app' / '.Tiance'
    workspace.mkdir(parents=True)
    storage.projects_root.mkdir(parents=True)
    assert storage.recycle_project_data(str(tmp_path / 'app'))
    assert fake_system_recycle[0][0] == workspace
    assert storage.projects_root.is_dir()


def test_cleanup_reservation_blocks_new_io_and_registration(tmp_path):
    workspace = tmp_path / '.Tiance'
    with workspace_removal(workspace):
        for registering in (False, True):
            with pytest.raises(ConflictError):
                with workspace_access(workspace, registering=registering):
                    pytest.fail('cleanup reservation must exclude new writers')
    ensure_database(workspace)


def test_route_only_selects_cleanup_when_explicitly_requested(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes.project import core
    from app.services.application import project_removal
    calls = []
    class Projects:
        def get_project(self, _): return None
        def delete_project(self, project_id, **options): calls.append((project_id, options))
    class Removal:
        async def remove_with_data(self, project_id): calls.append(('cleanup', project_id))
    monkeypatch.setattr(core, 'get_project_service', lambda: Projects())
    monkeypatch.setattr(project_removal, 'get_project_removal_application_service', lambda: Removal())
    app = FastAPI()
    from app.core.errors import AppError, app_error_handler
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(core.router)
    with TestClient(app) as client:
        assert client.delete('/projects/test').status_code == 204
        assert client.delete('/projects/test?clear_tiance_data=true').status_code == 204
        assert client.delete('/projects/test?clear_tiance_data=true&delete_files=true').status_code == 400
    assert calls == [('test', {'delete_files': False}), ('cleanup', 'test')]


def test_real_activity_owners_include_cancellation_and_pending_audit():
    from app.services.project.conversation_background_tasks import ConversationBackgroundTaskRegistry
    from app.services.project.conversation_run_manager import ConversationRunManager
    from app.services.project.conversation_audit import ConversationAuditService

    async def scenario():
        started = asyncio.Event()
        finish = asyncio.Event()
        async def work():
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await finish.wait()
        registry = ConversationBackgroundTaskRegistry()
        task = registry.create_task('project', 'session', work(), name='test-background')
        manager = ConversationRunManager()
        manager._runs['project:session'] = SimpleNamespace(task=task)
        audit = ConversationAuditService(None)
        audit._tasks[('project', 'session')] = {task}
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        for owner in (manager, registry, audit):
            assert owner.has_project_activity('project')
            assert not owner.has_project_activity('other')
        finish.set()
        await task
        for owner in (manager, registry, audit):
            assert not owner.has_project_activity('project')
        audit._failed_session_writes['failed'] = ('project', 'session', None, 'test')
        assert audit.has_project_activity('project')
    asyncio.run(scenario())
