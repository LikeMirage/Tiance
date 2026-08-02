# 供应商远程客户端外观
# 根据协议族路由到对应的模型发现客户端，并提供 HTTP GET/POST 能力

from functools import lru_cache

from app.domain.llm.provider_catalog import (
    ModelDiscoveryStrategy,
    ProviderCatalogEntry,
)
from app.domain.llm.discovered_model import DiscoveredModel
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.infra.http_client import get_shared_http_client
from app.infra.llm.anthropic_client import AnthropicModelDiscoveryClient
from app.infra.llm.gemini_client import GeminiModelDiscoveryClient
from app.infra.llm.openai_client import OpenAIModelDiscoveryClient
from app.infra.llm.provider_model_probe_client import ProviderModelProbeClient


class ProviderRemoteClient:
    def __init__(self) -> None:
        self._openai_client = OpenAIModelDiscoveryClient()
        self._anthropic_client = AnthropicModelDiscoveryClient()
        self._gemini_client = GeminiModelDiscoveryClient()
        self._model_probe_client = ProviderModelProbeClient()

    async def discover_models(
        self,
        provider_template: ProviderCatalogEntry,
        runtime_config: ProviderRuntimeConfig,
        api_key: str,
    ) -> list[DiscoveredModel]:
        """根据独立的模型发现策略选择客户端。"""
        if (
            provider_template.model_discovery_strategy
            == ModelDiscoveryStrategy.ANTHROPIC_MODELS
        ):
            return await self._anthropic_client.discover_models(
                provider_template.model_discovery_auth_scheme,
                runtime_config,
                api_key,
                self._get_json,
            )

        if (
            provider_template.model_discovery_strategy
            == ModelDiscoveryStrategy.GEMINI_MODELS
        ):
            return await self._gemini_client.discover_models(
                provider_template.model_discovery_auth_scheme,
                runtime_config,
                api_key,
                self._get_json,
            )

        return await self._openai_client.discover_models(
            provider_template.model_discovery_auth_scheme,
            runtime_config,
            api_key,
            self._get_json,
        )

    async def check_model(
        self,
        provider_template: ProviderCatalogEntry,
        runtime_config: ProviderRuntimeConfig,
        api_key: str,
        model_id: str,
    ) -> dict[str, object]:
        """探测模型是否可用"""
        return await self._model_probe_client.probe_model(
            provider_template,
            runtime_config,
            api_key,
            model_id,
            self._post_json,
        )

    async def _get_json(self, url: str, headers: dict[str, str]) -> dict[str, object]:
        """发送 HTTP GET 请求并返回 JSON 响应"""
        client = get_shared_http_client()
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    async def _post_json(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, object],
    ) -> dict[str, object]:
        """发送 HTTP POST 请求并返回 JSON 响应"""
        client = get_shared_http_client()
        response = await client.post(url, headers=headers, json=body)
        response.raise_for_status()
        if not response.content:
            return {}
        payload = response.json()
        return payload if isinstance(payload, dict) else {}


@lru_cache
def get_provider_remote_client() -> ProviderRemoteClient:
    """获取 ProviderRemoteClient 单例"""
    return ProviderRemoteClient()
