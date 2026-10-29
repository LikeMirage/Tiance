# 供应商端点契约工厂
# 生成地址和模型列表地址均完整保存，不从其他地址推导。

from collections.abc import Mapping

from app.domain.llm.provider_catalog import ProviderEndpointTemplate, ProviderProtocolFamily


def build_provider_endpoint_template(
    *,
    api_base_url: str,
    model_discovery_url: str | None = None,
    generation_urls: Mapping[ProviderProtocolFamily | str, str] | None = None,
) -> ProviderEndpointTemplate:
    normalized_generation_urls = normalize_generation_urls(generation_urls or {})
    return ProviderEndpointTemplate(
        api_base_url=api_base_url,
        text_generation_url_template=api_base_url,
        model_discovery_url=model_discovery_url,
        generation_urls=normalized_generation_urls,
    )


def normalize_generation_urls(
    generation_urls: Mapping[ProviderProtocolFamily | str, str],
) -> dict[ProviderProtocolFamily, str]:
    normalized: dict[ProviderProtocolFamily, str] = {}
    for protocol_family, generation_url in generation_urls.items():
        try:
            protocol = (
                protocol_family
                if isinstance(protocol_family, ProviderProtocolFamily)
                else ProviderProtocolFamily(str(protocol_family))
            )
        except ValueError:
            continue
        if isinstance(generation_url, str) and generation_url.strip():
            normalized[protocol] = generation_url.strip()
    return normalized
