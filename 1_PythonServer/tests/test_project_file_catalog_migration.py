from datetime import UTC, datetime
from json import loads

from app.domain.project import Project, ProjectCategory, ProjectKind
from app.infra.database import ensure_database_schema
from app.repositories.project.file_project_catalog import FileProjectCatalog
from app.repositories.project.project_repository import ProjectRepository
from app.services.application.project_file_catalog_migration import (
    FILE_CATALOG_PROJECT_KINDS,
    ProjectFileCatalogMigrationService,
)


def test_file_backed_project_catalogs_migrate_out_of_sqlite(tmp_path):
    database_path = tmp_path / "tiance.db"
    projects_root = tmp_path / "projects"
    external_project_root = tmp_path / "external-project"
    external_project_root.mkdir()
    knowledge_root = tmp_path / "knowledge"
    experience_root = tmp_path / "experience"
    roles_root = tmp_path / "roles"
    themes_root = tmp_path / "themes"
    providers_root = tmp_path / "providers"
    ensure_database_schema(database_path)
    database_repository = ProjectRepository(database_path)
    now = datetime.now(UTC).isoformat()

    records = (
        (
            ProjectKind.PROJECT,
            projects_root,
            "daily-project",
            "日常项目",
            "project-external-project",
            "外部项目",
        ),
        (
            ProjectKind.KNOWLEDGE,
            knowledge_root,
            "knowledge-category",
            "知识分类",
            "knowledge-project",
            "知识项目",
        ),
        (
            ProjectKind.EXPERIENCE,
            experience_root,
            "experience-category",
            "经验分类",
            "experience-project",
            "经验项目",
        ),
        (
            ProjectKind.ROLE,
            roles_root,
            "default-role-category",
            "基础角色",
            "role-project",
            "角色项目",
        ),
        (
            ProjectKind.THEME,
            themes_root,
            "default-theme-category",
            "基础主题",
            "theme-project",
            "主题项目",
        ),
        (
            ProjectKind.PROVIDER,
            providers_root,
            "default-provider-category",
            "模型供应商",
            "provider-project",
            "供应商项目",
        ),
    )
    for project_kind, root, category_id, category_name, project_id, project_name in records:
        root.mkdir(parents=True, exist_ok=True)
        project_root = (
            external_project_root
            if project_kind is ProjectKind.PROJECT
            else root / ("theme-slug" if project_kind is ProjectKind.THEME else project_id)
        )
        project_root.mkdir(exist_ok=True)
        database_repository.save_project_category(ProjectCategory(
            category_id=category_id,
            name=category_name,
            category_kind=project_kind,
            is_default=True,
            sort_order=0,
            created_at=now,
            updated_at=now,
        ))
        database_repository.save_project(Project(
            project_id=project_id,
            name=project_name,
            root_path=str(project_root),
            category_id=category_id,
            project_kind=project_kind,
            is_default=False,
            sort_order=0,
            created_at=now,
            updated_at=now,
        ))
    database_repository.set_metadata_value(
        key="projects.order",
        value=(
            '["knowledge-project", "project-external-project", "experience-project", '
            '"role-project", "theme-project", "provider-project"]'
        ),
        updated_at=now,
    )
    database_repository.set_metadata_value(
        key="projects.default_project_bootstrapped",
        value="1",
        updated_at=now,
    )

    repository = ProjectRepository(
        database_path,
        file_catalogs=(
            FileProjectCatalog(
                projects_root,
                project_kind=ProjectKind.PROJECT,
                allow_external_roots=True,
            ),
            FileProjectCatalog(knowledge_root, project_kind=ProjectKind.KNOWLEDGE),
            FileProjectCatalog(experience_root, project_kind=ProjectKind.EXPERIENCE),
            FileProjectCatalog(roles_root, project_kind=ProjectKind.ROLE),
            FileProjectCatalog(themes_root, project_kind=ProjectKind.THEME),
            FileProjectCatalog(providers_root, project_kind=ProjectKind.PROVIDER),
        ),
    )
    migration = ProjectFileCatalogMigrationService(repository)
    migration.migrate()

    assert (projects_root / "catalog.json").is_file()
    assert (knowledge_root / "catalog.json").is_file()
    assert (experience_root / "catalog.json").is_file()
    assert (roles_root / "catalog.json").is_file()
    assert (themes_root / "catalog.json").is_file()
    assert (providers_root / "catalog.json").is_file()
    for project_kind in (
        ProjectKind.PROJECT,
        ProjectKind.KNOWLEDGE,
        ProjectKind.EXPERIENCE,
        ProjectKind.ROLE,
        ProjectKind.THEME,
        ProjectKind.PROVIDER,
    ):
        assert repository.list_database_projects(project_kind=project_kind) == ()
        assert repository.list_database_project_categories(
            category_kind=project_kind,
        ) == ()
    assert repository.get_project("project-external-project").root_path == str(
        external_project_root.resolve()
    )
    assert repository.get_project("knowledge-project").category_id == "knowledge-category"
    assert repository.get_project("experience-project").category_id == "experience-category"
    assert repository.get_project("role-project").category_id == "default-role-category"
    assert repository.get_project("theme-project").category_id == "default-theme-category"
    assert repository.get_project("provider-project").category_id == "default-provider-category"
    assert repository.get_project("theme-project").root_path == str(
        (themes_root / "theme-slug").resolve()
    )
    assert repository.get_project("knowledge-project").sort_order == 0
    assert repository.get_project("experience-project").sort_order == 0
    assert repository.get_metadata_value("projects.order") is None
    assert repository.get_metadata_value("projects.default_project_bootstrapped") is None
    project_catalog = repository.get_file_catalog(ProjectKind.PROJECT)
    assert project_catalog is not None
    assert project_catalog.get_metadata_value(
        "projects.default_project_bootstrapped"
    ) == "1"

    migration.migrate()
    assert repository.get_project("project-external-project") is not None
    assert repository.get_project("knowledge-project") is not None
    assert repository.get_project("experience-project") is not None
    assert repository.get_project("role-project") is not None
    assert repository.get_project("theme-project") is not None
    assert repository.get_project("provider-project") is not None


def test_project_migration_removes_stale_database_order_without_project_rows(tmp_path):
    database_path = tmp_path / "tiance.db"
    projects_root = tmp_path / "projects"
    ensure_database_schema(database_path)
    database_repository = ProjectRepository(database_path)
    database_repository.set_metadata_value(
        key="projects.order",
        value='["missing-project"]',
        updated_at=datetime.now(UTC).isoformat(),
    )
    repository = ProjectRepository(
        database_path,
        file_catalogs=tuple(
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
        ),
    )

    ProjectFileCatalogMigrationService(repository).migrate()

    assert repository.get_metadata_value("projects.order") is None
