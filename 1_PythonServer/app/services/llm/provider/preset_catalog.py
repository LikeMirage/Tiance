from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
import json

from app.domain.llm.provider_catalog import (
    AuthScheme,
    ModelDiscoveryStrategy,
    ProviderProtocolFamily,
)
from app.repositories.llm.provider_file_store import ProviderFileStoreError


@dataclass(frozen=True, slots=True)
class ProviderEndpointPreset:
    generation_urls: Mapping[ProviderProtocolFamily, str]
    generation_auth_schemes: Mapping[ProviderProtocolFamily, AuthScheme]
    model_discovery_strategy: ModelDiscoveryStrategy
    model_discovery_auth_scheme: AuthScheme
    model_discovery_url: str | None


@lru_cache
def load_provider_endpoint_presets() -> Mapping[str, ProviderEndpointPreset]:
    resource = files("app.resources").joinpath("provider_presets.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    raw_providers = payload.get("providers") if isinstance(payload, dict) else None
    if not isinstance(raw_providers, list):
        raise ProviderFileStoreError("Provider preset resource is invalid.")

    presets: dict[str, ProviderEndpointPreset] = {}
    for item in raw_providers:
        if not isinstance(item, dict):
            raise ProviderFileStoreError("Provider preset entry is invalid.")
        provider_id = _required_text(item, "id")
        raw_generation_urls = item.get("generationUrls")
        if not isinstance(raw_generation_urls, dict):
            raise ProviderFileStoreError(
                f"Provider preset generation URLs are invalid: {provider_id}"
            )
        generation_urls = {
            ProviderProtocolFamily(str(protocol)): generation_url.strip()
            for protocol, generation_url in raw_generation_urls.items()
            if isinstance(generation_url, str) and generation_url.strip()
        }
        if not generation_urls:
            raise ProviderFileStoreError(
                f"Provider preset has no generation URL: {provider_id}"
            )
        presets[provider_id] = ProviderEndpointPreset(
            generation_urls=generation_urls,
            generation_auth_schemes=_required_generation_auth_schemes(
                item,
                provider_id=provider_id,
            ),
            model_discovery_strategy=ModelDiscoveryStrategy(
                _required_text(item, "modelDiscoveryStrategy")
            ),
            model_discovery_auth_scheme=AuthScheme(
                _required_text(item, "modelDiscoveryAuthScheme")
            ),
            model_discovery_url=_optional_text(item, "modelDiscoveryUrl"),
        )
    return presets


def get_provider_endpoint_preset(provider_id: str) -> ProviderEndpointPreset | None:
    return load_provider_endpoint_presets().get(provider_id)


def _required_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProviderFileStoreError(f"Provider preset field is invalid: {key}")
    return value.strip()


def _optional_text(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProviderFileStoreError(f"Provider preset field is invalid: {key}")
    normalized = value.strip()
    return normalized or None


def _required_generation_auth_schemes(
    payload: dict[str, object],
    *,
    provider_id: str,
) -> dict[ProviderProtocolFamily, AuthScheme]:
    raw_value = payload.get("generationAuthSchemes")
    if not isinstance(raw_value, dict):
        raise ProviderFileStoreError(
            f"Provider preset generation auth schemes are invalid: {provider_id}"
        )
    return {
        ProviderProtocolFamily(str(protocol)): AuthScheme(str(auth_scheme))
        for protocol, auth_scheme in raw_value.items()
    }
