from __future__ import annotations

from typing import Any

from app.domain.llm.provider_catalog import ProviderProtocolFamily


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
        if protocol not in generation_urls and has_preset_anchor:
            next_generation_urls[protocol] = preset_url

    if next_generation_urls == generation_urls:
        return False
    manifest["generationUrls"] = dict(sorted(next_generation_urls.items()))
    manifest["updatedAt"] = updated_at
    return True


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
