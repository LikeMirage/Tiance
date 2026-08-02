from __future__ import annotations

from datetime import UTC, datetime
from importlib.resources import files
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.domain.llm.provider_catalog import (
    AuthScheme,
    ProviderProtocolFamily,
    default_generation_auth_scheme,
    default_model_discovery_auth_scheme,
    default_model_discovery_strategy,
)
from app.repositories.llm.provider_file_store import (
    PROVIDER_CLOUD_CACHE_FILE,
    PROVIDER_CREDENTIALS_FILE,
    PROVIDER_MANIFEST_FILE,
    PROVIDER_MODEL_RULES_FILE,
    PROVIDER_MODELS_FILE,
    PROVIDER_RULES_FILE,
    PROVIDER_SCHEMA_VERSION,
    PROVIDER_SETTINGS_FILE,
    ProviderFileStore,
    ProviderFileStoreError,
)
from app.repositories.llm.provider_adaptation_rules_repository import (
    ProviderAdaptationRulesRepository,
)
from app.services.llm.provider.endpoint_storage_migration import (
    initialize_provider_manifest_endpoints,
    migrate_provider_endpoint_storage,
    provider_endpoint_storage_version_fields,
)


def ensure_provider_file_storage(providers_path: Path, database_path: Path) -> None:
    settings_file = providers_path / PROVIDER_SETTINGS_FILE
    if settings_file.is_file():
        now = _utc_now()
        store = ProviderFileStore(providers_path)
        migrate_provider_endpoint_storage(
            store,
            preset_manifests=_load_preset_manifests(now),
            updated_at=now,
        )
        _ensure_preset_rule_files(store)
        for provider_id in store.list_provider_ids():
            store.ensure_provider_sidecars(provider_id)
        _ensure_provider_rule_shapes(store)
        _validate_rule_files(store)
        return
    if providers_path.exists() and any(providers_path.iterdir()):
        raise ProviderFileStoreError(
            "Provider data directory exists but has no provider-settings.json."
        )

    now = _utc_now()
    preset_manifests = _load_preset_manifests(now)
    provider_manifests = dict(preset_manifests)
    legacy = _load_legacy_provider_data(database_path)
    provider_manifests.update(legacy["manifests"])

    for provider_id in set(legacy["models"]).union(legacy["credentials"]):
        provider_manifests.setdefault(provider_id, _generic_manifest(provider_id, now))

    for provider_id, config in legacy["configs"].items():
        manifest = provider_manifests.get(provider_id)
        if manifest is None:
            manifest = _generic_manifest(provider_id, now)
            provider_manifests[provider_id] = manifest
        manifest.update(
            {
                "apiBaseUrl": config["apiBaseUrl"],
                "enabled": config["enabled"],
                "createdAt": config["createdAt"],
                "updatedAt": config["updatedAt"],
            }
        )

    for provider_id, manifest in provider_manifests.items():
        initialize_provider_manifest_endpoints(
            manifest,
            preset_manifest=preset_manifests.get(provider_id),
            updated_at=now,
        )

    staging_path = providers_path.with_name(
        f".{providers_path.name}.initializing-{uuid4().hex}"
    )
    store = ProviderFileStore(staging_path)
    preset_rules = _load_preset_rules()
    try:
        for provider_id, manifest in provider_manifests.items():
            store.write_provider_file(provider_id, PROVIDER_MANIFEST_FILE, manifest)
            store.write_provider_file(
                provider_id,
                PROVIDER_CREDENTIALS_FILE,
                {
                    "schemaVersion": PROVIDER_SCHEMA_VERSION,
                    "items": legacy["credentials"].get(provider_id, []),
                },
            )
            store.write_provider_file(
                provider_id,
                PROVIDER_MODELS_FILE,
                {
                    "schemaVersion": PROVIDER_SCHEMA_VERSION,
                    "items": legacy["models"].get(provider_id, []),
                },
            )
            store.write_provider_file(
                provider_id,
                PROVIDER_CLOUD_CACHE_FILE,
                {"schemaVersion": PROVIDER_SCHEMA_VERSION, "cache": None},
            )
            provider_rules = preset_rules.get(provider_id, {})
            store.write_provider_file(
                provider_id,
                PROVIDER_RULES_FILE,
                provider_rules.get("providerRules", _empty_provider_rules()),
            )
            store.write_provider_file(
                provider_id,
                PROVIDER_MODEL_RULES_FILE,
                provider_rules.get("modelRules", _empty_model_rules()),
            )

        _validate_rule_files(store)

        available_ids = list(provider_manifests)
        legacy_order = [
            provider_id
            for provider_id in legacy["order"]
            if provider_id in provider_manifests
        ]
        legacy_order = _remove_legacy_deepseek_pin(
            legacy_order,
            list(_load_preset_manifests(now)),
        )
        seen = set(legacy_order)
        provider_order = legacy_order + [
            provider_id for provider_id in available_ids if provider_id not in seen
        ]
        store.write_settings(
            {
                "schemaVersion": PROVIDER_SCHEMA_VERSION,
                "initializedAt": now,
                "legacyMigrationCompletedAt": now,
                **provider_endpoint_storage_version_fields(),
                "providerOrder": provider_order,
                "updatedAt": now,
            }
        )

        if providers_path.exists():
            providers_path.rmdir()
        atomic_replace_path(staging_path, providers_path)
    except Exception:
        if staging_path.exists():
            import shutil

            shutil.rmtree(staging_path, ignore_errors=True)
        raise


def _ensure_preset_rule_files(store: ProviderFileStore) -> None:
    for provider_id, rules in _load_preset_rules().items():
        if not store.has_provider(provider_id):
            continue
        if store.read_provider_file(provider_id, PROVIDER_RULES_FILE, required=False) is None:
            store.write_provider_file(provider_id, PROVIDER_RULES_FILE, rules["providerRules"])
        if store.read_provider_file(provider_id, PROVIDER_MODEL_RULES_FILE, required=False) is None:
            store.write_provider_file(provider_id, PROVIDER_MODEL_RULES_FILE, rules["modelRules"])


def _validate_rule_files(store: ProviderFileStore) -> None:
    repository = ProviderAdaptationRulesRepository(store)
    for provider_id in store.list_provider_ids():
        manifest = store.read_provider_file(provider_id, PROVIDER_MANIFEST_FILE) or {}
        profile_id = manifest.get("profileId")
        if not isinstance(profile_id, str) or not profile_id:
            raise ProviderFileStoreError(f"Provider profileId is missing: {provider_id}")
        repository.resolve(
            provider_id=provider_id,
            model_id=None,
            expected_profile_id=profile_id,
        )


def _ensure_provider_rule_shapes(store: ProviderFileStore) -> None:
    for provider_id in store.list_provider_ids():
        payload = store.read_provider_file(provider_id, PROVIDER_RULES_FILE)
        if payload is not None and "behavior" not in payload:
            payload["behavior"] = {}
            store.write_provider_file(provider_id, PROVIDER_RULES_FILE, payload)


def _load_preset_rules() -> dict[str, dict[str, dict[str, Any]]]:
    resource = files("app.resources").joinpath("provider_rule_presets.json")
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


def _empty_provider_rules() -> dict[str, Any]:
    return {
        "schemaVersion": PROVIDER_SCHEMA_VERSION,
        "capabilities": {},
        "request": {},
        "behavior": {},
    }


def _empty_model_rules() -> dict[str, Any]:
    return {"schemaVersion": PROVIDER_SCHEMA_VERSION, "families": {}, "models": {}}


def _load_preset_manifests(now: str) -> dict[str, dict[str, Any]]:
    resource = files("app.resources").joinpath("provider_presets.json")
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
            "createdAt": now,
            "updatedAt": now,
        }
    return manifests


def _load_legacy_provider_data(database_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "manifests": {},
        "configs": {},
        "credentials": {},
        "models": {},
        "order": [],
    }
    if not database_path.is_file():
        return result

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if "custom_provider_catalog" in tables:
            for row in connection.execute("SELECT * FROM custom_provider_catalog").fetchall():
                provider_id = str(row["provider_id"])
                protocol_family = ProviderProtocolFamily(str(row["protocol_family"]))
                result["manifests"][provider_id] = {
                    "schemaVersion": PROVIDER_SCHEMA_VERSION,
                    "id": provider_id,
                    "displayName": str(row["display_name"]),
                    "profileId": _legacy_profile_id(str(row["upstream_key"])),
                    "protocolFamily": protocol_family.value,
                    "generationAuthSchemes": {
                        protocol_family.value: str(row["auth_scheme"])
                    },
                    "modelDiscoveryStrategy": default_model_discovery_strategy(
                        protocol_family
                    ).value,
                    "modelDiscoveryAuthScheme": default_model_discovery_auth_scheme(
                        default_model_discovery_strategy(protocol_family)
                    ).value,
                    "apiBaseUrl": str(row["api_base_url"]),
                    "modelDiscoveryUrl": None,
                    "enabled": False,
                    "createdAt": str(row["created_at"]),
                    "updatedAt": str(row["updated_at"]),
                }
        if "provider_configs" in tables:
            for row in connection.execute("SELECT * FROM provider_configs").fetchall():
                result["configs"][str(row["provider_id"])] = {
                    "apiBaseUrl": str(row["api_base_url"]),
                    "enabled": bool(row["enabled"]),
                    "createdAt": str(row["created_at"]),
                    "updatedAt": str(row["updated_at"]),
                }
        if "provider_config_api_keys" in tables:
            for row in connection.execute(
                "SELECT * FROM provider_config_api_keys ORDER BY provider_id, sort_order, created_at"
            ).fetchall():
                provider_id = str(row["provider_id"])
                result["credentials"].setdefault(provider_id, []).append(
                    {
                        "keyId": str(row["key_id"]),
                        "hint": row["api_key_hint"],
                        "ciphertext": row["api_key_ciphertext"],
                        "pollWeight": int(row["poll_weight"]),
                        "sortOrder": int(row["sort_order"]),
                        "createdAt": str(row["created_at"]),
                        "updatedAt": str(row["updated_at"]),
                    }
                )
        if "provider_custom_models" in tables:
            for row in connection.execute(
                "SELECT * FROM provider_custom_models ORDER BY provider_id, created_at, model_id"
            ).fetchall():
                provider_id = str(row["provider_id"])
                result["models"].setdefault(provider_id, []).append(
                    {
                        "modelId": str(row["model_id"]),
                        "displayName": str(row["display_name"]),
                        "familyGroup": str(row["family_group"]),
                        "capabilityTags": _load_json_list(row["capability_tags"]),
                        "note": str(row["note"]),
                        "priceCurrency": str(row["price_currency"]),
                        "inputPricePerMillion": row["input_price_per_million"],
                        "cacheHitPricePerMillion": row["cache_hit_price_per_million"],
                        "outputPricePerMillion": row["output_price_per_million"],
                        "createdAt": str(row["created_at"]),
                        "updatedAt": str(row["updated_at"]),
                    }
                )
        if "provider_catalog_order" in tables:
            result["order"] = [
                str(row["provider_id"])
                for row in connection.execute(
                    "SELECT provider_id FROM provider_catalog_order ORDER BY sort_order"
                ).fetchall()
            ]
    return result


def _generic_manifest(provider_id: str, now: str) -> dict[str, Any]:
    return {
        "schemaVersion": PROVIDER_SCHEMA_VERSION,
        "id": provider_id,
        "displayName": provider_id,
        "profileId": "generic",
        "protocolFamily": "openai_compatible",
        "generationAuthSchemes": {"openai_compatible": "bearer_token"},
        "modelDiscoveryStrategy": "openai_models",
        "modelDiscoveryAuthScheme": "bearer_token",
        "generationUrls": {
            ProviderProtocolFamily.OPENAI_COMPATIBLE.value: (
                "https://example.invalid/v1/chat/completions"
            )
        },
        "modelDiscoveryUrl": None,
        "enabled": False,
        "createdAt": now,
        "updatedAt": now,
    }


def _legacy_profile_id(upstream_key: str) -> str:
    if upstream_key == "deepseek":
        return "deepseek"
    if upstream_key == "doubao":
        return "volcengine"
    return "generic"


def _remove_legacy_deepseek_pin(
    legacy_order: list[str],
    preset_order: list[str],
) -> list[str]:
    if not legacy_order or legacy_order[0] != "deepseek":
        return legacy_order
    next_order = [provider_id for provider_id in legacy_order if provider_id != "deepseek"]
    preceding_presets = preset_order[:preset_order.index("deepseek")]
    insertion_index = max(
        (next_order.index(provider_id) + 1 for provider_id in preceding_presets if provider_id in next_order),
        default=0,
    )
    next_order.insert(insertion_index, "deepseek")
    return next_order


def _load_json_list(value: object) -> list[str]:
    try:
        loaded = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return [item for item in loaded if isinstance(item, str)] if isinstance(loaded, list) else []


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


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
