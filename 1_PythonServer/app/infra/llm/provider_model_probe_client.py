# 模型探测客户端
# 发送最小化请求（"ping", max_tokens=1）验证模型和 API Key 是否可用

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.domain.llm.provider_catalog import ProviderCatalogEntry, ProviderProtocolFamily
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.infra.llm.anthropic_auth import build_anthropic_auth_headers
from app.infra.llm.request_auth import apply_auth_to_url, build_auth_headers
from app.infra.llm.url_utils import render_generation_url

PostJson = Callable[
    [str, dict[str, str], dict[str, object]],
    Awaitable[dict[str, object]],
]


@dataclass(frozen=True, slots=True)
class ProviderModelProbeRequest:
    """模型探测请求参数：URL、请求头、请求体"""
    url: str
    headers: dict[str, str]
    body: dict[str, object]


class ProviderModelProbeClient:
    async def probe_model(
        self,
        provider_template: ProviderCatalogEntry,
        runtime_config: ProviderRuntimeConfig,
        api_key: str,
        model_id: str,
        post_json: PostJson,
    ) -> dict[str, object]:
        """向供应商发送最小化探测请求，验证 API Key 和模型可用性"""
        normalized_model_id = model_id.strip()
        request = _build_probe_request(
            provider_template=provider_template,
            runtime_config=runtime_config,
            api_key=api_key,
            model_id=normalized_model_id,
        )
        await post_json(request.url, request.headers, request.body)
        return {
            "ok": True,
            "checked_url": _redact_url(request.url),
            "model_id": normalized_model_id,
        }


def _build_probe_request(
    *,
    provider_template: ProviderCatalogEntry,
    runtime_config: ProviderRuntimeConfig,
    api_key: str,
    model_id: str,
) -> ProviderModelProbeRequest:
    """根据协议族构建最小化探测请求"""
    if provider_template.protocol_family == ProviderProtocolFamily.OPENAI_RESPONSES:
        return ProviderModelProbeRequest(
            url=apply_auth_to_url(
                runtime_config.api_base_url,
                provider_template.auth_scheme,
                api_key,
            ),
            headers=build_auth_headers(provider_template.auth_scheme, api_key),
            body={
                "model": model_id,
                "input": "ping",
                "max_output_tokens": 1,
            },
        )

    if provider_template.protocol_family == ProviderProtocolFamily.ANTHROPIC_MESSAGES:
        return ProviderModelProbeRequest(
            url=apply_auth_to_url(
                runtime_config.api_base_url,
                provider_template.auth_scheme,
                api_key,
            ),
            headers=build_anthropic_auth_headers(
                provider_template.auth_scheme,
                api_key,
            ),
            body={
                "model": model_id,
                "max_tokens": 1,
                "messages": [
                    {
                        "role": "user",
                        "content": "ping",
                    }
                ],
            },
        )

    if provider_template.protocol_family == ProviderProtocolFamily.GEMINI_GENERATE_CONTENT:
        generation_url = render_generation_url(
            runtime_config.api_base_url,
            model_id=model_id,
            action="generateContent",
        )
        return ProviderModelProbeRequest(
            url=apply_auth_to_url(
                generation_url,
                provider_template.auth_scheme,
                api_key,
            ),
            headers=build_auth_headers(provider_template.auth_scheme, api_key),
            body={
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": "ping",
                            }
                        ],
                    }
                ],
                "generationConfig": {
                    "maxOutputTokens": 1,
                },
            },
        )

    return ProviderModelProbeRequest(
        url=apply_auth_to_url(
            runtime_config.api_base_url,
            provider_template.auth_scheme,
            api_key,
        ),
        headers=build_auth_headers(provider_template.auth_scheme, api_key),
        body={
            "model": model_id,
            "messages": [
                {
                    "role": "user",
                    "content": "ping",
                }
            ],
            "max_tokens": 1,
        },
    )
def _redact_url(url: str) -> str:
    return url.replace("key=", "key=***")
