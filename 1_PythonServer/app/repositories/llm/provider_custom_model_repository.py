from functools import lru_cache
from typing import Any

from app.domain.llm.provider_custom_model import ProviderCustomModel
from app.repositories.llm.provider_file_store import (
    PROVIDER_MODELS_FILE,
    PROVIDER_SCHEMA_VERSION,
    ProviderFileStore,
    ProviderFileStoreError,
    get_provider_file_store,
)


class ProviderCustomModelRepository:
    def __init__(self, store: ProviderFileStore) -> None:
        self._store = store

    def list_models(self, provider_id: str) -> tuple[ProviderCustomModel, ...]:
        payload = self._store.read_provider_file(
            provider_id,
            PROVIDER_MODELS_FILE,
            required=False,
        )
        if payload is None:
            return ()
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise ProviderFileStoreError("Provider models items must be a list.")
        return tuple(
            self._to_domain(provider_id, item)
            for item in raw_items
            if isinstance(item, dict)
        )

    def list_all_models(self) -> tuple[ProviderCustomModel, ...]:
        return tuple(
            model
            for provider_id in self._store.list_provider_ids()
            for model in self.list_models(provider_id)
        )

    def get_model(self, *, provider_id: str, model_id: str) -> ProviderCustomModel | None:
        return next(
            (model for model in self.list_models(provider_id) if model.model_id == model_id),
            None,
        )

    def save_model(self, model: ProviderCustomModel) -> ProviderCustomModel:
        models = list(self.list_models(model.provider_id))
        existing_index = next(
            (index for index, item in enumerate(models) if item.model_id == model.model_id),
            None,
        )
        if existing_index is None:
            models.append(model)
        else:
            models[existing_index] = model
        self._write_models(model.provider_id, models)
        saved = self.get_model(provider_id=model.provider_id, model_id=model.model_id)
        if saved is None:
            raise ProviderFileStoreError(f"Provider model save failed: {model.model_id}")
        return saved

    def delete_model(self, *, provider_id: str, model_id: str) -> bool:
        models = list(self.list_models(provider_id))
        next_models = [model for model in models if model.model_id != model_id]
        if len(next_models) == len(models):
            return False
        self._write_models(provider_id, next_models)
        return True

    def delete_provider_models(self, provider_id: str) -> None:
        if self._store.has_provider(provider_id):
            self._write_models(provider_id, [])

    def _write_models(self, provider_id: str, models: list[ProviderCustomModel]) -> None:
        self._store.write_provider_file(
            provider_id,
            PROVIDER_MODELS_FILE,
            {
                "schemaVersion": PROVIDER_SCHEMA_VERSION,
                "items": [self._from_domain(model) for model in models],
            },
        )

    @staticmethod
    def _from_domain(model: ProviderCustomModel) -> dict[str, Any]:
        return {
            "modelId": model.model_id,
            "displayName": model.display_name,
            "familyGroup": model.family_group,
            "capabilityTags": list(model.capability_tags),
            "note": model.note,
            "priceCurrency": model.price_currency,
            "inputPricePerMillion": model.input_price_per_million,
            "cacheHitPricePerMillion": model.cache_hit_price_per_million,
            "outputPricePerMillion": model.output_price_per_million,
            "createdAt": model.created_at,
            "updatedAt": model.updated_at,
        }

    @staticmethod
    def _to_domain(provider_id: str, payload: dict[str, Any]) -> ProviderCustomModel:
        capability_tags = payload.get("capabilityTags")
        return ProviderCustomModel(
            provider_id=provider_id,
            model_id=_required_text(payload, "modelId"),
            display_name=_required_text(payload, "displayName"),
            family_group=_optional_text(payload, "familyGroup") or "",
            capability_tags=tuple(
                item for item in capability_tags if isinstance(item, str)
            ) if isinstance(capability_tags, list) else (),
            note=_optional_text(payload, "note") or "",
            price_currency=_optional_text(payload, "priceCurrency") or "CNY",
            input_price_per_million=_optional_float(payload.get("inputPricePerMillion")),
            cache_hit_price_per_million=_optional_float(payload.get("cacheHitPricePerMillion")),
            output_price_per_million=_optional_float(payload.get("outputPricePerMillion")),
            created_at=_optional_text(payload, "createdAt"),
            updated_at=_optional_text(payload, "updatedAt"),
        )


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = _optional_text(payload, key)
    if value is None:
        raise ProviderFileStoreError(f"Provider model field is required: {key}")
    return value


def _optional_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@lru_cache
def get_provider_custom_model_repository() -> ProviderCustomModelRepository:
    return ProviderCustomModelRepository(get_provider_file_store())
