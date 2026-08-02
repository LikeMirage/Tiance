from __future__ import annotations

from typing import Any

from app.domain.llm.provider_catalog import ProviderProtocolFamily
from app.domain.llm.provider_endpoint_templates import retarget_generation_url


_PROTOCOL_VALUES = frozenset(item.value for item in ProviderProtocolFamily)


def sync_preset_generation_url_defaults(
    manifest: dict[str, Any],
    *,
    preset_manifest: dict[str, Any] | None,
    updated_at: str,
) -> bool:
    if preset_manifest is None:
        return False

    generation_urls = _valid_generation_urls(manifest.get("generationUrls"))
    preset_urls = _valid_generation_urls(preset_manifest.get("generationUrls"))
    if not generation_urls or not preset_urls:
        return False

    has_preset_anchor = any(
        generation_urls.get(protocol) == preset_url
        for protocol, preset_url in preset_urls.items()
    )
    next_generation_urls = dict(generation_urls)
    for protocol, preset_url in preset_urls.items():
        current_url = generation_urls.get(protocol)
        if current_url is None:
            if has_preset_anchor:
                next_generation_urls[protocol] = preset_url
            continue
        if _is_known_preset_url_variant(
            current_url=current_url,
            target_protocol=protocol,
            generation_urls=generation_urls,
            preset_urls=preset_urls,
            preset_url=preset_url,
        ):
            next_generation_urls[protocol] = preset_url

    active_protocol = manifest.get("protocolFamily")
    for protocol, current_url in generation_urls.items():
        if protocol in preset_urls or protocol == active_protocol:
            continue
        if _is_known_generated_url(
            current_url=current_url,
            target_protocol=protocol,
            generation_urls=generation_urls,
            preset_urls=preset_urls,
        ):
            next_generation_urls.pop(protocol, None)

    if next_generation_urls == generation_urls:
        return False
    manifest["generationUrls"] = dict(sorted(next_generation_urls.items()))
    manifest["updatedAt"] = updated_at
    return True


def _is_known_preset_url_variant(
    *,
    current_url: str,
    target_protocol: str,
    generation_urls: dict[str, str],
    preset_urls: dict[str, str],
    preset_url: str,
) -> bool:
    if current_url == preset_url:
        return False

    for source_protocol, preset_source_url in preset_urls.items():
        if source_protocol == target_protocol:
            continue
        if generation_urls.get(source_protocol) != preset_source_url:
            continue
        if (
            retarget_generation_url(
                preset_source_url,
                source_protocol,
                target_protocol,
            )
            == current_url
        ):
            return True
    return False


def _is_known_generated_url(
    *,
    current_url: str,
    target_protocol: str,
    generation_urls: dict[str, str],
    preset_urls: dict[str, str],
) -> bool:
    for source_protocol, preset_source_url in preset_urls.items():
        if generation_urls.get(source_protocol) != preset_source_url:
            continue
        if (
            retarget_generation_url(
                preset_source_url,
                source_protocol,
                target_protocol,
            )
            == current_url
        ):
            return True
    return False


def _valid_generation_urls(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        protocol: generation_url.strip()
        for protocol, generation_url in value.items()
        if protocol in _PROTOCOL_VALUES
        and isinstance(generation_url, str)
        and generation_url.strip()
    }
