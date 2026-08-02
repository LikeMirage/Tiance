from functools import lru_cache
from json import loads

from app.domain.project import Project, ProjectKind
from app.repositories.project import ProjectRepository, get_project_repository


FILE_CATALOG_PROJECT_KINDS = (
    ProjectKind.PROJECT,
    ProjectKind.KNOWLEDGE,
    ProjectKind.EXPERIENCE,
    ProjectKind.ROLE,
    ProjectKind.THEME,
    ProjectKind.PROVIDER,
)

_PROJECT_ORDER_KEY = "projects.order"
_DEFAULT_PROJECT_BOOTSTRAPPED_KEY = "projects.default_project_bootstrapped"


class ProjectFileCatalogMigrationService:
    """把独立数据项目集从 SQLite 迁移到各自 catalog.json。"""

    def __init__(self, repository: ProjectRepository) -> None:
        self._repository = repository

    def migrate(self) -> None:
        for project_kind in FILE_CATALOG_PROJECT_KINDS:
            self._migrate_project_kind(project_kind)

    def _migrate_project_kind(self, project_kind: ProjectKind) -> None:
        categories = self._repository.list_database_project_categories(
            category_kind=project_kind,
        )
        projects = self._repository.list_database_projects(
            project_kind=project_kind,
        )
        if not categories and not projects:
            if project_kind is ProjectKind.PROJECT:
                catalog = self._repository.get_file_catalog(project_kind)
                if catalog is None:
                    raise RuntimeError("未配置 project 文件项目仓库。")
                if self._repository.get_metadata_value(
                    _DEFAULT_PROJECT_BOOTSTRAPPED_KEY
                ) == "1":
                    catalog.set_metadata_value(
                        key=_DEFAULT_PROJECT_BOOTSTRAPPED_KEY,
                        value="1",
                    )
                self._repository.delete_metadata_value(_PROJECT_ORDER_KEY)
                self._repository.delete_metadata_value(
                    _DEFAULT_PROJECT_BOOTSTRAPPED_KEY
                )
            return
        catalog = self._repository.get_file_catalog(project_kind)
        if catalog is None:
            raise RuntimeError(f"未配置 {project_kind.value} 文件项目仓库。")
        if projects and not categories:
            raise RuntimeError(
                f"{project_kind.value} 项目存在，但没有可迁移的分类记录。"
            )

        project_order = self._database_project_order(projects)
        default_project_bootstrapped = (
            project_kind is ProjectKind.PROJECT
            and (
                bool(projects)
                or self._repository.get_metadata_value(
                    _DEFAULT_PROJECT_BOOTSTRAPPED_KEY
                ) == "1"
            )
        )

        for category in categories:
            catalog.save_project_category(category)
        catalog.save_category_order(tuple(category.category_id for category in categories))
        for project in projects:
            catalog.save_project(project)
        catalog.save_project_order(project_order)
        if default_project_bootstrapped:
            catalog.set_metadata_value(
                key=_DEFAULT_PROJECT_BOOTSTRAPPED_KEY,
                value="1",
            )

        self._verify_migration(
            project_kind=project_kind,
            category_ids={category.category_id for category in categories},
            project_ids={project.project_id for project in projects},
        )
        self._repository.purge_database_project_kind(project_kind)
        if project_kind is ProjectKind.PROJECT:
            self._repository.delete_metadata_value(_PROJECT_ORDER_KEY)
            self._repository.delete_metadata_value(_DEFAULT_PROJECT_BOOTSTRAPPED_KEY)

    def _database_project_order(
        self,
        projects: tuple[Project, ...],
    ) -> tuple[str, ...]:
        project_ids = {project.project_id for project in projects}
        ordered_ids: list[str] = []
        raw_order = self._repository.get_metadata_value(_PROJECT_ORDER_KEY)
        if raw_order:
            try:
                stored_order = loads(raw_order)
            except (TypeError, ValueError):
                stored_order = None
            if isinstance(stored_order, list):
                ordered_ids.extend(
                    project_id
                    for project_id in stored_order
                    if isinstance(project_id, str) and project_id in project_ids
                )
        ordered_set = set(ordered_ids)
        ordered_ids.extend(
            project.project_id
            for project in projects
            if project.project_id not in ordered_set
        )
        return tuple(ordered_ids)

    def _verify_migration(
        self,
        *,
        project_kind: ProjectKind,
        category_ids: set[str],
        project_ids: set[str],
    ) -> None:
        catalog = self._repository.get_file_catalog(project_kind)
        if catalog is None:
            raise RuntimeError(f"未配置 {project_kind.value} 文件项目仓库。")
        migrated_category_ids = {
            category.category_id
            for category in catalog.list_project_categories()
        }
        migrated_project_ids = {
            project.project_id
            for project in catalog.list_projects()
        }
        if not category_ids.issubset(migrated_category_ids):
            raise RuntimeError(f"{project_kind.value} 分类迁移校验失败。")
        if not project_ids.issubset(migrated_project_ids):
            raise RuntimeError(f"{project_kind.value} 项目迁移校验失败。")


@lru_cache
def get_project_file_catalog_migration_service() -> ProjectFileCatalogMigrationService:
    return ProjectFileCatalogMigrationService(get_project_repository())
