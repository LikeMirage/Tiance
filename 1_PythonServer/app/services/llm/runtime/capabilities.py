from dataclasses import replace
from functools import lru_cache

from app.core.errors import NotFoundError
from app.domain.llm.runtime_capabilities import LlmRuntimeCapabilities
from app.infra.llm.provider_profiles import resolve_provider_profile
from app.repositories.llm.provider_catalog_repository import (
    ProviderCatalogRepository,
    get_provider_catalog_repository,
)
from app.repositories.llm.provider_adaptation_rules_repository import (
    ProviderAdaptationRulesRepository,
    get_provider_adaptation_rules_repository,
)
from app.repositories.llm.provider_custom_model_repository import (
    ProviderCustomModelRepository,
    get_provider_custom_model_repository,
)


class LlmRuntimeCapabilitiesService:
    def __init__(
        self,
        catalog_repository: ProviderCatalogRepository,
        custom_model_repository: ProviderCustomModelRepository,
        adaptation_rules_repository: ProviderAdaptationRulesRepository | None = None,
    ) -> None:
        self._catalog_repository = catalog_repository
        self._custom_model_repository = custom_model_repository
        self._adaptation_rules_repository = adaptation_rules_repository

    def get_capabilities(
        self,
        *,
        provider_id: str,
        model_id: str | None = None,
    ) -> LlmRuntimeCapabilities:
        provider_template = self._catalog_repository.get_entry(provider_id)
        if provider_template is None:
            raise NotFoundError(f"Provider template '{provider_id}' was not found.")

        declared_rules = (
            self._adaptation_rules_repository.resolve(
                provider_id=provider_id,
                model_id=model_id,
                expected_profile_id=provider_template.profile_id,
            )
            if self._adaptation_rules_repository is not None
            else None
        )
        profile = resolve_provider_profile(
            provider_template,
            model_id,
            adaptation_rules=declared_rules,
            load_declared_rules=False,
        )
        capabilities = profile.resolve_capabilities(provider_template, model_id)
        if not model_id:
            return capabilities

        model = self._custom_model_repository.get_model(
            provider_id=provider_id,
            model_id=model_id,
        )
        input_modalities = tuple(
            modality
            for modality in capabilities.input_modalities
            if modality != "image"
        )
        if model is not None and "vision" in model.capability_tags:
            input_modalities = (*input_modalities, "image")
        if input_modalities == capabilities.input_modalities:
            return capabilities

        return replace(
            capabilities,
            input_modalities=input_modalities,
        )


@lru_cache
def get_llm_runtime_capabilities_service() -> LlmRuntimeCapabilitiesService:
    return LlmRuntimeCapabilitiesService(
        get_provider_catalog_repository(),
        get_provider_custom_model_repository(),
        get_provider_adaptation_rules_repository(),
    )
