from dataclasses import replace
from pathlib import Path

from app.domain.project import ProjectKind
from app.infra.database import ensure_database_schema
from app.infra.projects import ProjectStorage
from app.repositories.llm.provider_catalog_repository import ProviderCatalogRepository
from app.repositories.llm.provider_file_store import ProviderFileStore
from app.repositories.project import ProjectRepository
from app.repositories.project.file_project_catalog import FileProjectCatalog
from app.services.llm.provider.storage_bootstrap import ensure_provider_file_storage
from app.services.llm.provider.workspace_registry import (
    ProviderWorkspaceRegistryService,
    provider_project_id,
)
from app.services.application.project_category_deletion import (
    ProjectCategoryDeletionApplicationService,
)
from app.services.project import ProjectService


def test_provider_directories_are_registered_as_projects_and_stay_in_sync(tmp_path):
    database_path = tmp_path / "tiance.db"
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path, database_path)
    ensure_database_schema(database_path)

    file_store = ProviderFileStore(providers_path)
    catalog_repository = ProviderCatalogRepository(file_store)
    project_repository = ProjectRepository(
        database_path,
        file_catalogs=(
            FileProjectCatalog(providers_path, project_kind=ProjectKind.PROVIDER),
        ),
    )
    project_storage = ProjectStorage(
        projects_root=tmp_path / "projects",
        providers_root=providers_path,
    )
    project_service = ProjectService(project_repository, project_storage)
    registry = ProviderWorkspaceRegistryService(
        catalog_repository,
        file_store,
        project_repository,
        project_service,
        project_storage,
    )

    registry.synchronize()

    provider_ids = file_store.list_provider_ids()
    provider_projects = {
        project.project_id: project
        for project in project_repository.list_projects()
        if project.project_kind.value == "provider"
    }
    assert len(provider_projects) == len(provider_ids)
    assert (providers_path / "catalog.json").is_file()
    assert project_repository.list_database_projects(
        project_kind=ProjectKind.PROVIDER,
    ) == ()
    assert project_repository.list_database_project_categories(
        category_kind=ProjectKind.PROVIDER,
    ) == ()
    openai_project = provider_projects[provider_project_id("openai")]
    assert openai_project.name == catalog_repository.get_entry("openai").display_name
    assert openai_project.root_path == str((providers_path / "openai").resolve())

    secondary_category = project_service.create_project_category(
        name="AI 协作",
        category_kind=ProjectKind.PROVIDER,
    )
    project_service.move_project_to_category(
        openai_project.project_id,
        category_id=secondary_category.category_id,
    )
    registry.synchronize()
    assert (
        project_repository.get_project(openai_project.project_id).category_id
        == secondary_category.category_id
    )

    reversed_provider_ids = tuple(reversed(provider_ids))
    catalog_repository.replace_provider_order(
        reversed_provider_ids,
        updated_at="2026-08-01T00:00:00+00:00",
    )
    registry.synchronize()
    ordered_provider_ids = tuple(
        Path(project.root_path).name
        for project in project_repository.list_projects()
        if project.project_kind is ProjectKind.PROVIDER
    )
    assert ordered_provider_ids == reversed_provider_ids

    openai = catalog_repository.get_entry("openai")
    assert openai is not None
    catalog_repository.save_entry(
        replace(openai, display_name="OpenAI 正式名称"),
        updated_at="2026-08-01T00:00:00+00:00",
    )
    registry.synchronize()
    assert project_repository.get_project(provider_project_id("openai")).name == "OpenAI 正式名称"

    class ProviderDeletion:
        def delete_providers(self, provider_ids: tuple[str, ...]) -> None:
            for provider_id in provider_ids:
                assert catalog_repository.delete_entry(provider_id) is True
            registry.synchronize()

    ProjectCategoryDeletionApplicationService(
        project_service,
        ProviderDeletion(),  # type: ignore[arg-type]
    ).delete_category(secondary_category.category_id)

    assert project_repository.get_project(provider_project_id("openai")) is None
    assert project_repository.get_project_category(secondary_category.category_id) is None
    assert catalog_repository.get_entry("openai") is None
