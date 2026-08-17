from collections.abc import Sequence
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from app.domain.llm.provider_catalog import (
    AuthScheme,
    ModelDiscoveryStrategy,
    ProviderCatalogEntry,
    ProviderProtocolFamily,
)
from app.domain.llm.provider_endpoint_templates import (
    build_provider_endpoint_template,
    normalize_generation_urls,
)
from app.repositories.llm.provider_file_store import (
    PROVIDER_MANIFEST_FILE,
    PROVIDER_SCHEMA_VERSION,
    ProviderFileStore,
    ProviderFileStoreError,
    get_provider_file_store,
)


class ProviderCatalogRepository:
    def __init__(self, store: ProviderFileStore) -> None:
        self._store = store

    def list_entries(self) -> Sequence[ProviderCatalogEntry]:
        return tuple(self._load_entry(provider_id) for provider_id in self._store.list_provider_ids())

    def get_entry(self, provider_id: str) -> ProviderCatalogEntry | None:
        if not self._store.has_provider(provider_id):
            return None
        return self._load_entry(provider_id)

    def save_entry(self, entry: ProviderCatalogEntry, *, updated_at: str) -> ProviderCatalogEntry:
        existing = self._store.read_provider_file(
            entry.provider_id,
            PROVIDER_MANIFEST_FILE,
            required=False,
        )
        created_at = entry.created_at or _read_text(existing, "createdAt") or updated_at
        generation_urls = {
            protocol: url
            for protocol, url in entry.endpoints.generation_urls.items()
            if url.strip()
        }
        payload = {
            "schemaVersion": PROVIDER_SCHEMA_VERSION,
            "id": entry.provider_id,
            "displayName": entry.display_name,
            "profileId": entry.profile_id,
            "protocolFamily": entry.protocol_family.value,
            "generationAuthSchemes": {
                protocol.value: auth_scheme.value
                for protocol, auth_scheme in entry.generation_auth_schemes.items()
            },
            "modelDiscoveryStrategy": entry.model_discovery_strategy.value,
            "modelDiscoveryAuthScheme": entry.model_discovery_auth_scheme.value,
            "generationUrls": {
                protocol.value: generation_url
                for protocol, generation_url in generation_urls.items()
            },
            "modelDiscoveryUrl": entry.endpoints.model_discovery_url,
            "enabled": (
                bool(existing.get("enabled", False))
                and bool(entry.endpoints.api_base_url.strip())
                if existing
                else False
            ),
            "reasoningReplayMode": (
                _read_text(existing, "reasoningReplayMode")
                if existing
                else "tool_call_rounds"
            ),
            "createdAt": created_at,
            "updatedAt": updated_at,
        }
        is_new = existing is None
        self._store.write_provider_file(entry.provider_id, PROVIDER_MANIFEST_FILE, payload)
        self._store.ensure_provider_sidecars(entry.provider_id)
        if is_new:
            self._append_provider_order(entry.provider_id, updated_at=updated_at)
        return self._load_entry(entry.provider_id)

    def list_ordered_provider_ids(self) -> tuple[str, ...]:
        available_ids = self._store.list_provider_ids()
        settings = self._store.read_settings(required=False) or {}
        raw_order = settings.get("providerOrder")
        stored_order = raw_order if isinstance(raw_order, list) else []
        available_set = set(available_ids)
        ordered_ids = [
            item
            for item in stored_order
            if isinstance(item, str) and item in available_set
        ]
        seen = set(ordered_ids)
        ordered_ids.extend(provider_id for provider_id in available_ids if provider_id not in seen)
        return tuple(ordered_ids)

    def replace_provider_order(
        self,
        provider_ids: Sequence[str],
        *,
        updated_at: str,
    ) -> tuple[str, ...]:
        settings = self._store.read_settings(required=False) or {}
        settings.update(
            {
                "schemaVersion": PROVIDER_SCHEMA_VERSION,
                "providerOrder": list(provider_ids),
                "updatedAt": updated_at,
            }
        )
        self._store.write_settings(settings)
        return tuple(provider_ids)

    def delete_entry(self, provider_id: str) -> bool:
        deleted = self._store.delete_provider(provider_id)
        if not deleted:
            return False
        self.replace_provider_order(
            tuple(item for item in self.list_ordered_provider_ids() if item != provider_id),
            updated_at=_utc_now(),
        )
        return True

    def _load_entry(self, provider_id: str) -> ProviderCatalogEntry:
        payload = self._store.read_provider_file(provider_id, PROVIDER_MANIFEST_FILE)
        if payload is None:
            raise ProviderFileStoreError(f"Provider manifest not found: {provider_id}")
        manifest_id = _required_text(payload, "id")
        if manifest_id != provider_id:
            raise ProviderFileStoreError(
                f"Provider id does not match directory name: {manifest_id} != {provider_id}"
            )
        protocol_family = ProviderProtocolFamily(_required_text(payload, "protocolFamily"))
        generation_urls = normalize_generation_urls(
            payload.get("generationUrls")
            if isinstance(payload.get("generationUrls"), dict)
            else {}
        )
        api_base_url = generation_urls.get(protocol_family, "")
        raw_generation_auth_schemes = payload.get("generationAuthSchemes")
        if not isinstance(raw_generation_auth_schemes, dict):
            raise ProviderFileStoreError("Provider generation auth schemes must be an object.")
        generation_auth_schemes = {
            ProviderProtocolFamily(str(protocol)): AuthScheme(str(auth_scheme))
            for protocol, auth_scheme in raw_generation_auth_schemes.items()
        }
        return ProviderCatalogEntry(
            provider_id=provider_id,
            display_name=_required_text(payload, "displayName"),
            profile_id=_required_text(payload, "profileId"),
            protocol_family=protocol_family,
            generation_auth_schemes=generation_auth_schemes,
            model_discovery_strategy=ModelDiscoveryStrategy(
                _required_text(payload, "modelDiscoveryStrategy")
            ),
            model_discovery_auth_scheme=AuthScheme(
                _required_text(payload, "modelDiscoveryAuthScheme")
            ),
            endpoints=build_provider_endpoint_template(
                api_base_url=api_base_url,
                model_discovery_url=_read_text(payload, "modelDiscoveryUrl"),
                generation_urls=generation_urls,
            ),
            created_at=_read_text(payload, "createdAt"),
        )

    def _append_provider_order(self, provider_id: str, *, updated_at: str) -> None:
        current_order = list(self.list_ordered_provider_ids())
        if provider_id not in current_order:
            current_order.append(provider_id)
        self.replace_provider_order(current_order, updated_at=updated_at)


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = _read_text(payload, key)
    if value is None:
        raise ProviderFileStoreError(f"Provider manifest field is required: {key}")
    return value


def _read_text(payload: dict[str, Any] | None, key: str) -> str | None:
    if payload is None:
        return None
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@lru_cache
def get_provider_catalog_repository() -> ProviderCatalogRepository:
    return ProviderCatalogRepository(get_provider_file_store())
