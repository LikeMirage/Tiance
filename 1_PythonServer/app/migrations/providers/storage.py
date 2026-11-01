"""Historical provider conversion; normal provider reads use only current files."""
from __future__ import annotations
from pathlib import Path
from copy import deepcopy
from typing import Any
from uuid import uuid4
from app.core.atomic_replace import atomic_replace_path
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
from app.migrations.providers.endpoints import (
    initialize_provider_manifest_endpoints,
    migrate_provider_endpoint_storage,
    provider_endpoint_storage_version_fields,
)
from app.migrations.providers.store import MigrationProviderStore
from app.migrations.providers.legacy_database import _load_legacy_provider_data, _generic_manifest
from datetime import UTC, datetime
from app.migrations.providers.validation import _validate_rule_files
from app.migrations.providers.presets import _empty_provider_rules, _empty_model_rules
from app.migrations.providers.presets import _load_preset_manifests, _load_preset_rules

PROVIDER_PRESET_CATALOG_VERSION = 2

def upgrade_storage(providers_path: Path, database_path: Path | None) -> bool:
    settings_file = providers_path / PROVIDER_SETTINGS_FILE
    if not settings_file.is_file() and (database_path is None or not any(_load_legacy_provider_data(database_path).values())):
        return False
    if settings_file.is_file():
        now = _utc_now()
        store = MigrationProviderStore(providers_path)
        if store.read_settings(required=True).get("schemaVersion") != 1:
            raise ProviderFileStoreError("Unsupported provider settings schema; original files were retained.")
        preset_manifests = _load_preset_manifests(now)
        migrate_provider_endpoint_storage(
            store,
            preset_manifests=preset_manifests,
            updated_at=now,
        )
        _ensure_missing_preset_manifests(store, preset_manifests, now)
        _ensure_preset_rule_files(store)
        for provider_id in store.list_provider_ids():
            store.ensure_provider_sidecars(provider_id)
        _ensure_provider_rule_shapes(store)
        _validate_rule_files(store)
        return True
    if providers_path.exists() and any(providers_path.iterdir()):
        raise ProviderFileStoreError(
            "Provider data directory exists but has no provider-settings.json."
        )

    now = _utc_now()
    preset_manifests = _load_preset_manifests(now)
    provider_manifests = deepcopy(preset_manifests)
    legacy = _load_legacy_provider_data(database_path)
    provider_manifests.update(legacy["manifests"])

    for provider_id in set(legacy["models"]).union(legacy["credentials"]):
        provider_manifests.setdefault(provider_id, _generic_manifest(provider_id, now))

    for provider_id, config in legacy["configs"].items():
        manifest = provider_manifests.get(provider_id)
        if manifest is None:
            manifest = _generic_manifest(provider_id, now)
            provider_manifests[provider_id] = manifest
        urls = dict(manifest.get("generationUrls") or {})
        protocol = manifest["protocolFamily"]
        if urls.get(protocol) != config["apiBaseUrl"]:
            # The old database stored one explicit endpoint, not a separate discovery URL.
            manifest["modelDiscoveryUrl"] = None
        urls[protocol] = config["apiBaseUrl"]
        manifest["generationUrls"] = urls
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

        for provider_id in provider_manifests:
            for field, filename in (("credentials", PROVIDER_CREDENTIALS_FILE), ("models", PROVIDER_MODELS_FILE)):
                actual = store.read_provider_file(provider_id, filename, required=True)
                if actual["items"] != legacy[field].get(provider_id, []):
                    raise RuntimeError(f"Provider {field} export verification failed for {provider_id}.")

        available_ids = list(provider_manifests)
        legacy_order = [
            provider_id
            for provider_id in legacy["order"]
            if provider_id in provider_manifests
        ]
        seen = set(legacy_order)
        provider_order = legacy_order + [
            provider_id for provider_id in available_ids if provider_id not in seen
        ]
        store.write_settings(
            {
                "schemaVersion": PROVIDER_SCHEMA_VERSION,
                "initializedAt": now,
                "legacyMigrationCompletedAt": now,
                "providerPresetCatalogVersion": PROVIDER_PRESET_CATALOG_VERSION,
                **provider_endpoint_storage_version_fields(),
                "providerOrder": provider_order,
                "updatedAt": now,
            }
        )

        if providers_path.exists():
            providers_path.rmdir()
        atomic_replace_path(staging_path, providers_path)
        return True
    except Exception:
        if staging_path.exists():
            import shutil

            shutil.rmtree(staging_path, ignore_errors=True)
        raise


def _ensure_missing_preset_manifests(
    store: ProviderFileStore,
    preset_manifests: dict[str, dict[str, Any]],
    now: str,
) -> None:
    """Add newly bundled presets without overwriting existing user configuration."""
    settings = store.read_settings(required=True)
    if settings is None:  # pragma: no cover - required read cannot return None
        return
    raw_order = settings.get("providerOrder")
    provider_order = list(raw_order) if isinstance(raw_order, list) else []
    raw_catalog_version = settings.get("providerPresetCatalogVersion", 1)
    catalog_version = raw_catalog_version if isinstance(raw_catalog_version, int) else 1
    if catalog_version >= PROVIDER_PRESET_CATALOG_VERSION:
        return
    changed = False
    for provider_id in {"opencode"}:
        manifest = preset_manifests.get(provider_id)
        if manifest is None:
            continue
        if store.has_provider(provider_id):
            continue
        store.write_provider_file(provider_id, PROVIDER_MANIFEST_FILE, manifest)
        store.ensure_provider_sidecars(provider_id)
        provider_order.append(provider_id)
        changed = True
    settings["providerPresetCatalogVersion"] = PROVIDER_PRESET_CATALOG_VERSION
    settings["updatedAt"] = now
    if changed:
        settings["providerOrder"] = provider_order
    store.write_settings(settings)


def _ensure_preset_rule_files(store: ProviderFileStore) -> None:
    for provider_id, rules in _load_preset_rules().items():
        if not store.has_provider(provider_id):
            continue
        if store.read_provider_file(provider_id, PROVIDER_RULES_FILE, required=False) is None:
            store.write_provider_file(provider_id, PROVIDER_RULES_FILE, rules["providerRules"])
        if store.read_provider_file(provider_id, PROVIDER_MODEL_RULES_FILE, required=False) is None:
            store.write_provider_file(provider_id, PROVIDER_MODEL_RULES_FILE, rules["modelRules"])


def _ensure_provider_rule_shapes(store: ProviderFileStore) -> None:
    for provider_id in store.list_provider_ids():
        payload = store.read_provider_file(provider_id, PROVIDER_RULES_FILE)
        if payload is not None and "behavior" not in payload:
            payload["behavior"] = {}
            store.write_provider_file(provider_id, PROVIDER_RULES_FILE, payload)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
