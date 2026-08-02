# LLM 模型目录服务
# 将现有供应商配置、目录和用户添加模型统一成前端选择器可消费的列表

from functools import lru_cache
from typing import Literal

from app.domain.llm.model_catalog import LlmModelCatalogEntry
from app.domain.llm.provider_custom_model import ProviderCustomModel
from app.repositories.llm.provider_catalog_repository import (
    ProviderCatalogRepository,
    get_provider_catalog_repository,
)
from app.repositories.llm.provider_config_repository import (
    ProviderConfigRepository,
    get_provider_config_repository,
)
from app.repositories.llm.provider_custom_model_repository import (
    ProviderCustomModelRepository,
    get_provider_custom_model_repository,
)

LlmModelCatalogKind = Literal["chat", "functional_text", "vision"]


class LlmModelCatalogService:
    def __init__(
        self,
        catalog_repository: ProviderCatalogRepository,
        config_repository: ProviderConfigRepository,
        custom_model_repository: ProviderCustomModelRepository,
    ) -> None:
        self._catalog_repository = catalog_repository
        self._config_repository = config_repository
        self._custom_model_repository = custom_model_repository

    def list_models(
        self,
        *,
        enabled_only: bool = True,
        kind: LlmModelCatalogKind | None = None,
    ) -> tuple[LlmModelCatalogEntry, ...]:
        catalog_by_id = {
            provider.provider_id: provider
            for provider in self._catalog_repository.list_entries()
        }
        configs_by_id = {
            config.provider_id: config
            for config in self._config_repository.list_configs()
        }

        entries: list[LlmModelCatalogEntry] = []
        for model in self._custom_model_repository.list_all_models():
            provider_template = catalog_by_id.get(model.provider_id)
            config = configs_by_id.get(model.provider_id)
            provider_enabled = bool(config and config.enabled)
            if enabled_only and not provider_enabled:
                continue
            if kind is not None and not _matches_kind(model, kind):
                continue

            entries.append(
                LlmModelCatalogEntry(
                    provider_id=model.provider_id,
                    provider_label=(
                        provider_template.display_name
                        if provider_template is not None
                        else model.provider_id
                    ),
                    provider_enabled=provider_enabled,
                    protocol_family=(
                        provider_template.protocol_family.value
                        if provider_template is not None
                        else ""
                    ),
                    model_id=model.model_id,
                    model_label=model.display_name or model.model_id,
                    family_group=model.family_group,
                    capability_tags=model.capability_tags,
                    source="added",
                    price_currency=model.price_currency,
                    input_price_per_million=model.input_price_per_million,
                    cache_hit_price_per_million=model.cache_hit_price_per_million,
                    output_price_per_million=model.output_price_per_million,
                    created_at=model.created_at,
                    updated_at=model.updated_at,
                )
            )

        return tuple(entries)


def _matches_kind(model: ProviderCustomModel, kind: LlmModelCatalogKind) -> bool:
    if kind == "chat":
        return _is_chat_model_candidate(model.capability_tags)
    if kind == "vision":
        return _is_functional_text_model(model.capability_tags) and (
            "vision" in model.capability_tags
        )
    return _is_functional_text_model(model.capability_tags)


def _is_chat_model_candidate(capability_tags: tuple[str, ...]) -> bool:
    if not capability_tags:
        return True

    tags = set(capability_tags)
    if tags.intersection({"reasoning", "vision", "function_calling"}):
        return True

    return not all(tag in NON_CHAT_ONLY_CAPABILITIES for tag in capability_tags)


def _is_functional_text_model(capability_tags: tuple[str, ...]) -> bool:
    return not any(tag in EXCLUDED_FUNCTIONAL_TEXT_TAGS for tag in capability_tags)


NON_CHAT_ONLY_CAPABILITIES = frozenset(
    (
        "embedding",
        "rerank",
        "speech_to_text",
        "tts",
        "image_generation",
        "video_generation",
    )
)

EXCLUDED_FUNCTIONAL_TEXT_TAGS = frozenset(
    (
        "embedding",
        "image_generation",
        "rerank",
        "speech_to_text",
        "tts",
        "video_generation",
    )
)


@lru_cache
def get_llm_model_catalog_service() -> LlmModelCatalogService:
    return LlmModelCatalogService(
        get_provider_catalog_repository(),
        get_provider_config_repository(),
        get_provider_custom_model_repository(),
    )
