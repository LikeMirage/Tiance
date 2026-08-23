from functools import lru_cache

from app.repositories.llm.provider_catalog_repository import (
    ProviderCatalogRepository,
    get_provider_catalog_repository,
)


class ProviderCatalogDeletionRepository:
    def __init__(self, catalog_repository: ProviderCatalogRepository) -> None:
        self._catalog_repository = catalog_repository

    def delete_provider_package(self, provider_id: str) -> bool:
        return self._catalog_repository.delete_entry(provider_id)

    def provider_package_exists(self, provider_id: str) -> bool:
        return self._catalog_repository.has_provider_directory(provider_id)


@lru_cache
def get_provider_catalog_deletion_repository() -> ProviderCatalogDeletionRepository:
    return ProviderCatalogDeletionRepository(get_provider_catalog_repository())
