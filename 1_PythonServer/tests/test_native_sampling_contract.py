from dataclasses import replace

import pytest

from app.core.errors import AppError
from app.domain.llm.chat import ChatCompletionRequest, ChatMessage, ChatMessageRole
from app.domain.llm.generation_params import LlmGenerationParams
from app.domain.llm.provider_adaptation import LlmCapabilityRules, ProviderAdaptationRules
from app.domain.llm.provider_catalog import (
    AuthScheme, ProviderCatalogEntry, ProviderEndpointTemplate, ProviderProtocolFamily,
    default_model_discovery_strategy,
)
from app.infra.llm.chat_adapters.anthropic import _build_anthropic_body
from app.infra.llm.chat_adapters.gemini import _build_gemini_body
from app.infra.llm.provider_profiles import resolve_provider_profile
from app.services.llm.chat.request_validation import validate_chat_request_capabilities
from app.services.llm.runtime.capabilities import LlmRuntimeCapabilitiesService


def _provider(protocol):
    return ProviderCatalogEntry(
        provider_id="sampling-test", display_name="Sampling", profile_id="custom",
        protocol_family=protocol, generation_auth_schemes={},
        model_discovery_strategy=default_model_discovery_strategy(protocol),
        model_discovery_auth_scheme=AuthScheme.BEARER_TOKEN,
        endpoints=ProviderEndpointTemplate("https://example.invalid", "", None),
    )


def _request(**generation):
    return ChatCompletionRequest(
        provider_id="sampling-test", model_id="test-model",
        messages=(ChatMessage(role=ChatMessageRole.USER, content="test"),),
        generation=LlmGenerationParams(**generation),
    )


@pytest.mark.parametrize("parameter", ["presence_penalty", "frequency_penalty"])
def test_anthropic_rejects_unsent_penalties_including_declared_rule_overrides(parameter):
    provider = _provider(ProviderProtocolFamily.ANTHROPIC_MESSAGES)
    rules = ProviderAdaptationRules(capabilities=LlmCapabilityRules(
        sampling_parameters=("temperature", "top_p", "presence_penalty", "frequency_penalty"),
    ))
    profile = resolve_provider_profile(provider, adaptation_rules=rules)
    capabilities = profile.resolve_capabilities(provider, "test-model")
    assert capabilities.sampling.parameters == ("temperature", "top_p")
    with pytest.raises(AppError, match=parameter):
        validate_chat_request_capabilities(_request(**{parameter: 0.7}), capabilities)


def test_anthropic_supported_parameters_are_validated_and_sent():
    provider = _provider(ProviderProtocolFamily.ANTHROPIC_MESSAGES)
    profile = resolve_provider_profile(provider, load_declared_rules=False)
    request = _request(temperature=0.4, top_p=0.8)
    validate_chat_request_capabilities(request, profile.resolve_capabilities(provider, "test-model"))
    body = _build_anthropic_body(request, stream=False)
    assert body["temperature"] == 0.4
    assert body["top_p"] == 0.8


@pytest.mark.parametrize("value", [0, -0.5, 0.7])
def test_gemini_penalties_reach_the_generation_payload(value):
    provider = _provider(ProviderProtocolFamily.GEMINI_GENERATE_CONTENT)
    profile = resolve_provider_profile(provider, load_declared_rules=False)
    request = _request(presence_penalty=value, frequency_penalty=value)
    validate_chat_request_capabilities(request, profile.resolve_capabilities(provider, "test-model"))
    assert _build_gemini_body(request)["generationConfig"] == {
        "presencePenalty": value, "frequencyPenalty": value,
    }


def test_unset_gemini_penalties_are_not_sent():
    assert _build_gemini_body(_request())["generationConfig"] == {}


@pytest.mark.parametrize("protocol", [
    ProviderProtocolFamily.ANTHROPIC_MESSAGES, ProviderProtocolFamily.GEMINI_GENERATE_CONTENT,
])
def test_model_rules_can_still_restrict_native_sampling(protocol):
    provider = _provider(protocol)
    rules = ProviderAdaptationRules(capabilities=LlmCapabilityRules(
        sampling_supported=False, sampling_parameters=(), max_output_tokens_max=9000,
    ))
    profile = resolve_provider_profile(provider, adaptation_rules=rules)
    capabilities = profile.resolve_capabilities(provider, "test-model")
    assert not capabilities.sampling.supported
    assert capabilities.sampling.parameters == ()
    assert capabilities.max_output_tokens.max == 9000
    with pytest.raises(AppError, match="不支持采样"):
        validate_chat_request_capabilities(_request(temperature=0.5), capabilities)


def test_runtime_capability_api_uses_the_same_native_contract():
    from types import SimpleNamespace

    provider = _provider(ProviderProtocolFamily.ANTHROPIC_MESSAGES)
    service = LlmRuntimeCapabilitiesService(
        SimpleNamespace(get_entry=lambda _: provider),
        SimpleNamespace(get_model=lambda **_: None),
    )
    assert service.get_capabilities(provider_id=provider.provider_id).sampling.parameters == (
        "temperature", "top_p",
    )
    openai = replace(provider, protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE)
    profile = resolve_provider_profile(openai, load_declared_rules=False)
    assert "presence_penalty" in profile.resolve_capabilities(openai, None).sampling.parameters
