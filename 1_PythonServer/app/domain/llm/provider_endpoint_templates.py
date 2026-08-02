# 供应商端点契约工厂
# 生成地址完整保存；推导函数仅供旧文件格式的一次性迁移使用

import re
from collections.abc import Mapping
from urllib.parse import urlsplit, urlunsplit

from app.domain.llm.provider_catalog import ProviderEndpointTemplate, ProviderProtocolFamily


_API_VERSION_SEGMENT = re.compile(r"^v\d+(?:beta|alpha)?$", re.IGNORECASE)

_DEFAULT_API_VERSION_BY_PROTOCOL = {
    ProviderProtocolFamily.OPENAI_RESPONSES.value: "v1",
    ProviderProtocolFamily.ANTHROPIC_MESSAGES.value: "v1",
    ProviderProtocolFamily.GEMINI_GENERATE_CONTENT.value: "v1beta",
}


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


def upgrade_unambiguous_legacy_generation_url(
    api_base_url: str,
    protocol_family: ProviderProtocolFamily | str,
) -> str:
    """Upgrade old host/version base URLs without guessing custom endpoint paths."""

    parsed = urlsplit(api_base_url.strip())
    if not parsed.scheme or not parsed.netloc:
        return api_base_url

    segments = [segment for segment in parsed.path.split("/") if segment]
    if _generation_protocol_for_segments(segments) is not None:
        return api_base_url.strip()
    if segments and not _API_VERSION_SEGMENT.fullmatch(segments[-1]):
        return api_base_url.strip()

    protocol_value = _protocol_value(protocol_family)
    if protocol_value == ProviderProtocolFamily.OPENAI_COMPATIBLE.value:
        return _generation_url(parsed, segments, protocol_value)
    if protocol_value not in _DEFAULT_API_VERSION_BY_PROTOCOL:
        return api_base_url.strip()
    if not segments:
        segments.append(_DEFAULT_API_VERSION_BY_PROTOCOL[protocol_value])
    return _generation_url(parsed, segments, protocol_value)


def retarget_generation_url(
    generation_url: str,
    source_protocol: ProviderProtocolFamily | str,
    target_protocol: ProviderProtocolFamily | str,
) -> str:
    """Retarget recognized generation endpoints when the user changes protocol."""

    source_value = _protocol_value(source_protocol)
    target_value = _protocol_value(target_protocol)
    normalized_url = generation_url.strip()
    if source_value == target_value:
        return normalized_url

    parsed = urlsplit(normalized_url)
    if not parsed.scheme or not parsed.netloc:
        return normalized_url
    segments = [segment for segment in parsed.path.split("/") if segment]
    matched_protocol = _generation_protocol_for_segments(segments)
    if matched_protocol is None:
        return upgrade_unambiguous_legacy_generation_url(normalized_url, target_value)
    if matched_protocol != source_value:
        return normalized_url

    base_segments = _remove_generation_suffix(segments, source_value)
    return _generation_url(parsed, base_segments, target_value)


def _is_gemini_generation_template(segments: list[str]) -> bool:
    return (
        len(segments) >= 2
        and segments[-2] == "models"
        and "{model}" in segments[-1]
    )


def _generation_protocol_for_segments(segments: list[str]) -> str | None:
    if len(segments) >= 2 and segments[-2:] == ["chat", "completions"]:
        return ProviderProtocolFamily.OPENAI_COMPATIBLE.value
    if segments and segments[-1] == "responses":
        return ProviderProtocolFamily.OPENAI_RESPONSES.value
    if segments and segments[-1] == "messages":
        return ProviderProtocolFamily.ANTHROPIC_MESSAGES.value
    if _is_gemini_generation_template(segments):
        return ProviderProtocolFamily.GEMINI_GENERATE_CONTENT.value
    return None


def _remove_generation_suffix(segments: list[str], protocol_value: str) -> list[str]:
    if protocol_value in {
        ProviderProtocolFamily.OPENAI_COMPATIBLE.value,
        ProviderProtocolFamily.GEMINI_GENERATE_CONTENT.value,
    }:
        return segments[:-2]
    return segments[:-1]


def _generation_url(parsed, base_segments: list[str], protocol_value: str) -> str:
    if protocol_value == ProviderProtocolFamily.OPENAI_COMPATIBLE.value:
        generation_segments = [*base_segments, "chat", "completions"]
    elif protocol_value == ProviderProtocolFamily.OPENAI_RESPONSES.value:
        generation_segments = [*base_segments, "responses"]
    elif protocol_value == ProviderProtocolFamily.ANTHROPIC_MESSAGES.value:
        generation_segments = [*base_segments, "messages"]
    elif protocol_value == ProviderProtocolFamily.GEMINI_GENERATE_CONTENT.value:
        generation_segments = [*base_segments, "models", "{model}:{action}"]
    else:
        return urlunsplit(parsed)

    generation_path = f"/{'/'.join(generation_segments)}"
    return urlunsplit((parsed.scheme, parsed.netloc, generation_path, "", ""))


def _protocol_value(protocol_family: ProviderProtocolFamily | str) -> str:
    return (
        protocol_family.value
        if isinstance(protocol_family, ProviderProtocolFamily)
        else str(protocol_family)
    )
