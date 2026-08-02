# 供应商级联删除服务
# 删除供应商文件包

from app.domain.llm.provider_catalog import ProviderCatalogEntry
from app.repositories.llm.provider_catalog_deletion_repository import (
    ProviderCatalogDeletionRepository,
)


class ProviderCatalogDeletionService:
    def __init__(
        self,
        deletion_repository: ProviderCatalogDeletionRepository,
    ) -> None:
        self._deletion_repository = deletion_repository

    def delete_provider(self, provider_template: ProviderCatalogEntry) -> None:
        self._deletion_repository.delete_provider_package(provider_template.provider_id)
