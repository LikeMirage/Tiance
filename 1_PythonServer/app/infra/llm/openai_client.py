# OpenAI 兼容协议模型发现客户端
# 从 /v1/models 端点获取模型列表

from collections.abc import Awaitable, Callable

from app.domain.llm.discovered_model import DiscoveredModel
from app.domain.llm.provider_catalog import AuthScheme
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.infra.llm.url_utils import require_model_discovery_url
from app.infra.llm.request_auth import apply_auth_to_url, build_auth_headers

GetJson = Callable[[str, dict[str, str]], Awaitable[dict[str, object]]]


class OpenAIModelDiscoveryClient:
    async def discover_models(
        self,
        auth_scheme: AuthScheme,
        runtime_config: ProviderRuntimeConfig,
        api_key: str,
        get_json: GetJson,
    ) -> list[DiscoveredModel]:
        """调用 OpenAI 兼容的 /v1/models 接口发现模型"""
        payload = await get_json(
            url=apply_auth_to_url(
                require_model_discovery_url(runtime_config),
                auth_scheme,
                api_key,
            ),
            headers=build_auth_headers(auth_scheme, api_key),
        )
        items = payload.get("data", [])
        return [
            DiscoveredModel(
                model_id=str(item["id"]),
                display_name=str(item.get("name") or item["id"]),
                provider_id=runtime_config.provider_id,
                raw_payload=item if isinstance(item, dict) else None,
            )
            for item in items
            if isinstance(item, dict) and item.get("id")
        ]
