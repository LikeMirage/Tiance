from functools import lru_cache
from typing import Any

from app.domain.llm.provider_cloud_model import ProviderCloudModelCache
from app.domain.llm.discovered_model import DiscoveredModel
from app.repositories.llm.provider_file_store import (
    PROVIDER_CLOUD_CACHE_FILE,
    PROVIDER_SCHEMA_VERSION,
    ProviderFileStore,
    ProviderFileStoreError,
    get_provider_file_store,
)


class ProviderCloudModelRepository:
    def __init__(self, store: ProviderFileStore) -> None:
        self._store = store

    def get_cache(
        self,
        *,
        provider_id: str,
        protocol_family: str,
        api_base_url: str,
    ) -> ProviderCloudModelCache | None:
        payload = self._store.read_provider_file(
            provider_id,
            PROVIDER_CLOUD_CACHE_FILE,
            required=False,
        )
        if payload is None or not isinstance(payload.get("cache"), dict):
            return None
        cache = payload["cache"]
        if (
            cache.get("protocolFamily") != protocol_family
            or cache.get("apiBaseUrl") != api_base_url
        ):
            return None
        raw_models = cache.get("models")
        if not isinstance(raw_models, list):
            raise ProviderFileStoreError("Provider cloud cache models must be a list.")
        return ProviderCloudModelCache(
            provider_id=provider_id,
            protocol_family=protocol_family,
            api_base_url=api_base_url,
            discovered_at=_required_text(cache, "discoveredAt"),
            models=tuple(
                self._to_model(provider_id, item)
                for item in raw_models
                if isinstance(item, dict)
            ),
        )

    def replace_provider_cache(self, cache: ProviderCloudModelCache) -> ProviderCloudModelCache:
        self._store.write_provider_file(
            cache.provider_id,
            PROVIDER_CLOUD_CACHE_FILE,
            {
                "schemaVersion": PROVIDER_SCHEMA_VERSION,
                "cache": {
                    "protocolFamily": cache.protocol_family,
                    "apiBaseUrl": cache.api_base_url,
                    "discoveredAt": cache.discovered_at,
                    "models": [self._from_model(model) for model in cache.models],
                },
            },
        )
        return cache

    def delete_provider_cache(self, provider_id: str) -> None:
        if not self._store.has_provider(provider_id):
            return
        self._store.write_provider_file(
            provider_id,
            PROVIDER_CLOUD_CACHE_FILE,
            {"schemaVersion": PROVIDER_SCHEMA_VERSION, "cache": None},
        )

    @staticmethod
    def _from_model(model: DiscoveredModel) -> dict[str, Any]:
        return {
            "modelId": model.model_id,
            "displayName": model.display_name,
            "familyGroup": model.family_group,
            "capabilityTags": list(model.capability_tags),
        }

    @staticmethod
    def _to_model(provider_id: str, payload: dict[str, Any]) -> DiscoveredModel:
        tags = payload.get("capabilityTags")
        return DiscoveredModel(
            model_id=_required_text(payload, "modelId"),
            display_name=_required_text(payload, "displayName"),
            provider_id=provider_id,
            family_group=_optional_text(payload, "familyGroup") or "",
            capability_tags=tuple(item for item in tags if isinstance(item, str))
            if isinstance(tags, list)
            else (),
        )


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = _optional_text(payload, key)
    if value is None:
        raise ProviderFileStoreError(f"Provider cloud cache field is required: {key}")
    return value


def _optional_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


@lru_cache
def get_provider_cloud_model_repository() -> ProviderCloudModelRepository:
    return ProviderCloudModelRepository(get_provider_file_store())
