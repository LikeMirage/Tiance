# 供应商目录服务
# 提供供应商模板列表/查询和排序管理

from functools import lru_cache
from datetime import UTC, datetime

from app.core.errors import BadRequestError, NotFoundError
from app.domain.llm.provider_catalog import ProviderCatalogEntry
from app.repositories.llm.provider_catalog_repository import (
    ProviderCatalogRepository,
    get_provider_catalog_repository,
)


class ProviderCatalogService:
    def __init__(
        self,
        repository: ProviderCatalogRepository,
    ) -> None:
        self._repository = repository

    def list_provider_templates(self) -> tuple[ProviderCatalogEntry, ...]:
        return tuple(self._repository.list_entries())

    def get_provider_template(self, provider_id: str) -> ProviderCatalogEntry | None:
        return self._repository.get_entry(provider_id)

    def get_provider_order(self) -> tuple[str, ...]:
        return self._repository.list_ordered_provider_ids()

    def save_provider_order(self, provider_ids: tuple[str, ...]) -> tuple[str, ...]:
        normalized_provider_ids: list[str] = []
        seen_provider_ids: set[str] = set()
        available_provider_ids = {
            provider.provider_id for provider in self._repository.list_entries()
        }

        for provider_id in provider_ids:
            normalized_provider_id = provider_id.strip()
            if not normalized_provider_id:
                continue
            if normalized_provider_id in seen_provider_ids:
                raise BadRequestError(f"Provider id '{normalized_provider_id}' is duplicated.")
            if normalized_provider_id not in available_provider_ids:
                raise NotFoundError(f"Provider template '{normalized_provider_id}' was not found.")
            seen_provider_ids.add(normalized_provider_id)
            normalized_provider_ids.append(normalized_provider_id)

        if normalized_provider_ids and len(normalized_provider_ids) != len(available_provider_ids):
            missing_provider_ids = available_provider_ids.difference(normalized_provider_ids)
            raise BadRequestError(
                "Provider order must include every available provider id. Missing: "
                + ", ".join(sorted(missing_provider_ids))
            )

        return self._repository.replace_provider_order(
            tuple(normalized_provider_ids),
            updated_at=_utc_now(),
        )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@lru_cache
def get_provider_catalog_service() -> ProviderCatalogService:
    return ProviderCatalogService(
        get_provider_catalog_repository(),
    )
