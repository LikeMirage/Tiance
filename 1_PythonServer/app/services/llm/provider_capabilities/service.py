from __future__ import annotations

import asyncio
from functools import lru_cache
import logging

from app.core.errors import BadRequestError, NotFoundError, UpstreamProviderError
from app.domain.llm.provider_capabilities import ProviderWebSearchResult
from app.infra.llm.provider_capabilities import (
    ProviderCapabilityRemoteClient,
    get_provider_capability_remote_client,
)
from app.infra.llm.provider_capabilities.base import (
    PROVIDER_WEB_SEARCH_OPERATION_TIMEOUT_SECONDS,
)
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
    get_provider_api_key_scheduler,
)
from app.services.llm.provider.config_runtime import ProviderConfigRuntimeResolver
from app.services.llm.usage import LlmUsageService, get_llm_usage_service
from app.services.tools.host_capability_access import HostCapabilityGrant


logger = logging.getLogger(__name__)


class ProviderCapabilityService:
    def __init__(
        self,
        catalog_repository: ProviderCatalogRepository,
        config_repository: ProviderConfigRepository,
        remote_client: ProviderCapabilityRemoteClient,
        api_key_scheduler: ProviderApiKeyScheduler,
        usage_service: LlmUsageService,
    ) -> None:
        self._catalog_repository = catalog_repository
        self._config_repository = config_repository
        self._remote_client = remote_client
        self._usage_service = usage_service
        self._runtime_resolver = ProviderConfigRuntimeResolver(api_key_scheduler)

    async def web_search(
        self,
        *,
        grant: HostCapabilityGrant,
        query: str,
    ) -> ProviderWebSearchResult:
        provider_template = self._catalog_repository.get_entry(grant.provider_id)
        if provider_template is None:
            raise NotFoundError(f"供应商 '{grant.provider_id}' 不存在。")
        provider_config = self._config_repository.get_config(grant.provider_id)
        if provider_config is None:
            raise NotFoundError(f"供应商配置 '{grant.provider_id}' 不存在。")
        if not provider_config.enabled:
            raise BadRequestError(f"供应商 '{grant.provider_id}' 未启用。")

        runtime_credentials = self._runtime_resolver.resolve_runtime_credentials(
            provider_template,
            provider_config,
        )
        if runtime_credentials is None:
            raise BadRequestError(f"供应商 '{grant.provider_id}' 没有可用的 API Key。")
        runtime_config, selected_api_key = runtime_credentials

        try:
            async with asyncio.timeout(PROVIDER_WEB_SEARCH_OPERATION_TIMEOUT_SECONDS):
                result = await self._remote_client.web_search(
                    provider_template=provider_template,
                    runtime_config=runtime_config,
                    api_key=selected_api_key.api_key,
                    model_id=grant.model_id,
                    query=query,
                )
        except TimeoutError as exc:
            raise UpstreamProviderError(
                "供应商内置网络搜索超过 150 秒，操作已取消。",
                code="provider_web_search_timeout",
            ) from exc

        if result.usage is not None:
            try:
                self._usage_service.record_message_usage(
                    project_id=grant.project_id,
                    session_id=grant.session_id,
                    message_id=f"provider_web_search:{grant.grant_id}",
                    provider_id=grant.provider_id,
                    model_id=grant.model_id,
                    usage=result.usage,
                    usage_feature_key="provider_web_search",
                )
            except Exception:
                logger.exception("Failed to record usage for provider web search.")
        return result


@lru_cache
def get_provider_capability_service() -> ProviderCapabilityService:
    return ProviderCapabilityService(
        get_provider_catalog_repository(),
        get_provider_config_repository(),
        get_provider_capability_remote_client(),
        get_provider_api_key_scheduler(),
        get_llm_usage_service(),
    )
