# 自定义模型服务
# 验证和持久化用户手动添加的模型，含价格和功能标签的规范化

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from math import isfinite
import re

from app.core.errors import BadRequestError, NotFoundError
from app.domain.llm.provider_custom_model import ProviderCustomModel
from app.repositories.llm.provider_catalog_repository import (
    ProviderCatalogRepository,
    get_provider_catalog_repository,
)
from app.repositories.llm.provider_custom_model_repository import (
    ProviderCustomModelRepository,
    get_provider_custom_model_repository,
)


@dataclass(frozen=True, slots=True)
class ProviderCustomModelSaveInput:
    provider_id: str
    model_id: str
    display_name: str
    family_group: str
    capability_tags: tuple[str, ...]
    note: str
    price_currency: str
    input_price_per_million: float | None
    cache_hit_price_per_million: float | None
    output_price_per_million: float | None


class ProviderCustomModelService:
    def __init__(
        self,
        catalog_repository: ProviderCatalogRepository,
        custom_model_repository: ProviderCustomModelRepository,
    ) -> None:
        self._catalog_repository = catalog_repository
        self._custom_model_repository = custom_model_repository

    def list_models(self, provider_id: str) -> tuple[ProviderCustomModel, ...]:
        provider_template = self._require_provider_template(provider_id)
        return self._custom_model_repository.list_models(provider_template.provider_id)

    def save_model(self, payload: ProviderCustomModelSaveInput) -> ProviderCustomModel:
        provider_template = self._require_provider_template(payload.provider_id)
        normalized_model_id = payload.model_id.strip()
        if not normalized_model_id:
            raise BadRequestError("Model id is required.")

        existing_models = {
            model.model_id: model
            for model in self._custom_model_repository.list_models(provider_template.provider_id)
        }
        existing_model = existing_models.get(normalized_model_id)
        now = _utc_now()
        model = ProviderCustomModel(
            provider_id=provider_template.provider_id,
            model_id=normalized_model_id,
            display_name=payload.display_name.strip(),
            family_group=payload.family_group.strip(),
            capability_tags=_normalize_capability_tags(payload.capability_tags),
            note=payload.note.strip(),
            price_currency=_normalize_price_currency(payload.price_currency),
            input_price_per_million=_normalize_optional_price(
                payload.input_price_per_million,
                field_label="输入价格",
            ),
            cache_hit_price_per_million=_normalize_optional_price(
                payload.cache_hit_price_per_million,
                field_label="缓存命中价格",
            ),
            output_price_per_million=_normalize_optional_price(
                payload.output_price_per_million,
                field_label="输出价格",
            ),
            created_at=existing_model.created_at if existing_model is not None else now,
            updated_at=now,
        )
        return self._custom_model_repository.save_model(model)

    def delete_model(self, *, provider_id: str, model_id: str) -> bool:
        provider_template = self._require_provider_template(provider_id)
        normalized_model_id = model_id.strip()
        if not normalized_model_id:
            raise BadRequestError("Model id is required.")
        deleted = self._custom_model_repository.delete_model(
            provider_id=provider_template.provider_id,
            model_id=normalized_model_id,
        )
        return deleted

    def _require_provider_template(self, provider_id: str):
        provider_template = self._catalog_repository.get_entry(provider_id)
        if provider_template is None:
            raise NotFoundError(f"Provider template '{provider_id}' was not found.")
        return provider_template


def _normalize_capability_tags(tags: tuple[str, ...]) -> tuple[str, ...]:
    normalized_tags: list[str] = []
    seen_tags: set[str] = set()
    for tag in tags:
        normalized_tag = tag.strip().lower()
        if not normalized_tag or normalized_tag in seen_tags:
            continue
        seen_tags.add(normalized_tag)
        normalized_tags.append(normalized_tag)
    return tuple(normalized_tags)


def _normalize_price_currency(price_currency: str) -> str:
    normalized_currency = price_currency.strip().upper()
    if not normalized_currency:
        return "CNY"

    if not re.fullmatch(r"[A-Z]{3,8}", normalized_currency):
        raise BadRequestError("价格币种格式无效。")

    return normalized_currency


def _normalize_optional_price(
    price: float | None,
    *,
    field_label: str,
) -> float | None:
    if price is None:
        return None

    try:
        normalized_price = float(price)
    except (TypeError, ValueError) as exc:
        raise BadRequestError(f"{field_label}必须是大于等于 0 的数字。") from exc

    if not isfinite(normalized_price) or normalized_price < 0:
        raise BadRequestError(f"{field_label}必须是大于等于 0 的数字。")

    return normalized_price


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@lru_cache
def get_provider_custom_model_service() -> ProviderCustomModelService:
    return ProviderCustomModelService(
        get_provider_catalog_repository(),
        get_provider_custom_model_repository(),
    )
