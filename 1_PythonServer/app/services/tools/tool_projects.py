from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.domain.project import Project, ProjectCategory, ProjectKind
from app.domain.tools import ToolFolder, Toolset
from app.services.project.project_files import ProjectFileService, get_project_file_service
from app.services.project.projects import ProjectService, get_project_service


class ToolProjectService:
    """把工具专用视图建立在原生项目与项目分类之上。"""

    def __init__(
        self,
        project_service: ProjectService,
        project_file_service: ProjectFileService,
        tools_root: Path,
    ) -> None:
        self._project_service = project_service
        self._project_file_service = project_file_service
        self._tools_root = tools_root

    def ensure_default_category(self) -> None:
        self._project_service.ensure_default_tool_project_category()

    def list_toolsets(self) -> tuple[Toolset, ...]:
        return tuple(
            self._to_toolset(category)
            for category in self._project_service.list_project_categories()
            if category.category_kind is ProjectKind.TOOL
        )

    def create_toolset(self, *, name: str | None = None) -> Toolset:
        category = self._project_service.create_project_category(
            name=name,
            category_kind=ProjectKind.TOOL,
        )
        return self._to_toolset(category)

    def rename_toolset(self, category_id: str, *, name: str) -> Toolset:
        category = self._project_service.rename_project_category(category_id, name=name)
        self._require_tool_category(category)
        return self._to_toolset(category)

    def delete_toolset(self, category_id: str) -> None:
        self._require_tool_category_id(category_id)
        self._project_service.delete_project_category(category_id)

    def list_tool_folders(self, category_id: str) -> tuple[ToolFolder, ...]:
        self._require_tool_category_id(category_id)
        return tuple(
            self._to_tool_folder(project)
            for project in self._project_service.list_projects()
            if project.project_kind is ProjectKind.TOOL
            and project.category_id == category_id
        )

    def create_tool_folder(self, category_id: str, *, name: str | None = None) -> ToolFolder:
        from app.services.application.project_creation import (
            get_project_creation_application_service,
        )

        self._require_tool_category_id(category_id)
        project = get_project_creation_application_service().create_project(
            name=name,
            category_id=category_id,
            project_kind=ProjectKind.TOOL,
        )
        return self._to_tool_folder(project)

    def rename_tool_folder(
        self,
        category_id: str,
        project_id: str,
        *,
        name: str,
    ) -> ToolFolder:
        project = self.require_tool_project(category_id, project_id)
        updated = self._project_service.rename_project(project.project_id, name=name)
        return self._to_tool_folder(updated)

    def delete_tool_folder(self, category_id: str, project_id: str) -> None:
        project = self.require_tool_project(category_id, project_id)
        self._project_service.delete_project(project.project_id)

    def move_tool_folder(
        self,
        category_id: str,
        project_id: str,
        *,
        target_category_id: str,
    ) -> ToolFolder:
        project = self.require_tool_project(category_id, project_id)
        self._require_tool_category_id(target_category_id)
        updated = self._project_service.move_project_to_category(
            project.project_id,
            category_id=target_category_id,
        )
        return self._to_tool_folder(updated)

    def reveal_tool_folder(self, category_id: str, project_id: str) -> None:
        project = self.require_tool_project(category_id, project_id)
        self._project_file_service.reveal_entry(project.project_id, "")

    def require_tool_project(self, category_id: str, project_id: str) -> Project:
        self._require_tool_category_id(category_id)
        normalized_project_id = project_id.strip()
        project = self._project_service.get_project(normalized_project_id)
        if (
            project is None
            or project.project_kind is not ProjectKind.TOOL
            or project.category_id != category_id
        ):
            raise NotFoundError(f"工具项目 '{normalized_project_id}' 不存在。")
        return project

    def get_tool_project(self, project_id: str) -> Project | None:
        project = self._project_service.get_project(project_id.strip())
        return project if project is not None and project.project_kind is ProjectKind.TOOL else None

    def folder_for_project(self, project: Project) -> ToolFolder:
        if project.project_kind is not ProjectKind.TOOL:
            raise NotFoundError("工具项目不存在。")
        return self._to_tool_folder(project)

    def _require_tool_category_id(self, category_id: str) -> ProjectCategory:
        category = next(
            (
                item
                for item in self._project_service.list_project_categories()
                if item.category_id == category_id
            ),
            None,
        )
        if category is None:
            raise NotFoundError(f"工具分类 '{category_id}' 不存在。")
        self._require_tool_category(category)
        return category

    @staticmethod
    def _require_tool_category(category: ProjectCategory) -> None:
        if category.category_kind is not ProjectKind.TOOL:
            raise NotFoundError("工具分类不存在。")

    def _to_toolset(self, category: ProjectCategory) -> Toolset:
        return Toolset(
            category_id=category.category_id,
            name=category.name,
            scope="local",
            root_path=str(self._tools_root),
            readonly=False,
            created_at=category.created_at,
            updated_at=category.updated_at,
        )

    def _to_tool_folder(self, project: Project) -> ToolFolder:
        return ToolFolder(
            project_id=project.project_id,
            category_id=project.category_id,
            name=project.name,
            root_path=project.root_path,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )

@lru_cache
def get_tool_project_service() -> ToolProjectService:
    return ToolProjectService(
        get_project_service(),
        get_project_file_service(),
        get_settings().tools_data_path,
    )
