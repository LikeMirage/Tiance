import sqlite3
from pathlib import Path

import pytest

from app.core.errors import BadRequestError, ConflictError
from app.domain.project import ProjectKind
from app.infra.database import (
    database_transaction,
    ensure_database_schema,
    run_database_migrations,
)
from app.infra.database.schema import MIGRATIONS
from app.infra.projects import ProjectStorage
from app.repositories.project import ProjectRepository
from app.schemas.project.projects import ProjectResponse
from app.services.project.projects import (
    DEFAULT_EXPERIENCE_PROJECT_CATEGORY_ID,
    DEFAULT_EXPERIENCE_PROJECT_CATEGORY_NAME,
    DEFAULT_KNOWLEDGE_PROJECT_CATEGORY_ID,
    DEFAULT_KNOWLEDGE_PROJECT_CATEGORY_NAME,
    DEFAULT_ROLE_PROJECT_CATEGORY_ID,
    DEFAULT_ROLE_PROJECT_CATEGORY_NAME,
    DEFAULT_THEME_PROJECT_CATEGORY_ID,
    DEFAULT_THEME_PROJECT_CATEGORY_NAME,
    DEFAULT_TOOL_PROJECT_CATEGORY_ID,
    DEFAULT_TOOL_PROJECT_CATEGORY_NAME,
    DEFAULT_PROVIDER_PROJECT_CATEGORY_ID,
    DEFAULT_PROVIDER_PROJECT_CATEGORY_NAME,
    DEFAULT_PROJECT_CATEGORY_ID,
    DEFAULT_PROJECT_CATEGORY_NAME,
    ProjectService,
)


class RaceProjectRepository(ProjectRepository):
    def __init__(self, database_path):
        super().__init__(database_path)
        self.miss_next_root_path_lookup = False

    def get_project_by_root_path(self, root_path: str):
        if self.miss_next_root_path_lookup:
            self.miss_next_root_path_lookup = False
            return None
        return super().get_project_by_root_path(root_path)


def test_project_categories_bootstrap_default_category(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    service = ProjectService(
        ProjectRepository(database_path),
        ProjectStorage(tmp_path / "managed-projects"),
    )

    categories = service.list_project_categories()

    assert len(categories) == 7
    project_category = next(
        category
        for category in categories
        if category.category_kind is ProjectKind.PROJECT
    )
    role_category = next(
        category
        for category in categories
        if category.category_kind is ProjectKind.ROLE
    )
    theme_category = next(
        category
        for category in categories
        if category.category_kind is ProjectKind.THEME
    )
    knowledge_category = next(
        category
        for category in categories
        if category.category_kind is ProjectKind.KNOWLEDGE
    )
    experience_category = next(
        category
        for category in categories
        if category.category_kind is ProjectKind.EXPERIENCE
    )
    tool_category = next(
        category
        for category in categories
        if category.category_kind is ProjectKind.TOOL
    )
    provider_category = next(
        category
        for category in categories
        if category.category_kind is ProjectKind.PROVIDER
    )
    assert project_category.category_id == DEFAULT_PROJECT_CATEGORY_ID
    assert project_category.name == DEFAULT_PROJECT_CATEGORY_NAME
    assert project_category.is_default is True
    assert knowledge_category.category_id == DEFAULT_KNOWLEDGE_PROJECT_CATEGORY_ID
    assert knowledge_category.name == DEFAULT_KNOWLEDGE_PROJECT_CATEGORY_NAME
    assert knowledge_category.is_default is True
    assert experience_category.category_id == DEFAULT_EXPERIENCE_PROJECT_CATEGORY_ID
    assert experience_category.name == DEFAULT_EXPERIENCE_PROJECT_CATEGORY_NAME
    assert experience_category.is_default is True
    assert role_category.category_id == DEFAULT_ROLE_PROJECT_CATEGORY_ID
    assert role_category.name == DEFAULT_ROLE_PROJECT_CATEGORY_NAME
    assert role_category.is_default is True
    assert theme_category.category_id == DEFAULT_THEME_PROJECT_CATEGORY_ID
    assert theme_category.name == DEFAULT_THEME_PROJECT_CATEGORY_NAME
    assert theme_category.is_default is True
    assert tool_category.category_id == DEFAULT_TOOL_PROJECT_CATEGORY_ID
    assert tool_category.name == DEFAULT_TOOL_PROJECT_CATEGORY_NAME
    assert tool_category.is_default is True
    assert provider_category.category_id == DEFAULT_PROVIDER_PROJECT_CATEGORY_ID
    assert provider_category.name == DEFAULT_PROVIDER_PROJECT_CATEGORY_NAME
    assert provider_category.is_default is True


def test_tool_category_bootstrap_keeps_existing_categories_without_uncategorized(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    service = ProjectService(
        ProjectRepository(database_path),
        ProjectStorage(tmp_path / "managed-projects"),
    )
    existing = service.create_project_category(
        name="基础工具",
        category_kind=ProjectKind.TOOL,
    )

    categories = service.list_project_categories()
    tool_categories = tuple(
        category
        for category in categories
        if category.category_kind is ProjectKind.TOOL
    )

    assert tool_categories == (existing,)


def test_knowledge_and_experience_projects_use_independent_categories_and_roots(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    knowledge_root = tmp_path / "knowledge"
    experience_root = tmp_path / "experience"
    service = ProjectService(
        ProjectRepository(database_path),
        ProjectStorage(
            tmp_path / "managed-projects",
            knowledge_root=knowledge_root,
            experience_root=experience_root,
        ),
    )
    knowledge_category = service.create_project_category(
        name="论文",
        category_kind=ProjectKind.KNOWLEDGE,
    )
    experience_category = service.create_project_category(
        name="实践",
        category_kind=ProjectKind.EXPERIENCE,
    )

    knowledge_project = service.create_project(
        name="知识项目",
        category_id=knowledge_category.category_id,
        project_kind=ProjectKind.KNOWLEDGE,
    )
    experience_project = service.create_project(
        name="经验项目",
        category_id=experience_category.category_id,
        project_kind=ProjectKind.EXPERIENCE,
    )

    assert knowledge_project.project_kind is ProjectKind.KNOWLEDGE
    assert experience_project.project_kind is ProjectKind.EXPERIENCE
    assert ProjectResponse.from_domain(knowledge_project).project_kind is ProjectKind.KNOWLEDGE
    assert knowledge_project.root_path == str(knowledge_root / knowledge_project.project_id)
    assert experience_project.root_path == str(experience_root / experience_project.project_id)
    with pytest.raises(BadRequestError):
        service.create_project(
            name="错误归类",
            category_id=experience_category.category_id,
            project_kind=ProjectKind.KNOWLEDGE,
        )


def test_project_create_uses_selected_category(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    service = ProjectService(
        ProjectRepository(database_path),
        ProjectStorage(tmp_path / "managed-projects"),
    )
    category = service.create_project_category(name="客户项目")

    project = service.create_project(name="客户 A", category_id=category.category_id)

    assert project.category_id == category.category_id
    assert project.project_kind is ProjectKind.PROJECT
    response = ProjectResponse.from_domain(project)
    assert response.model_dump(mode="json")["project_kind"] == "project"


def test_project_kind_migration_backfills_existing_projects(tmp_path):
    database_path = tmp_path / "tiance.db"
    run_database_migrations(
        database_path,
        tuple(migration for migration in MIGRATIONS if migration.version <= 29),
    )
    with database_transaction(database_path) as connection:
        connection.execute(
            """
            INSERT INTO projects (
                project_id,
                name,
                root_path,
                category_id,
                is_default,
                sort_order,
                created_at,
                updated_at
            ) VALUES (
                'legacy-project',
                '旧项目',
                'C:/legacy-project',
                'daily-project',
                0,
                0,
                'created',
                'updated'
            )
            """
        )

    ensure_database_schema(database_path)

    repository = ProjectRepository(database_path)
    migrated_project = repository.get_project("legacy-project")
    assert migrated_project is not None
    assert migrated_project.project_kind is ProjectKind.PROJECT

    role_category = repository.get_project_category(
        DEFAULT_ROLE_PROJECT_CATEGORY_ID,
    )
    assert role_category is not None
    assert role_category.category_kind is ProjectKind.ROLE


def test_role_category_migration_replaces_fixed_role_set(tmp_path):
    database_path = tmp_path / "tiance.db"
    run_database_migrations(
        database_path,
        tuple(migration for migration in MIGRATIONS if migration.version <= 34),
    )
    with database_transaction(database_path) as connection:
        connection.execute(
            """
            INSERT INTO project_categories (
                category_id,
                name,
                category_kind,
                is_default,
                sort_order,
                created_at,
                updated_at
            ) VALUES (
                'role-set',
                '角色集',
                'role',
                0,
                1,
                'created',
                'updated'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO projects (
                project_id,
                name,
                root_path,
                category_id,
                project_kind,
                is_default,
                sort_order,
                created_at,
                updated_at
            ) VALUES (
                'legacy-role',
                '旧角色',
                'C:/legacy-role',
                'role-set',
                'role',
                0,
                0,
                'created',
                'updated'
            )
            """
        )

    ensure_database_schema(database_path)

    repository = ProjectRepository(database_path)
    assert repository.get_project_category("role-set") is None
    default_role_category = repository.get_project_category(
        DEFAULT_ROLE_PROJECT_CATEGORY_ID,
    )
    assert default_role_category is not None
    assert default_role_category.is_default is True
    migrated_role = repository.get_project("legacy-role")
    assert migrated_role is not None
    assert migrated_role.category_id == DEFAULT_ROLE_PROJECT_CATEGORY_ID

    with pytest.raises(sqlite3.IntegrityError, match="legacy_role_category_removed"):
        with database_transaction(database_path) as connection:
            connection.execute(
                """
                INSERT INTO project_categories (
                    category_id,
                    name,
                    category_kind,
                    is_default,
                    sort_order,
                    created_at,
                    updated_at
                ) VALUES (
                    'role-set',
                    '角色集',
                    'role',
                    0,
                    1,
                    'created',
                    'updated'
                )
                """
            )


def test_role_project_uses_selected_category_and_roles_directory(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    projects_root = tmp_path / "managed-projects"
    roles_root = tmp_path / "roles"
    repository = ProjectRepository(database_path)
    service = ProjectService(
        repository,
        ProjectStorage(projects_root, roles_root),
    )

    role_category = service.create_project_category(
        name="文案角色",
        category_kind=ProjectKind.ROLE,
    )
    role_project = service.create_role_project(
        name=None,
        category_id=role_category.category_id,
    )

    assert role_project.name == "新建角色"
    assert role_project.category_id == role_category.category_id
    assert role_project.project_kind is ProjectKind.ROLE
    assert role_project.root_path == str(roles_root / role_project.project_id)
    assert service.is_managed_project(role_project) is True

    with pytest.raises(BadRequestError):
        service.create_project(name="错误项目", category_id=role_category.category_id)
    with pytest.raises(BadRequestError):
        service.create_role_project(
            name="错误角色",
            category_id=DEFAULT_PROJECT_CATEGORY_ID,
        )

    renamed_category = service.rename_project_category(
        role_category.category_id,
        name="内容创作",
    )
    assert renamed_category.name == "内容创作"

    service.delete_project_category(role_category.category_id)
    assert repository.get_project(role_project.project_id) is None
    assert repository.get_project_category(role_category.category_id) is None
    assert not Path(role_project.root_path).exists()

    service.list_project_categories()
    service.delete_project_category(DEFAULT_ROLE_PROJECT_CATEGORY_ID)
    assert repository.get_project_category(DEFAULT_ROLE_PROJECT_CATEGORY_ID) is None
    assert all(
        category.category_id != DEFAULT_ROLE_PROJECT_CATEGORY_ID
        for category in service.list_project_categories()
    )


def test_delete_theme_category_archives_theme_folder_and_index(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    projects_root = tmp_path / "managed-projects"
    roles_root = tmp_path / "roles"
    themes_root = tmp_path / "themes"
    theme_root = themes_root / "autumn"
    theme_root.mkdir(parents=True)
    repository = ProjectRepository(database_path)
    service = ProjectService(
        repository,
        ProjectStorage(projects_root, roles_root, themes_root),
    )
    category = service.create_project_category(
        name="季节主题",
        category_kind=ProjectKind.THEME,
    )
    theme_project = service.create_project(
        name="秋色",
        root_path=str(theme_root),
        category_id=category.category_id,
        project_kind=ProjectKind.THEME,
    )

    assert theme_project.category_id == category.category_id
    assert theme_project.project_kind is ProjectKind.THEME
    assert theme_project.root_path == str(theme_root.resolve())
    assert theme_root.is_dir()

    service.delete_project_category(category.category_id)
    assert repository.get_project(theme_project.project_id) is None
    assert repository.get_project_category(category.category_id) is None
    assert not theme_root.exists()


def test_delete_project_category_archives_projects_and_removes_index(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    repository = ProjectRepository(database_path)
    service = ProjectService(
        repository,
        ProjectStorage(tmp_path / "managed-projects"),
    )
    category = service.create_project_category(name="客户项目")
    project = service.create_project(name="客户 A", category_id=category.category_id)

    service.delete_project_category(category.category_id)

    assert repository.get_project(project.project_id) is None
    assert repository.get_project_category(category.category_id) is None
    assert not Path(project.root_path).exists()


def test_delete_project_category_archives_external_project_folder(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    repository = ProjectRepository(database_path)
    service = ProjectService(
        repository,
        ProjectStorage(tmp_path / "managed-projects"),
    )
    category = service.create_project_category(name="外部项目")
    external_root = tmp_path / "external-project"
    external_root.mkdir()
    project = service.create_project(
        name="外部项目",
        root_path=str(external_root),
        category_id=category.category_id,
    )

    service.delete_project_category(category.category_id)

    assert repository.get_project(project.project_id) is None
    assert repository.get_project_category(category.category_id) is None
    assert not external_root.exists()


def test_duplicate_import_reports_existing_project_category(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    service = ProjectService(
        ProjectRepository(database_path),
        ProjectStorage(tmp_path / "managed-projects"),
    )
    category = service.create_project_category(name="客户项目")
    external_root = tmp_path / "external-project"
    external_root.mkdir()
    created = service.create_project(
        name="外部项目",
        root_path=str(external_root),
        category_id=category.category_id,
    )

    with pytest.raises(ConflictError) as exc_info:
        service.create_project(
            name=None,
            root_path=str(external_root),
            category_id=DEFAULT_PROJECT_CATEGORY_ID,
        )

    assert exc_info.value.details == {
        "kind": "project_already_imported",
        "project_id": created.project_id,
        "project_name": "外部项目",
        "root_path": created.root_path,
        "category_id": category.category_id,
        "category_name": "客户项目",
    }


def test_duplicate_import_race_reports_existing_project_category(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    repository = RaceProjectRepository(database_path)
    service = ProjectService(
        repository,
        ProjectStorage(tmp_path / "managed-projects"),
    )
    category = service.create_project_category(name="客户项目")
    external_root = tmp_path / "external-project"
    external_root.mkdir()
    created = service.create_project(
        name="外部项目",
        root_path=str(external_root),
        category_id=category.category_id,
    )

    repository.miss_next_root_path_lookup = True
    with pytest.raises(ConflictError) as exc_info:
        service.create_project(
            name=None,
            root_path=str(external_root),
            category_id=DEFAULT_PROJECT_CATEGORY_ID,
        )

    assert exc_info.value.details["kind"] == "project_already_imported"
    assert exc_info.value.details["project_id"] == created.project_id
    assert exc_info.value.details["category_id"] == category.category_id


def test_import_rejects_external_symlink(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    service = ProjectService(
        ProjectRepository(database_path),
        ProjectStorage(tmp_path / "managed-projects"),
    )
    external_root = tmp_path / "external-project"
    external_root.mkdir()
    symlink_root = tmp_path / "external-link"
    try:
        symlink_root.symlink_to(external_root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"当前系统不允许创建目录符号链接：{exc}")

    with pytest.raises(BadRequestError):
        service.create_project(name="外部链接", root_path=str(symlink_root))

    assert external_root.is_dir()


def test_imported_project_remove_keeps_external_files(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    repository = ProjectRepository(database_path)
    service = ProjectService(
        repository,
        ProjectStorage(tmp_path / "managed-projects"),
    )
    external_root = tmp_path / "external-project"
    external_root.mkdir()
    (external_root / "note.txt").write_text("keep", encoding="utf-8")
    project = service.create_project(name="外部项目", root_path=str(external_root))

    service.delete_project(project.project_id)

    assert repository.get_project(project.project_id) is None
    assert external_root.is_dir()
    assert (external_root / "note.txt").read_text(encoding="utf-8") == "keep"


def test_imported_project_delete_files_moves_external_folder_from_original_path(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    repository = ProjectRepository(database_path)
    service = ProjectService(
        repository,
        ProjectStorage(tmp_path / "managed-projects"),
    )
    external_root = tmp_path / "external-project"
    external_root.mkdir()
    (external_root / "note.txt").write_text("delete", encoding="utf-8")
    project = service.create_project(name="外部项目", root_path=str(external_root))

    service.delete_project(project.project_id, delete_files=True)

    assert repository.get_project(project.project_id) is None
    assert not external_root.exists()


def test_restore_external_archived_project_root_requires_existing_parent(tmp_path):
    storage_root = tmp_path / "managed-projects"
    storage = ProjectStorage(storage_root)
    archived_root = storage_root / ".trash" / "external" / "external-project-archive"
    archived_root.mkdir(parents=True)

    with pytest.raises(ValueError):
        storage.restore_external_archived_project_root(
            archived_root,
            str(tmp_path / "missing-parent" / "external-project"),
        )

    assert archived_root.is_dir()
