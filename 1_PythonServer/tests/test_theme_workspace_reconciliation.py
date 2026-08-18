import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path

from watchfiles import Change

from app.domain.project import Project, ProjectCategory, ProjectKind
from app.repositories.project import FileProjectCatalog
from app.repositories.themes import ThemeSettingsRepository
from app.services.application.theme_workspace_reconciliation import (
    ThemeWorkspaceReconciliationService,
)
from app.services.themes.theme_workspace_watcher import (
    ThemeWorkspaceEventBroker,
    theme_workspace_change_paths,
    watch_theme_workspace_changes,
)
from app.services.themes import theme_workspace_watcher


RECOVERY_ROOT = Path(__file__).resolve().parents[1] / "app" / "resources" / "themes"


def test_empty_theme_workspace_restores_builtins_catalog_and_active_selection(tmp_path):
    themes_root = tmp_path / "themes"
    catalog = FileProjectCatalog(themes_root, project_kind=ProjectKind.THEME)
    settings_repository = ThemeSettingsRepository(themes_root / "theme-settings.json")
    settings_repository.save_active_theme_id("missing-theme")
    service = _create_service(themes_root, catalog, settings_repository)

    result = service.synchronize()

    assert result.restored_theme_ids == ("dark-gold", "light")
    assert result.active_theme_id == "dark-gold"
    assert settings_repository.get_active_theme_id() == "dark-gold"
    assert {
        Path(project.root_path).name
        for project in catalog.list_projects()
    } == {"dark-gold", "light"}
    assert (themes_root / "catalog.json").is_file()
    assert (themes_root / "dark-gold" / "theme.json").is_file()
    assert (themes_root / "light" / "theme.json").is_file()


def test_sync_preserves_name_category_and_sort_for_existing_theme(tmp_path):
    themes_root = tmp_path / "themes"
    catalog = FileProjectCatalog(themes_root, project_kind=ProjectKind.THEME)
    settings_repository = ThemeSettingsRepository(themes_root / "theme-settings.json")
    service = _create_service(themes_root, catalog, settings_repository)
    service.synchronize()

    custom_root = themes_root / "custom-theme"
    _write_theme(custom_root, theme_id="custom-theme", name="自定义主题")
    service.synchronize()
    custom_project = catalog.get_project_by_root_path(str(custom_root))
    assert custom_project is not None

    now = datetime.now(UTC).isoformat()
    custom_category = catalog.save_project_category(ProjectCategory(
        category_id="my-category",
        name="我的分类",
        category_kind=ProjectKind.THEME,
        is_default=False,
        sort_order=1,
        created_at=now,
        updated_at=now,
    ))
    catalog.save_project(Project(
        project_id=custom_project.project_id,
        name="用户显示名称",
        root_path=custom_project.root_path,
        category_id=custom_category.category_id,
        project_kind=ProjectKind.THEME,
        is_default=False,
        sort_order=9,
        created_at=custom_project.created_at,
        updated_at=custom_project.updated_at,
    ))
    _write_theme(custom_root, theme_id="custom-theme", name="文件中的新名称")

    result = service.synchronize()
    updated = catalog.get_project(custom_project.project_id)

    assert result.added_project_ids == ()
    assert updated is not None
    assert updated.name == "用户显示名称"
    assert updated.category_id == "my-category"
    assert updated.sort_order == 9


def test_sync_removes_missing_folder_but_ignores_invalid_new_folder(tmp_path):
    themes_root = tmp_path / "themes"
    catalog = FileProjectCatalog(themes_root, project_kind=ProjectKind.THEME)
    settings_repository = ThemeSettingsRepository(themes_root / "theme-settings.json")
    service = _create_service(themes_root, catalog, settings_repository)
    service.synchronize()

    custom_root = themes_root / "custom-theme"
    _write_theme(custom_root, theme_id="custom-theme", name="自定义主题")
    service.synchronize()
    custom_project = catalog.get_project_by_root_path(str(custom_root))
    assert custom_project is not None

    (custom_root / "theme.json").unlink()
    custom_root.rmdir()
    invalid_root = themes_root / "broken-theme"
    invalid_root.mkdir()
    (invalid_root / "theme.json").write_text("not-json", encoding="utf-8")
    settings_repository.save_active_theme_id("broken-theme")

    result = service.synchronize()

    assert result.removed_project_ids == (custom_project.project_id,)
    assert result.invalid_directories == ("broken-theme",)
    assert catalog.get_project(custom_project.project_id) is None
    assert catalog.get_project_by_root_path(str(invalid_root)) is None
    assert settings_repository.get_active_theme_id() == "dark-gold"


def test_theme_workspace_change_filter_tracks_state_files_and_ignores_assets(tmp_path):
    root = tmp_path / "themes"
    changes = {
        (Change.modified, str(root / "catalog.json")),
        (Change.modified, str(root / "theme-settings.json")),
        (Change.deleted, str(root / "theme-settings.json")),
        (Change.modified, str(root / "dark-gold" / "preview.webp")),
        (Change.modified, str(root / "dark-gold" / "theme.json")),
        (Change.added, str(root / "new-theme")),
    }

    assert theme_workspace_change_paths(root, changes) == (
        "catalog.json",
        "dark-gold/theme.json",
        "new-theme",
        "theme-settings.json",
    )


def test_theme_workspace_event_broker_keeps_only_latest_pending_change():
    async def scenario():
        broker = ThemeWorkspaceEventBroker()
        changes = broker.subscribe()
        first_change = asyncio.create_task(anext(changes))
        await asyncio.sleep(0)

        broker.publish(("dark-gold/theme.json",))
        assert await first_change == ("dark-gold/theme.json",)

        broker.publish(("light/theme.json",))
        broker.publish(("cloud-gate/theme.json",))
        assert await anext(changes) == ("cloud-gate/theme.json",)
        await changes.aclose()

    asyncio.run(scenario())


def test_theme_workspace_watcher_publishes_only_after_reconciliation(monkeypatch, tmp_path):
    theme_file = tmp_path / "dark-gold" / "theme.json"
    theme_file.parent.mkdir()
    theme_file.write_text("{}", encoding="utf-8")
    published = []

    async def fake_awatch(*_args, **_kwargs):
        yield {(Change.modified, str(theme_file))}

    class ReconciliationService:
        synchronized = False

        def synchronize(self):
            self.synchronized = True

    class EventBroker:
        def publish(self, paths):
            assert reconciliation_service.synchronized is True
            published.append(paths)

    reconciliation_service = ReconciliationService()
    monkeypatch.setattr(theme_workspace_watcher, "awatch", fake_awatch)

    asyncio.run(
        watch_theme_workspace_changes(
            tmp_path,
            reconciliation_service,
            EventBroker(),
        )
    )

    assert published == [("dark-gold/theme.json",)]


def test_invalid_catalog_is_archived_and_rebuilt(tmp_path):
    themes_root = tmp_path / "themes"
    themes_root.mkdir()
    (themes_root / "catalog.json").write_text("not-json", encoding="utf-8")
    catalog = FileProjectCatalog(themes_root, project_kind=ProjectKind.THEME)
    settings_repository = ThemeSettingsRepository(themes_root / "theme-settings.json")

    result = _create_service(themes_root, catalog, settings_repository).synchronize()

    assert result.recovered_catalog_path is not None
    assert Path(result.recovered_catalog_path).read_text(encoding="utf-8") == "not-json"
    assert len(catalog.list_projects()) == 2
    assert (themes_root / "catalog.json").is_file()


def _create_service(
    themes_root: Path,
    catalog: FileProjectCatalog,
    settings_repository: ThemeSettingsRepository,
) -> ThemeWorkspaceReconciliationService:
    return ThemeWorkspaceReconciliationService(
        themes_root=themes_root,
        recovery_root=RECOVERY_ROOT,
        catalog=catalog,
        settings_repository=settings_repository,
    )


def _write_theme(theme_root: Path, *, theme_id: str, name: str) -> None:
    payload = json.loads((RECOVERY_ROOT / "light.json").read_text(encoding="utf-8"))
    payload["id"] = theme_id
    payload["registrationName"] = name
    theme_root.mkdir(parents=True, exist_ok=True)
    (theme_root / "theme.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
