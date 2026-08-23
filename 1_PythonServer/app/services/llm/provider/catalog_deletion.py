# 供应商级联删除服务
# 删除供应商文件包

from app.repositories.llm.provider_catalog_deletion_repository import (
    ProviderCatalogDeletionRepository,
)


class ProviderCatalogDeletionService:
    def __init__(
        self,
        deletion_repository: ProviderCatalogDeletionRepository,
    ) -> None:
        self._deletion_repository = deletion_repository

    def provider_exists(self, provider_id: str) -> bool:
        return self._deletion_repository.provider_package_exists(provider_id)

    def delete_provider(self, provider_id: str) -> bool:
        return self._deletion_repository.delete_provider_package(provider_id)
