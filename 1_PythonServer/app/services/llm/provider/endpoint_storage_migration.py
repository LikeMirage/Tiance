from __future__ import annotations

from typing import Any

from app.domain.llm.provider_catalog import (
    AuthScheme,
    ModelDiscoveryStrategy,
    ProviderProtocolFamily,
    default_generation_auth_scheme,
    default_model_discovery_auth_scheme,
    default_model_discovery_strategy,
)
from app.domain.llm.provider_endpoint_templates import (
    derive_model_discovery_url,
)
from app.repositories.llm.provider_file_store import (
    PROVIDER_MANIFEST_FILE,
    PROVIDER_SCHEMA_VERSION,
    ProviderFileStore,
)
from app.services.llm.provider.preset_endpoint_defaults import (
    sync_preset_generation_url_defaults,
)


_MODEL_DISCOVERY_URL_AUTOFILL_VERSION = 1
_MODEL_DISCOVERY_URL_AUTOFILL_VERSION_KEY = "modelDiscoveryUrlAutofillVersion"
_GENERATION_URL_STORAGE_VERSION = 1
_GENERATION_URL_STORAGE_VERSION_KEY = "generationUrlStorageVersion"
_PRESET_GENERATION_URL_DEFAULTS_VERSION = 2
_PRESET_GENERATION_URL_DEFAULTS_VERSION_KEY = "presetGenerationUrlDefaultsVersion"
_MODEL_DISCOVERY_STRATEGY_VERSION = 1
_MODEL_DISCOVERY_STRATEGY_VERSION_KEY = "modelDiscoveryStrategyVersion"
_PROVIDER_AUTH_CONTRACT_VERSION = 1
_PROVIDER_AUTH_CONTRACT_VERSION_KEY = "providerAuthContractVersion"
_PROTOCOL_VALUES = frozenset(item.value for item in ProviderProtocolFamily)


def provider_endpoint_storage_version_fields() -> dict[str, int]:
    return {
        _MODEL_DISCOVERY_URL_AUTOFILL_VERSION_KEY: (
            _MODEL_DISCOVERY_URL_AUTOFILL_VERSION
        ),
        _GENERATION_URL_STORAGE_VERSION_KEY: _GENERATION_URL_STORAGE_VERSION,
        _PRESET_GENERATION_URL_DEFAULTS_VERSION_KEY: (
            _PRESET_GENERATION_URL_DEFAULTS_VERSION
        ),
        _MODEL_DISCOVERY_STRATEGY_VERSION_KEY: _MODEL_DISCOVERY_STRATEGY_VERSION,
        _PROVIDER_AUTH_CONTRACT_VERSION_KEY: _PROVIDER_AUTH_CONTRACT_VERSION,
    }


def initialize_provider_manifest_endpoints(
    manifest: dict[str, Any],
    *,
    preset_manifest: dict[str, Any] | None,
    updated_at: str,
) -> None:
    _migrate_generation_url_storage(manifest, updated_at=updated_at)
    _fill_model_discovery_url(manifest, updated_at=updated_at)
    _fill_model_discovery_strategy(
        manifest,
        preset_manifest=preset_manifest,
        updated_at=updated_at,
    )
    _migrate_auth_contract(
        manifest,
        preset_manifest=preset_manifest,
        updated_at=updated_at,
    )


def migrate_provider_endpoint_storage(
    store: ProviderFileStore,
    *,
    preset_manifests: dict[str, dict[str, Any]],
    updated_at: str,
) -> None:
    settings = store.read_settings(required=False) or {}
    model_urls_current = _version_is_current(
        settings,
        _MODEL_DISCOVERY_URL_AUTOFILL_VERSION_KEY,
        _MODEL_DISCOVERY_URL_AUTOFILL_VERSION,
    )
    generation_url_storage_current = _version_is_current(
        settings,
        _GENERATION_URL_STORAGE_VERSION_KEY,
        _GENERATION_URL_STORAGE_VERSION,
    )
    preset_generation_url_defaults_current = _version_is_current(
        settings,
        _PRESET_GENERATION_URL_DEFAULTS_VERSION_KEY,
        _PRESET_GENERATION_URL_DEFAULTS_VERSION,
    )
    model_discovery_strategy_current = _version_is_current(
        settings,
        _MODEL_DISCOVERY_STRATEGY_VERSION_KEY,
        _MODEL_DISCOVERY_STRATEGY_VERSION,
    )
    auth_contract_current = _version_is_current(
        settings,
        _PROVIDER_AUTH_CONTRACT_VERSION_KEY,
        _PROVIDER_AUTH_CONTRACT_VERSION,
    )
    all_versions_current = (
        model_urls_current
        and generation_url_storage_current
        and preset_generation_url_defaults_current
        and model_discovery_strategy_current
        and auth_contract_current
    )

    for provider_id in store.list_provider_ids():
        manifest = store.read_provider_file(provider_id, PROVIDER_MANIFEST_FILE)
        if manifest is None:
            continue
        changed = False
        if not generation_url_storage_current:
            changed = _migrate_generation_url_storage(
                manifest,
                updated_at=updated_at,
            ) or changed
        if not preset_generation_url_defaults_current:
            changed = sync_preset_generation_url_defaults(
                manifest,
                preset_manifest=preset_manifests.get(provider_id),
                updated_at=updated_at,
            ) or changed
        if not model_urls_current:
            changed = _fill_model_discovery_url(
                manifest,
                updated_at=updated_at,
            ) or changed
        changed = _fill_model_discovery_strategy(
            manifest,
            preset_manifest=preset_manifests.get(provider_id),
            updated_at=updated_at,
        ) or changed
        changed = _migrate_auth_contract(
            manifest,
            preset_manifest=preset_manifests.get(provider_id),
            updated_at=updated_at,
        ) or changed
        if changed:
            store.write_provider_file(provider_id, PROVIDER_MANIFEST_FILE, manifest)

    if all_versions_current:
        return

    settings.update(
        {
            "schemaVersion": PROVIDER_SCHEMA_VERSION,
            **provider_endpoint_storage_version_fields(),
            "updatedAt": updated_at,
        }
    )
    store.write_settings(settings)


def _migrate_generation_url_storage(
    manifest: dict[str, Any],
    *,
    updated_at: str,
) -> bool:
    protocol_family = _optional_text(manifest, "protocolFamily")
    if protocol_family is None:
        return False

    raw_generation_urls = manifest.get("generationUrls")
    generation_urls = {
        protocol: generation_url.strip()
        for protocol, generation_url in (
            raw_generation_urls.items()
            if isinstance(raw_generation_urls, dict)
            else ()
        )
        if protocol in _PROTOCOL_VALUES
        and isinstance(generation_url, str)
        and generation_url.strip()
    }
    legacy_api_base_url = _optional_text(manifest, "apiBaseUrl")
    if legacy_api_base_url is not None:
        generation_urls[protocol_family] = legacy_api_base_url
    if not generation_urls:
        return False

    next_generation_urls = dict(sorted(generation_urls.items()))
    changed = raw_generation_urls != next_generation_urls or "apiBaseUrl" in manifest
    if not changed:
        return False

    manifest["generationUrls"] = next_generation_urls
    manifest.pop("apiBaseUrl", None)
    manifest["updatedAt"] = updated_at
    return True


def _fill_model_discovery_url(
    manifest: dict[str, Any],
    *,
    updated_at: str,
) -> bool:
    if _optional_text(manifest, "modelDiscoveryUrl") is not None:
        return False

    api_base_url = _active_generation_url(manifest)
    protocol_family = _optional_text(manifest, "protocolFamily")
    if api_base_url is None or protocol_family is None:
        return False

    model_discovery_url = derive_model_discovery_url(api_base_url, protocol_family)
    if model_discovery_url is None:
        return False

    manifest["modelDiscoveryUrl"] = model_discovery_url
    manifest["updatedAt"] = updated_at
    return True


def _fill_model_discovery_strategy(
    manifest: dict[str, Any],
    *,
    preset_manifest: dict[str, Any] | None,
    updated_at: str,
) -> bool:
    current_strategy = _optional_text(manifest, "modelDiscoveryStrategy")
    if current_strategy is not None:
        ModelDiscoveryStrategy(current_strategy)
        return False

    preset_strategy = (
        _optional_text(preset_manifest, "modelDiscoveryStrategy")
        if preset_manifest is not None
        else None
    )
    if preset_strategy is not None:
        strategy = ModelDiscoveryStrategy(preset_strategy)
    else:
        protocol_family = _optional_text(manifest, "protocolFamily")
        if protocol_family is None:
            return False
        strategy = default_model_discovery_strategy(
            ProviderProtocolFamily(protocol_family)
        )

    manifest["modelDiscoveryStrategy"] = strategy.value
    manifest["updatedAt"] = updated_at
    return True


def _active_generation_url(manifest: dict[str, Any]) -> str | None:
    protocol_family = _optional_text(manifest, "protocolFamily")
    raw_generation_urls = manifest.get("generationUrls")
    if protocol_family is not None and isinstance(raw_generation_urls, dict):
        generation_url = raw_generation_urls.get(protocol_family)
        if isinstance(generation_url, str) and generation_url.strip():
            return generation_url.strip()
    return _optional_text(manifest, "apiBaseUrl")


def _migrate_auth_contract(
    manifest: dict[str, Any],
    *,
    preset_manifest: dict[str, Any] | None,
    updated_at: str,
) -> bool:
    protocol_value = _optional_text(manifest, "protocolFamily")
    if protocol_value is None:
        return False
    active_protocol = ProviderProtocolFamily(protocol_value)
    legacy_auth = _optional_text(manifest, "authScheme")

    raw_auth_schemes = manifest.get("generationAuthSchemes")
    had_auth_map = isinstance(raw_auth_schemes, dict)
    auth_schemes = {
        protocol: auth_scheme
        for protocol, auth_scheme in (
            raw_auth_schemes.items() if isinstance(raw_auth_schemes, dict) else ()
        )
        if protocol in _PROTOCOL_VALUES
        and isinstance(auth_scheme, str)
        and auth_scheme in {item.value for item in AuthScheme}
    }
    raw_urls = manifest.get("generationUrls")
    if isinstance(raw_urls, dict):
        for protocol in raw_urls:
            if protocol not in _PROTOCOL_VALUES or protocol in auth_schemes:
                continue
            auth_schemes[protocol] = default_generation_auth_scheme(
                ProviderProtocolFamily(protocol)
            ).value
    if legacy_auth in {item.value for item in AuthScheme}:
        auth_schemes.setdefault(active_protocol.value, legacy_auth)
    else:
        auth_schemes.setdefault(
            active_protocol.value,
            default_generation_auth_scheme(active_protocol).value,
        )

    preset_auth_schemes = (
        preset_manifest.get("generationAuthSchemes")
        if isinstance(preset_manifest, dict)
        else None
    )
    if isinstance(preset_auth_schemes, dict):
        valid_preset_auth_schemes = {
            protocol: auth_scheme
            for protocol, auth_scheme in preset_auth_schemes.items()
            if protocol in _PROTOCOL_VALUES
            and isinstance(auth_scheme, str)
            and auth_scheme in {item.value for item in AuthScheme}
        }
        if had_auth_map:
            for protocol, auth_scheme in valid_preset_auth_schemes.items():
                auth_schemes.setdefault(protocol, auth_scheme)
        else:
            auth_schemes.update(valid_preset_auth_schemes)

    preset_model_auth = (
        _optional_text(preset_manifest, "modelDiscoveryAuthScheme")
        if preset_manifest is not None
        else None
    )
    model_auth = _optional_text(manifest, "modelDiscoveryAuthScheme")
    if model_auth is None and preset_model_auth is not None:
        model_auth = preset_model_auth
    if model_auth is None:
        strategy = ModelDiscoveryStrategy(
            _optional_text(manifest, "modelDiscoveryStrategy")
            or default_model_discovery_strategy(active_protocol).value
        )
        model_auth = default_model_discovery_auth_scheme(strategy).value

    next_auth_schemes = dict(sorted(auth_schemes.items()))
    changed = (
        raw_auth_schemes != next_auth_schemes
        or manifest.get("modelDiscoveryAuthScheme") != model_auth
        or "authScheme" in manifest
    )
    if changed:
        manifest["generationAuthSchemes"] = next_auth_schemes
        manifest["modelDiscoveryAuthScheme"] = model_auth
        manifest.pop("authScheme", None)
        manifest["updatedAt"] = updated_at
    return changed


def _version_is_current(
    settings: dict[str, Any],
    key: str,
    target_version: int,
) -> bool:
    current_version = settings.get(key)
    return isinstance(current_version, int) and current_version >= target_version


def _optional_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None
