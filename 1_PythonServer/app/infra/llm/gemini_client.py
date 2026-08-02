# Gemini 协议模型发现客户端
# 从 /v1beta/models 端点发现模型，API Key 通过查询参数传递

from collections.abc import Awaitable, Callable

from app.domain.llm.discovered_model import DiscoveredModel
from app.domain.llm.provider_catalog import AuthScheme
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.infra.llm.url_utils import require_model_discovery_url
from app.infra.llm.request_auth import apply_auth_to_url, build_auth_headers

GetJson = Callable[[str, dict[str, str]], Awaitable[dict[str, object]]]


class GeminiModelDiscoveryClient:
    async def discover_models(
        self,
        auth_scheme: AuthScheme,
        runtime_config: ProviderRuntimeConfig,
        api_key: str,
        get_json: GetJson,
    ) -> list[DiscoveredModel]:
        """调用 Gemini /v1beta/models 接口发现模型"""
        payload = await get_json(
            url=apply_auth_to_url(
                require_model_discovery_url(runtime_config),
                auth_scheme,
                api_key,
            ),
            headers=build_auth_headers(auth_scheme, api_key),
        )
        items = payload.get("models", [])
        return [
            DiscoveredModel(
                model_id=_normalize_gemini_model_id(str(item["name"])),
                display_name=str(
                    item.get("displayName") or _normalize_gemini_model_id(str(item["name"]))
                ),
                provider_id=runtime_config.provider_id,
                raw_payload=item if isinstance(item, dict) else None,
            )
            for item in items
            if isinstance(item, dict) and item.get("name")
        ]


def _normalize_gemini_model_id(name: str) -> str:
    """去掉 Gemini 模型名中的 'models/' 前缀"""
    return name.removeprefix("models/")
