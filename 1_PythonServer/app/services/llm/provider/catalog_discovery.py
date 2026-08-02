# 供应商目录模型发现服务
# 在未保存配置的情况下，通过 API Key 和 URL 发现模型

import asyncio
from dataclasses import dataclass
from functools import lru_cache

from app.core.errors import BadRequestError, NotFoundError
from app.domain.llm.discovered_model import DiscoveredModel
from app.domain.llm.provider_catalog import ProviderCatalogEntry
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.infra.llm.provider_remote_client import ProviderRemoteClient, get_provider_remote_client
from app.repositories.llm.provider_catalog_repository import (
    ProviderCatalogRepository,
    get_provider_catalog_repository,
)
from app.repositories.llm.provider_config_repository import (
    ProviderConfigRepository,
    get_provider_config_repository,
)
from app.services.llm.provider.api_key_scheduler import (
    ProviderApiKeyScheduler,
    ProviderRuntimeApiKey,
    get_provider_api_key_scheduler,
)
from app.services.llm.provider.api_base_url_validation import normalize_provider_api_base_url
from app.services.llm.provider.config_runtime import ProviderConfigRuntimeResolver
from app.services.llm.provider.discovered_model_metadata import enrich_discovered_models


@dataclass(frozen=True, slots=True)
class _CatalogDiscoveryContext:
    provider_template: ProviderCatalogEntry
    runtime_config: ProviderRuntimeConfig
    selected_api_key: ProviderRuntimeApiKey


class ProviderCatalogDiscoveryService:
    def __init__(
        self,
        catalog_repository: ProviderCatalogRepository,
        config_repository: ProviderConfigRepository,
        remote_client: ProviderRemoteClient,
        api_key_scheduler: ProviderApiKeyScheduler,
    ) -> None:
        self._catalog_repository = catalog_repository
        self._config_repository = config_repository
        self._remote_client = remote_client
        self._runtime_resolver = ProviderConfigRuntimeResolver(
            api_key_scheduler,
        )

    async def discover_models(
        self,
        provider_id: str,
        api_base_url: str | None,
        api_key: str | None,
        model_discovery_url: str | None = None,
    ) -> list[DiscoveredModel]:
        if api_key and api_key.strip():
            raise BadRequestError("模型发现请先保存供应商配置；API Key 不应通过前端预览接口提交。")

        context = await asyncio.to_thread(
            self._resolve_discovery_context,
            provider_id,
            api_base_url,
            model_discovery_url,
        )
        discovered_models = await self._remote_client.discover_models(
            context.provider_template,
            context.runtime_config,
            context.selected_api_key.api_key,
        )
        return enrich_discovered_models(discovered_models)

    def _resolve_discovery_context(
        self,
        provider_id: str,
        api_base_url: str | None,
        model_discovery_url: str | None = None,
    ) -> _CatalogDiscoveryContext:
        provider_template = self._catalog_repository.get_entry(provider_id)
        if provider_template is None:
            raise NotFoundError(f"Provider template '{provider_id}' was not found.")

        provider_config = self._config_repository.get_config(provider_template.provider_id)
        if provider_config is None:
            raise BadRequestError("模型发现需要先保存供应商配置。")

        runtime_credentials = self._runtime_resolver.resolve_runtime_credentials(
            provider_template,
            provider_config,
        )
        if runtime_credentials is None:
            raise BadRequestError(f"Provider config '{provider_id}' has no saved API key.")

        runtime_config, selected_api_key = runtime_credentials
        if api_base_url and api_base_url.strip():
            runtime_config = ProviderRuntimeConfig(
                provider_id=runtime_config.provider_id,
                display_name=runtime_config.display_name,
                api_base_url=normalize_provider_api_base_url(api_base_url),
                model_discovery_url=runtime_config.model_discovery_url,
            )
        if model_discovery_url and model_discovery_url.strip():
            runtime_config = ProviderRuntimeConfig(
                provider_id=runtime_config.provider_id,
                display_name=runtime_config.display_name,
                api_base_url=runtime_config.api_base_url,
                model_discovery_url=normalize_provider_api_base_url(model_discovery_url),
            )

        return _CatalogDiscoveryContext(
            provider_template=provider_template,
            runtime_config=runtime_config,
            selected_api_key=selected_api_key,
        )


@lru_cache
def get_provider_catalog_discovery_service() -> ProviderCatalogDiscoveryService:
    return ProviderCatalogDiscoveryService(
        get_provider_catalog_repository(),
        get_provider_config_repository(),
        get_provider_remote_client(),
        get_provider_api_key_scheduler(),
    )
