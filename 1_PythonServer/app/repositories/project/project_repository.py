"""Project catalogs live in collection catalog.json files; global metadata uses SQLite."""
from functools import lru_cache
from pathlib import Path
from app.core.config import get_settings
from app.domain.project import Project, ProjectCategory, ProjectKind
from app.infra.database import database_connection, database_transaction
from app.repositories.project.file_project_catalog import FileProjectCatalog

COLLECTION_DIRECTORIES = {
    ProjectKind.PROJECT: "projects", ProjectKind.TOOL: "tools",
    ProjectKind.KNOWLEDGE: "knowledge", ProjectKind.EXPERIENCE: "experience",
    ProjectKind.ROLE: "roles", ProjectKind.THEME: "themes", ProjectKind.PROVIDER: "providers",
}

class ProjectRepository:
    def __init__(self, database_path: Path, *, file_catalogs: tuple[FileProjectCatalog, ...] | None = None) -> None:
        self._database_path = database_path
        if file_catalogs is None:
            file_catalogs = tuple(FileProjectCatalog(database_path.parent / name,
                project_kind=kind, allow_external_roots=kind is ProjectKind.PROJECT)
                for kind, name in COLLECTION_DIRECTORIES.items())
        self._file_catalogs = {catalog.project_kind: catalog for catalog in file_catalogs}

    def _require_catalog(self, kind: ProjectKind) -> FileProjectCatalog:
        catalog = self._file_catalogs.get(kind)
        if catalog is None:
            raise RuntimeError(f"未配置 {kind.value} 文件项目仓库。")
        return catalog

    def list_projects(self) -> tuple[Project, ...]:
        return tuple(sorted((item for catalog in self._file_catalogs.values()
            for item in catalog.list_projects()), key=lambda p: (p.sort_order,p.created_at,p.project_id)))

    def get_project(self, project_id: str) -> Project | None:
        for catalog in self._file_catalogs.values():
            if (project := catalog.get_project(project_id)) is not None:
                return project
        return None

    def get_default_project(self) -> Project | None:
        return next((p for p in self._require_catalog(ProjectKind.PROJECT).list_projects() if p.is_default), None)

    def get_project_by_root_path(self, root_path: str) -> Project | None:
        for catalog in self._file_catalogs.values():
            if (project := catalog.get_project_by_root_path(root_path)) is not None:
                return project
        return None

    def save_project(self, project: Project) -> Project:
        return self._require_catalog(project.project_kind).save_project(project)

    def delete_project(self, project_id: str) -> None:
        for catalog in self._file_catalogs.values():
            if catalog.get_project(project_id) is not None:
                catalog.delete_project(project_id)
                return

    def list_project_categories(self) -> tuple[ProjectCategory, ...]:
        return tuple(sorted((item for catalog in self._file_catalogs.values()
            for item in catalog.list_project_categories()), key=lambda c: (c.sort_order,c.created_at,c.category_id)))

    def get_project_category(self, category_id: str) -> ProjectCategory | None:
        for catalog in self._file_catalogs.values():
            if (category := catalog.get_project_category(category_id)) is not None:
                return category
        return None

    def get_project_category_by_name(self, name: str, *, category_kind: ProjectKind) -> ProjectCategory | None:
        return self._require_catalog(category_kind).get_project_category_by_name(name)

    def save_project_category(self, category: ProjectCategory) -> ProjectCategory:
        return self._require_catalog(category.category_kind).save_project_category(category)

    def delete_project_category(self, category_id: str) -> None:
        for catalog in self._file_catalogs.values():
            if catalog.get_project_category(category_id) is not None:
                catalog.delete_project_category(category_id)
                return

    def delete_project_category_with_projects(self, category_id: str) -> None:
        for catalog in self._file_catalogs.values():
            if catalog.get_project_category(category_id) is not None:
                catalog.delete_project_category_with_projects(category_id)
                return

    def move_projects_to_category(self, *, source_category_id: str, target_category_id: str, updated_at: str) -> None:
        for catalog in self._file_catalogs.values():
            if catalog.get_project_category(source_category_id) is not None:
                catalog.move_projects_to_category(source_category_id=source_category_id,
                    target_category_id=target_category_id, updated_at=updated_at)
                return
        raise ValueError("源项目分类不存在。")

    def next_project_category_sort_order(self, *, category_kind: ProjectKind | None = None) -> int:
        if category_kind is not None:
            return self._require_catalog(category_kind).next_project_category_sort_order()
        return max((c.sort_order for c in self.list_project_categories()), default=-1) + 1

    def next_sort_order(self, *, project_kind: ProjectKind | None = None) -> int:
        if project_kind is not None:
            return self._require_catalog(project_kind).next_project_sort_order()
        return max((p.sort_order for p in self.list_projects()), default=-1) + 1

    def get_metadata_value(self, key: str) -> str | None:
        with database_connection(self._database_path) as connection:
            row = connection.execute(
                "SELECT value FROM app_metadata WHERE key = ?",
                (key,),
            ).fetchone()
        return None if row is None else str(row["value"])

    def set_metadata_value(self, *, key: str, value: str, updated_at: str) -> None:
        with database_transaction(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO app_metadata (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, updated_at),
            )

    def delete_metadata_value(self, key: str) -> None:
        with database_transaction(self._database_path) as connection:
            connection.execute("DELETE FROM app_metadata WHERE key = ?", (key,))

    def get_catalog_metadata_value(
        self,
        project_kind: ProjectKind,
        key: str,
    ) -> str | None:
        catalog = self._file_catalogs.get(project_kind)
        return None if catalog is None else catalog.get_metadata_value(key)

    def set_catalog_metadata_value(
        self,
        project_kind: ProjectKind,
        *,
        key: str,
        value: str,
    ) -> None:
        catalog = self._file_catalogs.get(project_kind)
        if catalog is None:
            raise RuntimeError(f"未配置 {project_kind.value} 文件项目仓库。")
        catalog.set_metadata_value(key=key, value=value)

    def save_file_project_order(self, project_ids: tuple[str, ...]) -> frozenset[str]:
        """把文件式项目的分类内顺序写回各自 catalog.json。"""
        persisted_ids: set[str] = set()
        for catalog in self._file_catalogs.values():
            persisted_ids.update(catalog.save_project_order(project_ids))
        return frozenset(persisted_ids)


    def get_file_catalog(self, project_kind: ProjectKind) -> FileProjectCatalog | None:
        return self._file_catalogs.get(project_kind)


@lru_cache
def get_project_repository() -> ProjectRepository:
    settings = get_settings()
    return ProjectRepository(
        settings.app_database_file,
        file_catalogs=(
            FileProjectCatalog(
                settings.projects_data_path,
                project_kind=ProjectKind.PROJECT,
                allow_external_roots=True,
            ),
            FileProjectCatalog(
                settings.tools_data_path,
                project_kind=ProjectKind.TOOL,
            ),
            FileProjectCatalog(
                settings.knowledge_data_path,
                project_kind=ProjectKind.KNOWLEDGE,
            ),
            FileProjectCatalog(
                settings.experience_data_path,
                project_kind=ProjectKind.EXPERIENCE,
            ),
            FileProjectCatalog(
                settings.roles_data_path,
                project_kind=ProjectKind.ROLE,
            ),
            FileProjectCatalog(
                settings.themes_data_path,
                project_kind=ProjectKind.THEME,
            ),
            FileProjectCatalog(
                settings.providers_data_path,
                project_kind=ProjectKind.PROVIDER,
            ),
        ),
    )
