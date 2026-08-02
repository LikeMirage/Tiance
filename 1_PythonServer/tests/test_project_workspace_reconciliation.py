import asyncio
from pathlib import Path
import shutil

from watchfiles import Change

from app.infra.projects import read_project_identity
from app.repositories.project import FileProjectCatalog
from app.domain.project import Project, ProjectKind
from app.services.application.project_workspace_reconciliation import (
    ProjectWorkspaceReconciliationService,
)
from app.services.project import project_workspace_watcher
from app.services.project.project_workspace_watcher import (
    ProjectWorkspaceEventBroker,
    project_workspace_change_paths,
    watch_project_workspace_changes,
)


def test_sync_registers_new_folder_and_writes_stable_identity(tmp_path):
    projects_root = tmp_path / "projects"
    project_root = projects_root / "我的项目"
    project_root.mkdir(parents=True)
    catalog = FileProjectCatalog(
        projects_root,
        project_kind=ProjectKind.PROJECT,
        allow_external_roots=True,
    )

    result = _create_service(projects_root, catalog).synchronize()

    assert len(result.added_project_ids) == 1
    project = catalog.get_project(result.added_project_ids[0])
    assert project is not None
    assert project.name == "我的项目"
    assert Path(project.root_path) == project_root.resolve()
    identity = read_project_identity(project_root)
    assert identity is not None
    assert identity.project_id == project.project_id
    assert identity.name == project.name


def test_sync_uses_identity_to_preserve_project_when_folder_is_renamed(tmp_path):
    projects_root = tmp_path / "projects"
    original_root = projects_root / "原目录"
    original_root.mkdir(parents=True)
    catalog = FileProjectCatalog(
        projects_root,
        project_kind=ProjectKind.PROJECT,
        allow_external_roots=True,
    )
    service = _create_service(projects_root, catalog)
    created = service.synchronize()
    project_id = created.added_project_ids[0]
    renamed_root = projects_root / "新目录"
    original_root.rename(renamed_root)

    result = service.synchronize()

    assert result.relocated_project_ids == (project_id,)
    assert result.added_project_ids == ()
    assert result.removed_project_ids == ()
    project = catalog.get_project(project_id)
    assert project is not None
    assert Path(project.root_path) == renamed_root.resolve()


def test_sync_removes_missing_managed_project(tmp_path):
    projects_root = tmp_path / "projects"
    managed_root = projects_root / "managed"
    managed_root.mkdir(parents=True)
    catalog = FileProjectCatalog(
        projects_root,
        project_kind=ProjectKind.PROJECT,
        allow_external_roots=True,
    )
    service = _create_service(projects_root, catalog)
    created = service.synchronize()
    managed_project_id = created.added_project_ids[0]
    shutil.rmtree(managed_root)

    result = service.synchronize()

    assert result.removed_project_ids == (managed_project_id,)
    assert catalog.get_project(managed_project_id) is None


def test_sync_writes_external_identity_and_does_not_remove_missing_external_project(tmp_path):
    projects_root = tmp_path / "projects"
    external_root = tmp_path / "external-project"
    external_root.mkdir()
    catalog = FileProjectCatalog(
        projects_root,
        project_kind=ProjectKind.PROJECT,
        allow_external_roots=True,
    )
    service = _create_service(projects_root, catalog)
    service.synchronize()
    category = catalog.list_project_categories()[0]
    external_project = catalog.save_project(Project(
        project_id="4a118c53-213d-493a-85f0-dbdc80b64da5",
        name="外部项目",
        root_path=str(external_root),
        category_id=category.category_id,
        project_kind=ProjectKind.PROJECT,
        is_default=False,
        sort_order=0,
        created_at="created",
        updated_at="updated",
    ))

    service.synchronize()
    identity = read_project_identity(external_root)
    assert identity is not None
    assert identity.project_id == external_project.project_id

    shutil.rmtree(external_root)
    result = service.synchronize()

    assert result.removed_project_ids == ()
    assert catalog.get_project(external_project.project_id) is not None


def test_project_workspace_change_filter_tracks_catalog_identity_and_directories(tmp_path):
    root = tmp_path / "projects"
    changes = {
        (Change.modified, str(root / "catalog.json")),
        (Change.added, str(root / "new-project")),
        (Change.modified, str(root / "new-project" / ".Tiance" / "project.json")),
        (Change.modified, str(root / "new-project" / "README.md")),
        (Change.modified, str(root / ".trash" / "old-project")),
    }

    assert project_workspace_change_paths(root, changes) == (
        "catalog.json",
        "new-project",
        "new-project/.Tiance/project.json",
    )


def test_project_workspace_event_broker_keeps_only_latest_pending_change():
    async def scenario():
        broker = ProjectWorkspaceEventBroker()
        changes = broker.subscribe()
        first_change = asyncio.create_task(anext(changes))
        await asyncio.sleep(0)

        broker.publish(("first",))
        assert await first_change == ("first",)

        broker.publish(("second",))
        broker.publish(("third",))
        assert await anext(changes) == ("third",)
        await changes.aclose()

    asyncio.run(scenario())


def test_project_workspace_watcher_publishes_after_reconciliation(monkeypatch, tmp_path):
    project_root = tmp_path / "new-project"
    project_root.mkdir()
    published = []

    async def fake_awatch(*_args, **_kwargs):
        yield {(Change.added, str(project_root))}

    class ReconciliationService:
        synchronized = False

        def synchronize(self):
            self.synchronized = True

    class EventBroker:
        def publish(self, paths):
            assert reconciliation_service.synchronized is True
            published.append(paths)

    reconciliation_service = ReconciliationService()
    monkeypatch.setattr(project_workspace_watcher, "awatch", fake_awatch)

    asyncio.run(
        watch_project_workspace_changes(
            tmp_path,
            reconciliation_service,
            EventBroker(),
        )
    )

    assert published == [("new-project",)]


def _create_service(
    projects_root: Path,
    catalog: FileProjectCatalog,
) -> ProjectWorkspaceReconciliationService:
    return ProjectWorkspaceReconciliationService(
        projects_root=projects_root,
        catalog=catalog,
    )
