from datetime import UTC, datetime
from json import loads
from pathlib import Path

import pytest

from app.domain.project import Project, ProjectCategory, ProjectKind
from app.infra.database import ensure_database_schema
from app.infra.projects import ProjectStorage
from app.repositories.project.file_project_catalog import FileProjectCatalog
from app.repositories.project.project_repository import ProjectRepository
from app.services.application.project_file_catalog_migration import (
    FILE_CATALOG_PROJECT_KINDS,
    ProjectFileCatalogMigrationService,
)
from app.services.project.projects import ProjectService


def test_file_project_catalog_requires_complete_catalog_shape(tmp_path):
    root = tmp_path / "tools"
    root.mkdir()
    (root / "catalog.json").write_text(
        '{"schema_version": 1, "categories": [], "projects": []}\n',
        encoding="utf-8",
    )
    catalog = FileProjectCatalog(root, project_kind=ProjectKind.TOOL)

    with pytest.raises(ValueError, match="metadata"):
        catalog.list_projects()


def test_file_project_catalog_persists_logical_categories_without_folders(tmp_path):
    root = tmp_path / "tools"
    catalog = FileProjectCatalog(root, project_kind=ProjectKind.TOOL)
    now = datetime.now(UTC).isoformat()
    category = ProjectCategory(
        category_id="basic-tools",
        name="基础工具",
        category_kind=ProjectKind.TOOL,
        is_default=True,
        sort_order=0,
        created_at=now,
        updated_at=now,
    )
    project = Project(
        project_id="tool-project-id",
        name="文件读取",
        root_path=str(root / "tool-project-id"),
        category_id=category.category_id,
        project_kind=ProjectKind.TOOL,
        is_default=False,
        sort_order=0,
        created_at=now,
        updated_at=now,
    )

    catalog.save_project_category(category)
    catalog.save_project(project)

    assert catalog.list_project_categories() == (category,)
    loaded = catalog.get_project(project.project_id)
    assert loaded == Project(
        project_id=project.project_id,
        name=project.name,
        root_path=str((root / project.project_id).resolve()),
        category_id=project.category_id,
        project_kind=project.project_kind,
        is_default=project.is_default,
        sort_order=project.sort_order,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )
    assert {item.name for item in root.iterdir()} == {"catalog.json"}


def test_file_project_catalog_moves_projects_by_record_only(tmp_path):
    root = tmp_path / "tools"
    catalog = FileProjectCatalog(root, project_kind=ProjectKind.TOOL)
    now = datetime.now(UTC).isoformat()
    for category_id, name, is_default in (
        ("first", "第一类", True),
        ("second", "第二类", False),
    ):
        catalog.save_project_category(ProjectCategory(
            category_id=category_id,
            name=name,
            category_kind=ProjectKind.TOOL,
            is_default=is_default,
            sort_order=0 if is_default else 1,
            created_at=now,
            updated_at=now,
        ))
    project_root = root / "project-id"
    project_root.mkdir(parents=True)
    catalog.save_project(Project(
        project_id="project-id",
        name="工具",
        root_path=str(project_root),
        category_id="first",
        project_kind=ProjectKind.TOOL,
        is_default=False,
        sort_order=0,
        created_at=now,
        updated_at=now,
    ))

    catalog.move_projects_to_category(
        source_category_id="first",
        target_category_id="second",
        updated_at=now,
    )

    assert catalog.get_project("project-id").category_id == "second"
    assert project_root.is_dir()


def test_file_project_catalog_preserves_direct_child_directory_name(tmp_path):
    root = tmp_path / "themes"
    theme_root = root / "theme-slug"
    theme_root.mkdir(parents=True)
    catalog = FileProjectCatalog(root, project_kind=ProjectKind.THEME)
    now = datetime.now(UTC).isoformat()
    category = ProjectCategory(
        category_id="theme-category",
        name="主题",
        category_kind=ProjectKind.THEME,
        is_default=True,
        sort_order=0,
        created_at=now,
        updated_at=now,
    )
    project = Project(
        project_id="theme-project-uuid",
        name="主题",
        root_path=str(theme_root),
        category_id=category.category_id,
        project_kind=ProjectKind.THEME,
        is_default=False,
        sort_order=0,
        created_at=now,
        updated_at=now,
    )

    catalog.save_project_category(category)
    catalog.save_project(project)

    assert catalog.get_project(project.project_id).root_path == str(theme_root.resolve())
    payload = loads((root / "catalog.json").read_text(encoding="utf-8"))
    assert payload["projects"][0]["root_name"] == "theme-slug"


def test_project_catalog_preserves_external_root_path(tmp_path):
    root = tmp_path / "projects"
    external_root = tmp_path / "external-workspace"
    external_root.mkdir()
    catalog = FileProjectCatalog(
        root,
        project_kind=ProjectKind.PROJECT,
        allow_external_roots=True,
    )
    now = datetime.now(UTC).isoformat()
    category = ProjectCategory(
        category_id="daily-project",
        name="日常项目",
        category_kind=ProjectKind.PROJECT,
        is_default=True,
        sort_order=0,
        created_at=now,
        updated_at=now,
    )
    project = Project(
        project_id="external-project",
        name="外部项目",
        root_path=str(external_root),
        category_id=category.category_id,
        project_kind=ProjectKind.PROJECT,
        is_default=False,
        sort_order=0,
        created_at=now,
        updated_at=now,
    )

    catalog.save_project_category(category)
    catalog.save_project(project)

    assert catalog.get_project(project.project_id) == Project(
        project_id=project.project_id,
        name=project.name,
        root_path=str(external_root.resolve()),
        category_id=project.category_id,
        project_kind=project.project_kind,
        is_default=project.is_default,
        sort_order=project.sort_order,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )
    payload = loads((root / "catalog.json").read_text(encoding="utf-8"))
    assert payload["projects"][0]["root_path"] == str(external_root.resolve())
    assert "root_name" not in payload["projects"][0]


def test_project_service_uses_catalog_and_preserves_external_delete_contract(
    tmp_path,
):
    database_path = tmp_path / "tiance.db"
    projects_root = tmp_path / "projects"
    external_root = tmp_path / "external-project"
    external_root.mkdir()
    external_file = external_root / "note.txt"
    external_file.write_text("keep", encoding="utf-8")
    ensure_database_schema(database_path)
    catalogs = tuple(
        FileProjectCatalog(
            (
                projects_root
                if project_kind is ProjectKind.PROJECT
                else tmp_path / project_kind.value
            ),
            project_kind=project_kind,
            allow_external_roots=project_kind is ProjectKind.PROJECT,
        )
        for project_kind in FILE_CATALOG_PROJECT_KINDS
    )
    repository = ProjectRepository(database_path, file_catalogs=catalogs)
    ProjectFileCatalogMigrationService(repository).migrate()
    catalog = repository.get_file_catalog(ProjectKind.PROJECT)
    assert catalog is not None
    service = ProjectService(repository, ProjectStorage(projects_root))

    managed_project = service.create_project(name="托管项目")
    external_project = service.create_project(
        name="外部项目",
        root_path=str(external_root),
    )
    service.save_project_order(
        (external_project.project_id, managed_project.project_id)
    )

    assert catalog.catalog_path.is_file()
    assert service.get_project_order() == (
        external_project.project_id,
        managed_project.project_id,
    )
    assert repository.list_database_projects(project_kind=ProjectKind.PROJECT) == ()
    assert (
        repository.list_database_project_categories(
            category_kind=ProjectKind.PROJECT
        )
        == ()
    )

    service.delete_project(external_project.project_id)

    assert repository.get_project(external_project.project_id) is None
    assert external_file.read_text(encoding="utf-8") == "keep"


def test_file_project_service_deletes_category_projects_and_does_not_recreate_default(
    tmp_path,
):
    database_path = tmp_path / "tiance.db"
    projects_root = tmp_path / "projects"
    ensure_database_schema(database_path)
    catalogs = tuple(
        FileProjectCatalog(
            projects_root if kind is ProjectKind.PROJECT else tmp_path / kind.value,
            project_kind=kind,
            allow_external_roots=kind is ProjectKind.PROJECT,
        )
        for kind in FILE_CATALOG_PROJECT_KINDS
    )
    repository = ProjectRepository(database_path, file_catalogs=catalogs)
    service = ProjectService(repository, ProjectStorage(projects_root))
    service.ensure_builtin_project_categories()
    category = service.create_project_category(name="待删除分类")
    project = service.create_project(name="待删除项目", category_id=category.category_id)

    service.delete_project_category(category.category_id)
    service.delete_project_category("daily-project")

    assert repository.get_project(project.project_id) is None
    assert not Path(project.root_path).exists()
    assert repository.get_project_category(category.category_id) is None
    assert all(
        item.category_id != "daily-project"
        for item in service.list_project_categories()
    )


def test_file_project_catalog_saves_project_order_inside_each_category(tmp_path):
    root = tmp_path / "knowledge"
    catalog = FileProjectCatalog(root, project_kind=ProjectKind.KNOWLEDGE)
    now = datetime.now(UTC).isoformat()
    for category_id, sort_order in (("first", 0), ("second", 1)):
        catalog.save_project_category(ProjectCategory(
            category_id=category_id,
            name=category_id,
            category_kind=ProjectKind.KNOWLEDGE,
            is_default=category_id == "first",
            sort_order=sort_order,
            created_at=now,
            updated_at=now,
        ))
    for category_id, project_id, sort_order in (
        ("first", "first-a", 0),
        ("first", "first-b", 1),
        ("second", "second-a", 0),
        ("second", "second-b", 1),
    ):
        catalog.save_project(Project(
            project_id=project_id,
            name=project_id,
            root_path=str(root / project_id),
            category_id=category_id,
            project_kind=ProjectKind.KNOWLEDGE,
            is_default=False,
            sort_order=sort_order,
            created_at=now,
            updated_at=now,
        ))

    catalog.save_project_order(("second-b", "first-b", "second-a", "first-a"))

    projects = catalog.list_projects()
    assert [
        project.project_id
        for project in projects
        if project.category_id == "first"
    ] == ["first-b", "first-a"]
    assert [
        project.project_id
        for project in projects
        if project.category_id == "second"
    ] == ["second-b", "second-a"]

    catalog.save_category_order(("second", "first"))

    assert [
        category.category_id
        for category in catalog.list_project_categories()
    ] == ["second", "first"]
    assert [
        category.sort_order
        for category in catalog.list_project_categories()
    ] == [0, 1]
