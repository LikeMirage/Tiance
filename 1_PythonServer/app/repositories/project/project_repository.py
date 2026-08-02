# 项目数据仓库
# 对上提供统一项目目录；各项目集使用各自数据根目录下的 catalog.json。

from functools import lru_cache
from json import dumps, loads
from pathlib import Path
import sqlite3

from app.core.config import get_settings
from app.domain.project import Project, ProjectCategory, ProjectKind
from app.infra.database import database_connection, database_transaction
from app.repositories.project.file_project_catalog import FileProjectCatalog


class ProjectRepository:
    def __init__(
        self,
        database_path: Path,
        *,
        file_catalogs: tuple[FileProjectCatalog, ...] = (),
    ) -> None:
        self._database_path = database_path
        self._file_catalogs = {
            catalog.project_kind: catalog
            for catalog in file_catalogs
        }

    def list_projects(self) -> tuple[Project, ...]:
        projects = [
            item
            for item in self.list_database_projects()
            if item.project_kind not in self._file_catalogs
        ]
        for catalog in self._file_catalogs.values():
            projects.extend(catalog.list_projects())
        return tuple(sorted(projects, key=_project_sort_key))

    def list_database_projects(
        self,
        *,
        project_kind: ProjectKind | None = None,
    ) -> tuple[Project, ...]:
        """只读取 SQLite 项目记录，供旧目录迁移使用。"""
        where = "" if project_kind is None else "WHERE project_kind = ?"
        parameters = () if project_kind is None else (project_kind.value,)
        with database_connection(self._database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT
                    project_id,
                    name,
                    root_path,
                    category_id,
                    project_kind,
                    is_default,
                    sort_order,
                    created_at,
                    updated_at
                FROM projects
                {where}
                ORDER BY sort_order ASC, created_at ASC
                """,
                parameters,
            ).fetchall()
        return tuple(_project_row_to_domain(row) for row in rows)

    def get_project(self, project_id: str) -> Project | None:
        for catalog in self._file_catalogs.values():
            project = catalog.get_project(project_id)
            if project is not None:
                return project
        with database_connection(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT
                    project_id,
                    name,
                    root_path,
                    category_id,
                    project_kind,
                    is_default,
                    sort_order,
                    created_at,
                    updated_at
                FROM projects
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()
        if row is None:
            return None
        project = _project_row_to_domain(row)
        return None if project.project_kind in self._file_catalogs else project

    def get_default_project(self) -> Project | None:
        project_catalog = self._file_catalogs.get(ProjectKind.PROJECT)
        if project_catalog is not None:
            return next(
                (
                    project
                    for project in project_catalog.list_projects()
                    if project.is_default
                ),
                None,
            )
        with database_connection(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT
                    project_id,
                    name,
                    root_path,
                    category_id,
                    project_kind,
                    is_default,
                    sort_order,
                    created_at,
                    updated_at
                FROM projects
                WHERE is_default = 1
                LIMIT 1
                """
            ).fetchone()
        return None if row is None else _project_row_to_domain(row)

    def get_project_by_root_path(self, root_path: str) -> Project | None:
        for catalog in self._file_catalogs.values():
            project = catalog.get_project_by_root_path(root_path)
            if project is not None:
                return project
        with database_connection(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT
                    project_id,
                    name,
                    root_path,
                    category_id,
                    project_kind,
                    is_default,
                    sort_order,
                    created_at,
                    updated_at
                FROM projects
                WHERE root_path = ?
                """,
                (root_path,),
            ).fetchone()
        if row is None:
            return None
        project = _project_row_to_domain(row)
        return None if project.project_kind in self._file_catalogs else project

    def save_project(self, project: Project) -> Project:
        catalog = self._file_catalogs.get(project.project_kind)
        if catalog is not None:
            return catalog.save_project(project)
        with database_transaction(self._database_path) as connection:
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    name = excluded.name,
                    root_path = excluded.root_path,
                    category_id = excluded.category_id,
                    project_kind = excluded.project_kind,
                    is_default = excluded.is_default,
                    sort_order = excluded.sort_order,
                    updated_at = excluded.updated_at
                """,
                (
                    project.project_id,
                    project.name,
                    project.root_path,
                    project.category_id,
                    project.project_kind.value,
                    1 if project.is_default else 0,
                    project.sort_order,
                    project.created_at,
                    project.updated_at,
                ),
            )
        return project

    def delete_project(self, project_id: str) -> None:
        for catalog in self._file_catalogs.values():
            if catalog.get_project(project_id) is not None:
                catalog.delete_project(project_id)
                return
        with database_transaction(self._database_path) as connection:
            connection.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))

    def list_project_categories(self) -> tuple[ProjectCategory, ...]:
        categories = [
            item
            for item in self.list_database_project_categories()
            if item.category_kind not in self._file_catalogs
        ]
        for catalog in self._file_catalogs.values():
            categories.extend(catalog.list_project_categories())
        return tuple(sorted(categories, key=_category_sort_key))

    def list_database_project_categories(
        self,
        *,
        category_kind: ProjectKind | None = None,
    ) -> tuple[ProjectCategory, ...]:
        """只读取 SQLite 分类记录，供旧目录迁移使用。"""
        where = "" if category_kind is None else "WHERE category_kind = ?"
        parameters = () if category_kind is None else (category_kind.value,)
        with database_connection(self._database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT
                    category_id,
                    name,
                    category_kind,
                    is_default,
                    sort_order,
                    created_at,
                    updated_at
                FROM project_categories
                {where}
                ORDER BY sort_order ASC, created_at ASC
                """,
                parameters,
            ).fetchall()
        return tuple(_project_category_row_to_domain(row) for row in rows)

    def get_project_category(self, category_id: str) -> ProjectCategory | None:
        for catalog in self._file_catalogs.values():
            category = catalog.get_project_category(category_id)
            if category is not None:
                return category
        with database_connection(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT
                    category_id,
                    name,
                    category_kind,
                    is_default,
                    sort_order,
                    created_at,
                    updated_at
                FROM project_categories
                WHERE category_id = ?
                """,
                (category_id,),
            ).fetchone()
        if row is None:
            return None
        category = _project_category_row_to_domain(row)
        return None if category.category_kind in self._file_catalogs else category

    def get_project_category_by_name(
        self,
        name: str,
        *,
        category_kind: ProjectKind,
    ) -> ProjectCategory | None:
        catalog = self._file_catalogs.get(category_kind)
        if catalog is not None:
            return catalog.get_project_category_by_name(name)
        with database_connection(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT
                    category_id,
                    name,
                    category_kind,
                    is_default,
                    sort_order,
                    created_at,
                    updated_at
                FROM project_categories
                WHERE category_kind = ?
                  AND name = ? COLLATE NOCASE
                LIMIT 1
                """,
                (category_kind.value, name),
            ).fetchone()
        return None if row is None else _project_category_row_to_domain(row)

    def save_project_category(self, category: ProjectCategory) -> ProjectCategory:
        catalog = self._file_catalogs.get(category.category_kind)
        if catalog is not None:
            return catalog.save_project_category(category)
        with database_transaction(self._database_path) as connection:
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(category_id) DO UPDATE SET
                    name = excluded.name,
                    category_kind = excluded.category_kind,
                    is_default = excluded.is_default,
                    sort_order = excluded.sort_order,
                    updated_at = excluded.updated_at
                """,
                (
                    category.category_id,
                    category.name,
                    category.category_kind.value,
                    1 if category.is_default else 0,
                    category.sort_order,
                    category.created_at,
                    category.updated_at,
                ),
            )
        return category

    def delete_project_category(self, category_id: str) -> None:
        for catalog in self._file_catalogs.values():
            if catalog.get_project_category(category_id) is not None:
                catalog.delete_project_category(category_id)
                return
        with database_transaction(self._database_path) as connection:
            connection.execute(
                "DELETE FROM project_categories WHERE category_id = ?",
                (category_id,),
            )

    def delete_project_category_with_projects(self, category_id: str) -> None:
        for catalog in self._file_catalogs.values():
            if catalog.get_project_category(category_id) is not None:
                catalog.delete_project_category_with_projects(category_id)
                return
        with database_transaction(self._database_path) as connection:
            connection.execute(
                "DELETE FROM projects WHERE category_id = ?",
                (category_id,),
            )
            connection.execute(
                "DELETE FROM project_categories WHERE category_id = ?",
                (category_id,),
            )

    def move_projects_to_category(
        self,
        *,
        source_category_id: str,
        target_category_id: str,
        updated_at: str,
    ) -> None:
        for catalog in self._file_catalogs.values():
            if catalog.get_project_category(source_category_id) is not None:
                catalog.move_projects_to_category(
                    source_category_id=source_category_id,
                    target_category_id=target_category_id,
                    updated_at=updated_at,
                )
                return
        with database_transaction(self._database_path) as connection:
            connection.execute(
                """
                UPDATE projects
                SET category_id = ?, updated_at = ?
                WHERE category_id = ?
                """,
                (target_category_id, updated_at, source_category_id),
            )

    def next_project_category_sort_order(
        self,
        *,
        category_kind: ProjectKind | None = None,
    ) -> int:
        if category_kind in self._file_catalogs:
            return self._file_catalogs[category_kind].next_project_category_sort_order()
        where = "" if category_kind is None else "WHERE category_kind = ?"
        parameters = () if category_kind is None else (category_kind.value,)
        with database_connection(self._database_path) as connection:
            row = connection.execute(
                f"SELECT MAX(sort_order) FROM project_categories {where}",
                parameters,
            ).fetchone()
        return 0 if row is None or row[0] is None else int(row[0]) + 1

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

    def next_sort_order(
        self,
        *,
        project_kind: ProjectKind | None = None,
    ) -> int:
        if project_kind in self._file_catalogs:
            return self._file_catalogs[project_kind].next_project_sort_order()
        where = "" if project_kind is None else "WHERE project_kind = ?"
        parameters = () if project_kind is None else (project_kind.value,)
        with database_connection(self._database_path) as connection:
            row = connection.execute(
                f"SELECT MAX(sort_order) FROM projects {where}",
                parameters,
            ).fetchone()
        return 0 if row is None or row[0] is None else int(row[0]) + 1

    def save_file_project_order(self, project_ids: tuple[str, ...]) -> frozenset[str]:
        """把文件式项目的分类内顺序写回各自 catalog.json。"""
        persisted_ids: set[str] = set()
        for catalog in self._file_catalogs.values():
            persisted_ids.update(catalog.save_project_order(project_ids))
        return frozenset(persisted_ids)

    def file_project_ids(self) -> frozenset[str]:
        return frozenset(
            project.project_id
            for catalog in self._file_catalogs.values()
            for project in catalog.list_projects()
        )

    def get_file_catalog(self, project_kind: ProjectKind) -> FileProjectCatalog | None:
        return self._file_catalogs.get(project_kind)

    def purge_database_project_kind(self, project_kind: ProjectKind) -> None:
        """文件目录迁移成功后删除 SQLite 中同类型的旧目录记录。"""
        with database_transaction(self._database_path) as connection:
            project_ids = {
                str(row["project_id"])
                for row in connection.execute(
                    "SELECT project_id FROM projects WHERE project_kind = ?",
                    (project_kind.value,),
                ).fetchall()
            }
            order_row = connection.execute(
                "SELECT value FROM app_metadata WHERE key = 'projects.order'",
            ).fetchone()
            if order_row is not None:
                try:
                    order = loads(str(order_row["value"]))
                except (TypeError, ValueError):
                    order = None
                if isinstance(order, list) and all(
                    isinstance(project_id, str) for project_id in order
                ):
                    connection.execute(
                        "UPDATE app_metadata SET value = ? WHERE key = 'projects.order'",
                        (dumps([
                            project_id
                            for project_id in order
                            if project_id not in project_ids
                        ]),),
                    )
            connection.execute(
                "DELETE FROM projects WHERE project_kind = ?",
                (project_kind.value,),
            )
            connection.execute(
                "DELETE FROM project_categories WHERE category_kind = ?",
                (project_kind.value,),
            )


def _project_row_to_domain(row: sqlite3.Row) -> Project:
    return Project(
        project_id=str(row["project_id"]),
        name=str(row["name"]),
        root_path=str(row["root_path"]),
        category_id=str(row["category_id"]),
        project_kind=ProjectKind(str(row["project_kind"])),
        is_default=bool(row["is_default"]),
        sort_order=int(row["sort_order"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _project_category_row_to_domain(row: sqlite3.Row) -> ProjectCategory:
    return ProjectCategory(
        category_id=str(row["category_id"]),
        name=str(row["name"]),
        category_kind=ProjectKind(str(row["category_kind"])),
        is_default=bool(row["is_default"]),
        sort_order=int(row["sort_order"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _project_sort_key(project: Project) -> tuple[int, str, str]:
    return project.sort_order, project.created_at, project.project_id


def _category_sort_key(category: ProjectCategory) -> tuple[int, str, str]:
    return category.sort_order, category.created_at, category.category_id


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
