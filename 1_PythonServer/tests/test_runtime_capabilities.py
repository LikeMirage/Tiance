import pytest

from app.domain.llm.provider_catalog import (
    AuthScheme,
    ProviderCatalogEntry,
    ProviderEndpointTemplate,
    ProviderProtocolFamily,
    default_model_discovery_strategy,
)
from app.domain.llm.provider_custom_model import ProviderCustomModel
from app.services.llm.runtime.capabilities import LlmRuntimeCapabilitiesService


@pytest.mark.parametrize(
    ("provider_id", "profile_id", "protocol_family"),
    (
        ("custom-openai", "custom", ProviderProtocolFamily.OPENAI_COMPATIBLE),
        ("volcengine", "volcengine", ProviderProtocolFamily.OPENAI_COMPATIBLE),
        ("custom-responses", "custom", ProviderProtocolFamily.OPENAI_RESPONSES),
        ("custom-anthropic", "custom", ProviderProtocolFamily.ANTHROPIC_MESSAGES),
        ("custom-gemini", "custom", ProviderProtocolFamily.GEMINI_GENERATE_CONTENT),
    ),
)
def test_vision_tag_enables_image_input_for_every_protocol(
    provider_id: str,
    profile_id: str,
    protocol_family: ProviderProtocolFamily,
):
    provider = _provider_entry(
        provider_id=provider_id,
        profile_id=profile_id,
        protocol_family=protocol_family,
    )
    service = LlmRuntimeCapabilitiesService(
        _CatalogRepositoryStub(provider),
        _CustomModelRepositoryStub(
            _custom_model(provider.provider_id, "vision-model", tags=("vision",))
        ),
    )

    capabilities = service.get_capabilities(
        provider_id=provider.provider_id,
        model_id="vision-model",
    )

    assert capabilities.input_modalities == ("text", "image")


@pytest.mark.parametrize(
    ("provider_id", "profile_id", "protocol_family"),
    (
        ("custom-openai", "custom", ProviderProtocolFamily.OPENAI_COMPATIBLE),
        ("volcengine", "volcengine", ProviderProtocolFamily.OPENAI_COMPATIBLE),
        ("custom-responses", "custom", ProviderProtocolFamily.OPENAI_RESPONSES),
        ("custom-anthropic", "custom", ProviderProtocolFamily.ANTHROPIC_MESSAGES),
        ("custom-gemini", "custom", ProviderProtocolFamily.GEMINI_GENERATE_CONTENT),
    ),
)
def test_provider_profile_does_not_bypass_model_vision_tag(
    provider_id: str,
    profile_id: str,
    protocol_family: ProviderProtocolFamily,
):
    provider = _provider_entry(
        provider_id=provider_id,
        profile_id=profile_id,
        protocol_family=protocol_family,
    )
    service = LlmRuntimeCapabilitiesService(
        _CatalogRepositoryStub(provider),
        _CustomModelRepositoryStub(
            _custom_model(provider.provider_id, "text-model", tags=("reasoning",))
        ),
    )

    capabilities = service.get_capabilities(
        provider_id=provider.provider_id,
        model_id="text-model",
    )

    assert capabilities.input_modalities == ("text",)


class _CatalogRepositoryStub:
    def __init__(self, provider: ProviderCatalogEntry) -> None:
        self._provider = provider

    def get_entry(self, provider_id: str):
        return self._provider if provider_id == self._provider.provider_id else None


class _CustomModelRepositoryStub:
    def __init__(self, model: ProviderCustomModel) -> None:
        self._model = model

    def get_model(self, *, provider_id: str, model_id: str):
        if provider_id == self._model.provider_id and model_id == self._model.model_id:
            return self._model
        return None


def _provider_entry(
    *,
    provider_id: str,
    profile_id: str,
    protocol_family: ProviderProtocolFamily,
) -> ProviderCatalogEntry:
    return ProviderCatalogEntry(
        provider_id=provider_id,
        display_name=provider_id,
        profile_id=profile_id,
        protocol_family=protocol_family,
        generation_auth_schemes={protocol_family: AuthScheme.BEARER_TOKEN},
        model_discovery_strategy=default_model_discovery_strategy(protocol_family),
        model_discovery_auth_scheme=AuthScheme.BEARER_TOKEN,
        endpoints=ProviderEndpointTemplate(
            api_base_url="https://example.test",
            text_generation_url_template="https://example.test/chat/completions",
            model_discovery_url="https://example.test/models",
        ),
    )


def _custom_model(
    provider_id: str,
    model_id: str,
    *,
    tags: tuple[str, ...],
) -> ProviderCustomModel:
    return ProviderCustomModel(
        provider_id=provider_id,
        model_id=model_id,
        display_name=model_id,
        family_group="",
        capability_tags=tags,
    )
