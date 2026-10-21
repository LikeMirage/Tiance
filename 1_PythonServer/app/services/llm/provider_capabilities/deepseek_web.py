from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.core.errors import AppError
from app.infra.llm.provider_capabilities.deepseek_web import request_deepseek_web
from app.repositories.llm.provider_catalog_repository import get_provider_catalog_repository
from app.repositories.llm.provider_config_repository import get_provider_config_repository
from app.services.llm.provider.api_key_scheduler import get_provider_api_key_scheduler
from app.services.llm.provider.config_runtime import ProviderConfigRuntimeResolver


class DeepSeekWebService:
    def __init__(self, catalog, configs, key_scheduler, request=request_deepseek_web):
        self._catalog = catalog
        self._configs = configs
        self._credentials = ProviderConfigRuntimeResolver(key_scheduler)
        self._request = request

    async def execute(self, *, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        provider = self._catalog.get_entry("deepseek")
        config = self._configs.get_config("deepseek")
        if provider is None or config is None:
            raise self._missing_key()
        if not config.enabled:
            raise AppError(
                "模型集中的 DeepSeek 供应商未启用。请启用并配置官方 API Key，或用 action=configure 配置本工具的 Key。",
                code="DEEPSEEK_PROVIDER_DISABLED",
            )
        credentials = self._credentials.resolve_runtime_credentials(provider, config)
        if credentials is None or not credentials[1].api_key:
            raise self._missing_key()
        # Search/Fetch have fixed official endpoints and do not use a chat model or URL.
        return await self._request(action=action, payload=payload, api_key=credentials[1].api_key)

    @staticmethod
    def _missing_key() -> AppError:
        return AppError(
            "未找到可用的 DeepSeek 官方 API Key。请在“模型集 → DeepSeek”中添加 Key 并启用轮询权重，"
            "或让 AI 调用本工具 action=configure、api_key=用户提供的 Key 写入 config.json。",
            code="DEEPSEEK_KEY_MISSING",
        )


@lru_cache
def get_deepseek_web_service() -> DeepSeekWebService:
    return DeepSeekWebService(
        get_provider_catalog_repository(), get_provider_config_repository(),
        get_provider_api_key_scheduler(),
    )
