from functools import lru_cache
from pathlib import Path

from app.core.errors import BadRequestError, NotFoundError
from app.domain.project import ProjectKind
from app.services.application.theme_project_policy import (
    ensure_theme_project_can_be_deleted,
)
from app.services.llm.provider.catalog_mutation import (
    ProviderCatalogMutationService,
    get_provider_catalog_mutation_service,
)
from app.services.llm.provider.workspace_registry import provider_project_id
from app.services.project import ProjectService, get_project_service


class ProjectCategoryDeletionApplicationService:
    """协调分类删除与各类项目自身的删除合同。"""

    def __init__(
        self,
        project_service: ProjectService,
        provider_service: ProviderCatalogMutationService,
    ) -> None:
        self._project_service = project_service
        self._provider_service = provider_service

    def delete_category(self, category_id: str) -> None:
        category = self._project_service.get_project_category(category_id)
        if category is None:
            raise NotFoundError(f"项目分类 '{category_id}' 不存在。")
        projects = tuple(
            project
            for project in self._project_service.list_projects()
            if project.category_id == category.category_id
        )

        if category.category_kind is ProjectKind.THEME:
            for project in projects:
                ensure_theme_project_can_be_deleted(project)

        if category.category_kind is ProjectKind.PROVIDER:
            provider_ids = tuple(self._provider_id(project.project_id, project.root_path) for project in projects)
            self._provider_service.delete_providers(provider_ids)

        self._project_service.delete_project_category(category.category_id)

    @staticmethod
    def _provider_id(project_id: str, root_path: str) -> str:
        provider_id = Path(root_path).name
        if provider_project_id(provider_id) != project_id:
            raise BadRequestError("模型供应商项目登记与目录不一致，已停止删除。")
        return provider_id


@lru_cache
def get_project_category_deletion_application_service(
) -> ProjectCategoryDeletionApplicationService:
    return ProjectCategoryDeletionApplicationService(
        get_project_service(),
        get_provider_catalog_mutation_service(),
    )
