from pathlib import Path
import json
from typing import Any
from app.domain.llm.provider_catalog import ProviderProtocolFamily, AuthScheme
from app.repositories.llm.provider_file_store import PROVIDER_SCHEMA_VERSION, ProviderFileStore, ProviderFileStoreError


def _load_preset_rules() -> dict[str, dict[str, dict[str, Any]]]:
    resource = Path(__file__).parent.joinpath("provider_rule_presets.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    raw_providers = payload.get("providers") if isinstance(payload, dict) else None
    if not isinstance(raw_providers, dict):
        raise ProviderFileStoreError("Provider rule preset resource is invalid.")
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for provider_id, raw_rules in raw_providers.items():
        ProviderFileStore.validate_provider_id(provider_id)
        if not isinstance(raw_rules, dict):
            raise ProviderFileStoreError("Provider rule preset entry is invalid.")
        provider_rules = raw_rules.get("providerRules", _empty_provider_rules())
        model_rules = raw_rules.get("modelRules", _empty_model_rules())
        if not isinstance(provider_rules, dict) or not isinstance(model_rules, dict):
            raise ProviderFileStoreError("Provider rule preset files must be objects.")
        result[provider_id] = {
            "providerRules": provider_rules,
            "modelRules": model_rules,
        }
    return result


def _load_preset_manifests(now: str) -> dict[str, dict[str, Any]]:
    resource = Path(__file__).parent.joinpath("provider_presets.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    raw_providers = payload.get("providers") if isinstance(payload, dict) else None
    if not isinstance(raw_providers, list):
        raise ProviderFileStoreError("Provider preset resource is invalid.")
    manifests: dict[str, dict[str, Any]] = {}
    for item in raw_providers:
        if not isinstance(item, dict):
            raise ProviderFileStoreError("Provider preset entry is invalid.")
        provider_id = _required_text(item, "id")
        ProviderFileStore.validate_provider_id(provider_id)
        protocol_family = _required_text(item, "protocolFamily")
        generation_urls = _required_generation_urls(item)
        if protocol_family not in generation_urls:
            raise ProviderFileStoreError(
                f"Provider preset has no generation URL for active protocol: {provider_id}"
            )
        manifests[provider_id] = {
            "schemaVersion": PROVIDER_SCHEMA_VERSION,
            "id": provider_id,
            "displayName": _required_text(item, "displayName"),
            "profileId": _required_text(item, "profileId"),
            "protocolFamily": protocol_family,
            "generationAuthSchemes": _required_generation_auth_schemes(item),
            "modelDiscoveryStrategy": _required_text(
                item,
                "modelDiscoveryStrategy",
            ),
            "modelDiscoveryAuthScheme": _required_text(
                item,
                "modelDiscoveryAuthScheme",
            ),
            "generationUrls": generation_urls,
            "modelDiscoveryUrl": _optional_text(item, "modelDiscoveryUrl"),
            "enabled": False,
            "reasoningReplayMode": "tool_call_rounds",
            "createdAt": now,
            "updatedAt": now,
        }
    return manifests


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProviderFileStoreError(f"Provider preset field is required: {key}")
    return value.strip()


def _optional_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _required_generation_urls(payload: dict[str, Any]) -> dict[str, str]:
    raw_generation_urls = payload.get("generationUrls")
    if not isinstance(raw_generation_urls, dict):
        raise ProviderFileStoreError("Provider preset generationUrls must be an object.")
    generation_urls = {
        protocol: generation_url.strip()
        for protocol, generation_url in raw_generation_urls.items()
        if protocol in {item.value for item in ProviderProtocolFamily}
        and isinstance(generation_url, str)
        and generation_url.strip()
    }
    if not generation_urls:
        raise ProviderFileStoreError("Provider preset generationUrls is empty.")
    return generation_urls


def _required_generation_auth_schemes(payload: dict[str, Any]) -> dict[str, str]:
    raw_value = payload.get("generationAuthSchemes")
    if not isinstance(raw_value, dict):
        raise ProviderFileStoreError(
            "Provider preset generationAuthSchemes must be an object."
        )
    auth_schemes = {
        protocol: auth_scheme
        for protocol, auth_scheme in raw_value.items()
        if protocol in {item.value for item in ProviderProtocolFamily}
        and isinstance(auth_scheme, str)
        and auth_scheme in {item.value for item in AuthScheme}
    }
    if not auth_schemes:
        raise ProviderFileStoreError(
            "Provider preset generationAuthSchemes is empty."
        )
    return auth_schemes


def _empty_provider_rules() -> dict[str, Any]:
    return {
        "schemaVersion": PROVIDER_SCHEMA_VERSION,
        "capabilities": {},
        "request": {},
        "behavior": {},
    }

def _empty_model_rules() -> dict[str, Any]:
    return {"schemaVersion": PROVIDER_SCHEMA_VERSION, "families": {}, "models": {}}
