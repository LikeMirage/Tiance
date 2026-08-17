# 供应商配置服务
# 配置保存、模型发现（使用已保存凭证）、模型探测、云模型缓存管理等

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache

from app.core.errors import NotFoundError
from app.domain.llm.provider_cloud_model import ProviderCloudModelCache
from app.domain.llm.provider_catalog import (
    AuthScheme,
    ModelDiscoveryStrategy,
    ProviderCatalogEntry,
    ProviderProtocolFamily,
)
from app.domain.llm.provider_config import ProviderConfig
from app.domain.llm.reasoning_replay import ReasoningReplayMode
from app.domain.llm.discovered_model import DiscoveredModel
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.infra.llm.provider_remote_client import ProviderRemoteClient, get_provider_remote_client
from app.repositories.llm.provider_catalog_repository import (
    ProviderCatalogRepository,
    get_provider_catalog_repository,
)
from app.repositories.llm.provider_adaptation_rules_repository import (
    ProviderAdaptationRulesRepository,
    get_provider_adaptation_rules_repository,
)
from app.repositories.llm.provider_cloud_model_repository import (
    ProviderCloudModelRepository,
    get_provider_cloud_model_repository,
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
from app.services.llm.provider.api_key_secrets import has_api_key_secret
from app.services.llm.provider.config_runtime import ProviderConfigRuntimeResolver
from app.services.llm.provider.config_writer import (
    ProviderApiKeyConfigInput,
    ProviderConfigWriter,
)
from app.services.llm.provider.discovered_model_metadata import enrich_discovered_models


@dataclass(frozen=True, slots=True)
class _ProviderRuntimeContext:
    provider_template: ProviderCatalogEntry
    config: ProviderConfig
    runtime_config: ProviderRuntimeConfig
    selected_api_key: ProviderRuntimeApiKey


class ProviderConfigService:
    def __init__(
        self,
        config_repository: ProviderConfigRepository,
        catalog_repository: ProviderCatalogRepository,
        cloud_model_repository: ProviderCloudModelRepository,
        remote_client: ProviderRemoteClient,
        api_key_scheduler: ProviderApiKeyScheduler,
        adaptation_rules_repository: ProviderAdaptationRulesRepository,
    ) -> None:
        self._config_repository = config_repository
        self._catalog_repository = catalog_repository
        self._cloud_model_repository = cloud_model_repository
        self._remote_client = remote_client
        self._adaptation_rules_repository = adaptation_rules_repository
        self._config_writer = ProviderConfigWriter(
            config_repository,
            cloud_model_repository,
        )
        self._runtime_resolver = ProviderConfigRuntimeResolver(
            api_key_scheduler,
        )

    def list_configs(self) -> tuple[ProviderConfig, ...]:
        return self._config_repository.list_configs()

    def get_config(self, provider_id: str) -> ProviderConfig | None:
        return self._config_repository.get_config(provider_id)

    def get_api_key_presence_by_id(self, config: ProviderConfig) -> dict[str, bool]:
        return {
            api_key.key_id: has_api_key_secret(api_key)
            for api_key in config.api_keys
        }

    def get_prompt_cache_retention_seconds(
        self,
        provider_id: str,
        model_id: str | None = None,
    ) -> int:
        self._require_provider_template(provider_id)
        return self._adaptation_rules_repository.resolve_prompt_cache_retention_seconds(
            provider_id=provider_id,
            model_id=model_id,
        )

    def save_prompt_cache_retention_seconds(
        self,
        *,
        provider_id: str,
        seconds: int,
    ) -> int:
        self._require_provider_template(provider_id)
        return self._adaptation_rules_repository.save_prompt_cache_retention_seconds(
            provider_id=provider_id,
            seconds=seconds,
        )

    def save_config(
        self,
        *,
        provider_id: str,
        api_base_url: str | None,
        protocol_family: ProviderProtocolFamily,
        auth_scheme: AuthScheme,
        enabled: bool,
        api_keys: tuple[ProviderApiKeyConfigInput, ...],
        model_discovery_url: str | None = None,
        model_discovery_strategy: ModelDiscoveryStrategy,
        model_discovery_auth_scheme: AuthScheme,
        reasoning_replay_mode: ReasoningReplayMode | None = None,
    ) -> ProviderConfig:
        provider_template = self._require_provider_template(provider_id)
        return self._config_writer.save_config(
            provider_template=provider_template,
            api_base_url=api_base_url,
            protocol_family=protocol_family,
            auth_scheme=auth_scheme,
            model_discovery_url=model_discovery_url,
            model_discovery_strategy=model_discovery_strategy,
            model_discovery_auth_scheme=model_discovery_auth_scheme,
            enabled=enabled,
            api_keys=api_keys,
            reasoning_replay_mode=reasoning_replay_mode,
        )

    async def discover_models(self, provider_id: str) -> list[DiscoveredModel] | None:
        context = await asyncio.to_thread(self._resolve_runtime_context, provider_id)
        if context is None:
            return None

        models = await self._remote_client.discover_models(
            context.provider_template,
            context.runtime_config,
            context.selected_api_key.api_key,
        )
        return enrich_discovered_models(models)

    async def check_model(
        self,
        provider_id: str,
        model_id: str,
    ) -> dict[str, object] | None:
        context = await asyncio.to_thread(self._resolve_runtime_context, provider_id)
        if context is None:
            return None

        result = await self._remote_client.check_model(
            context.provider_template,
            context.runtime_config,
            context.selected_api_key.api_key,
            model_id,
        )
        result["selected_key_id"] = context.selected_api_key.key_id
        result["selected_api_key_hint"] = context.selected_api_key.api_key_hint
        return result

    def get_cloud_model_cache(self, provider_id: str) -> ProviderCloudModelCache:
        provider_template = self._require_provider_template(provider_id)
        config = self._config_repository.get_config(provider_template.provider_id)
        api_base_url = (
            config.api_base_url
            if config is not None
            else provider_template.endpoints.api_base_url
        )

        cached_models = self._cloud_model_repository.get_cache(
            provider_id=provider_template.provider_id,
            protocol_family=provider_template.protocol_family.value,
            api_base_url=api_base_url,
        )
        if cached_models is not None:
            return cached_models

        return ProviderCloudModelCache(
            provider_id=provider_template.provider_id,
            protocol_family=provider_template.protocol_family.value,
            api_base_url=api_base_url,
            discovered_at=None,
            models=(),
        )

    async def refresh_cloud_model_cache(
        self,
        provider_id: str,
    ) -> ProviderCloudModelCache | None:
        context = await asyncio.to_thread(self._resolve_runtime_context, provider_id)
        if context is None:
            return None

        models = await self._remote_client.discover_models(
            context.provider_template,
            context.runtime_config,
            context.selected_api_key.api_key,
        )
        models = enrich_discovered_models(models)

        cache = ProviderCloudModelCache(
            provider_id=context.provider_template.provider_id,
            protocol_family=context.provider_template.protocol_family.value,
            api_base_url=context.config.api_base_url,
            discovered_at=_utc_now(),
            models=tuple(models),
        )
        return await asyncio.to_thread(self._cloud_model_repository.replace_provider_cache, cache)

    def _require_provider_template(self, provider_id: str):
        provider_template = self._catalog_repository.get_entry(provider_id)
        if provider_template is None:
            raise NotFoundError(f"Provider template '{provider_id}' was not found.")
        return provider_template

    def _resolve_runtime_credentials(
        self,
        provider_template,
        config: ProviderConfig,
    ):
        return self._runtime_resolver.resolve_runtime_credentials(
            provider_template,
            config,
        )

    def _resolve_runtime_context(self, provider_id: str) -> _ProviderRuntimeContext | None:
        provider_template = self._require_provider_template(provider_id)
        config = self._config_repository.get_config(provider_template.provider_id)
        if config is None:
            return None

        runtime_credentials = self._resolve_runtime_credentials(provider_template, config)
        if runtime_credentials is None:
            return None

        runtime_config, selected_api_key = runtime_credentials
        return _ProviderRuntimeContext(
            provider_template=provider_template,
            config=config,
            runtime_config=runtime_config,
            selected_api_key=selected_api_key,
        )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@lru_cache
def get_provider_config_service() -> ProviderConfigService:
    return ProviderConfigService(
        get_provider_config_repository(),
        get_provider_catalog_repository(),
        get_provider_cloud_model_repository(),
        get_provider_remote_client(),
        get_provider_api_key_scheduler(),
        get_provider_adaptation_rules_repository(),
    )
