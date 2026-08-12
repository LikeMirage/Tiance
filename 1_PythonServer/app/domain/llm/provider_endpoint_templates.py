# 供应商端点契约工厂
# 生成地址完整保存；推导函数仅供旧文件格式的一次性迁移使用

import re
from collections.abc import Mapping
from urllib.parse import urlsplit, urlunsplit

from app.domain.llm.provider_catalog import ProviderEndpointTemplate, ProviderProtocolFamily


_API_VERSION_SEGMENT = re.compile(r"^v\d+(?:beta|alpha)?$", re.IGNORECASE)

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


def derive_model_discovery_url(
    api_base_url: str,
    protocol_family: ProviderProtocolFamily | str,
) -> str | None:
    """为历史文件迁移生成模型列表地址；正式配置链路不调用。"""

    parsed = urlsplit(api_base_url.strip())
    if not parsed.scheme or not parsed.netloc:
        return None

    segments = [segment for segment in parsed.path.split("/") if segment]
    if not segments:
        default_prefix = (
            "v1beta"
            if _protocol_value(protocol_family)
            == ProviderProtocolFamily.GEMINI_GENERATE_CONTENT.value
            else "v1"
        )
        model_segments = [default_prefix, "models"]
    elif _is_gemini_generation_template(segments):
        model_segments = segments[:-1]
    elif len(segments) >= 2 and segments[-2:] == ["chat", "completions"]:
        model_segments = [*segments[:-2], "models"]
    elif segments[-1] in {"responses", "messages"}:
        model_segments = [*segments[:-1], "models"]
    elif segments[-1] == "models":
        model_segments = segments
    elif _API_VERSION_SEGMENT.fullmatch(segments[-1]):
        model_segments = [*segments, "models"]
    else:
        model_segments = [*segments[:-1], "models"]

    model_path = f"/{'/'.join(model_segments)}"
    return urlunsplit((parsed.scheme, parsed.netloc, model_path, "", ""))


def _is_gemini_generation_template(segments: list[str]) -> bool:
    return (
        len(segments) >= 2
        and segments[-2] == "models"
        and "{model}" in segments[-1]
    )


def _protocol_value(protocol_family: ProviderProtocolFamily | str) -> str:
    return (
        protocol_family.value
        if isinstance(protocol_family, ProviderProtocolFamily)
        else str(protocol_family)
    )
