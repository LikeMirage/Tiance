from datetime import UTC, datetime
from functools import lru_cache
from uuid import NAMESPACE_URL, uuid5

from app.domain.project import Project, ProjectKind
from app.core.errors import BadRequestError
from app.infra.projects import ProjectStorage, get_project_storage
from app.repositories.llm.provider_catalog_repository import (
    ProviderCatalogRepository,
    get_provider_catalog_repository,
)
from app.repositories.llm.provider_file_store import (
    PROVIDER_MANIFEST_FILE,
    ProviderFileStore,
    get_provider_file_store,
)
from app.repositories.project import ProjectRepository, get_project_repository
from app.services.project import ProjectService, get_project_service


class ProviderWorkspaceRegistryService:
    """把供应商目录登记为可复用通用文件工作区的项目。"""

    def __init__(
        self,
        catalog_repository: ProviderCatalogRepository,
        file_store: ProviderFileStore,
        project_repository: ProjectRepository,
        project_service: ProjectService,
        project_storage: ProjectStorage,
    ) -> None:
        self._catalog_repository = catalog_repository
        self._file_store = file_store
        self._project_repository = project_repository
        self._project_service = project_service
        self._project_storage = project_storage

    def synchronize(self) -> None:
        provider_categories = tuple(
            category
            for category in self._project_service.list_project_categories()
            if category.category_kind is ProjectKind.PROVIDER
        )
        if provider_categories:
            fallback_category = provider_categories[0]
        else:
            fallback_category = self._project_service.create_project_category(
                name=None,
                category_kind=ProjectKind.PROVIDER,
            )
            provider_categories = (fallback_category,)
        category_ids = {category.category_id for category in provider_categories}
        existing_projects = {
            project.project_id: project
            for project in self._project_repository.list_projects()
            if project.project_kind is ProjectKind.PROVIDER
        }
        live_project_ids: set[str] = set()

        for sort_order, provider_id in enumerate(
            self._catalog_repository.list_ordered_provider_ids()
        ):
            entry = self._catalog_repository.get_entry(provider_id)
            if entry is None:
                continue
            project_id = provider_project_id(provider_id)
            live_project_ids.add(project_id)
            existing = existing_projects.get(project_id)
            manifest = self._file_store.read_provider_file(
                provider_id,
                PROVIDER_MANIFEST_FILE,
            ) or {}
            now = _utc_now()
            created_at = _manifest_timestamp(manifest, "createdAt") or now
            updated_at = _manifest_timestamp(manifest, "updatedAt") or created_at
            root_path = self._project_storage.resolve_managed_project_root(
                str(self._file_store.provider_dir(provider_id)),
                project_kind=ProjectKind.PROVIDER,
            )
            self._project_repository.save_project(Project(
                project_id=project_id,
                name=entry.display_name,
                root_path=str(root_path),
                category_id=(
                    existing.category_id
                    if existing is not None and existing.category_id in category_ids
                    else fallback_category.category_id
                ),
                project_kind=ProjectKind.PROVIDER,
                is_default=False,
                sort_order=sort_order,
                created_at=existing.created_at if existing is not None else created_at,
                updated_at=updated_at,
            ))

        for project_id in existing_projects.keys() - live_project_ids:
            self._project_repository.delete_project(project_id)

    def move_provider_to_category(self, provider_id: str, category_id: str) -> Project:
        return self._project_service.move_project_to_category(
            provider_project_id(provider_id),
            category_id=category_id,
        )

    def validate_provider_category(self, category_id: str) -> None:
        category = self._project_service.get_project_category(category_id)
        if category is None or category.category_kind is not ProjectKind.PROVIDER:
            raise BadRequestError("模型供应商分类不存在。")


def provider_project_id(provider_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"tiance:provider:{provider_id}"))


def _manifest_timestamp(manifest: dict[str, object], key: str) -> str | None:
    value = manifest.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@lru_cache
def get_provider_workspace_registry_service() -> ProviderWorkspaceRegistryService:
    return ProviderWorkspaceRegistryService(
        get_provider_catalog_repository(),
        get_provider_file_store(),
        get_project_repository(),
        get_project_service(),
        get_project_storage(),
    )
