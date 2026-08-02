from app.domain.llm.chat import ChatUsage
from app.domain.llm.generation_params import LlmReasoningMode
from app.domain.llm.provider_catalog import (
    AuthScheme,
    ProviderCatalogEntry,
    ProviderEndpointTemplate,
    ProviderProtocolFamily,
    default_model_discovery_strategy,
)
from app.infra.llm.provider_profiles.base import GenericOpenAICompatibleProfile
from app.infra.llm.provider_profiles.deepseek import DeepSeekProfile
from app.infra.llm.provider_profiles.openai_responses import (
    OpenAIProfile,
    OpenAIResponsesProfile,
)
from app.infra.llm.provider_profiles.registry import resolve_provider_profile
from app.infra.llm.provider_profiles.volcengine import VolcengineProfile


def test_deepseek_usage_reads_top_level_cache_tokens():
    usage = DeepSeekProfile().parse_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "prompt_cache_hit_tokens": 60,
            "prompt_cache_miss_tokens": 40,
            "completion_tokens_details": {"reasoning_tokens": 8},
        }
    )

    assert usage == ChatUsage(
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        prompt_cache_hit_tokens=60,
        prompt_cache_miss_tokens=40,
        reasoning_tokens=8,
    )


def test_volcengine_usage_reads_prompt_details_cached_tokens():
    usage = VolcengineProfile().parse_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "prompt_tokens_details": {"cached_tokens": 64},
            "completion_tokens_details": {"reasoning_tokens": 9},
        }
    )

    assert usage == ChatUsage(
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        prompt_cache_hit_tokens=64,
        prompt_cache_miss_tokens=36,
        reasoning_tokens=9,
    )


def test_volcengine_profile_exposes_provider_default_reasoning_modes():
    capabilities = VolcengineProfile().resolve_capabilities(
        _provider_entry(provider_id="volcengine", profile_id="volcengine"),
        "doubao-seed-2-0-pro-260215",
    )

    assert capabilities.reasoning.modes == (
        LlmReasoningMode.DEFAULT,
        LlmReasoningMode.AUTO,
        LlmReasoningMode.ENABLED,
        LlmReasoningMode.OFF,
    )


def test_volcengine_unknown_model_keeps_provider_default_reasoning_modes():
    capabilities = VolcengineProfile().resolve_capabilities(
        _provider_entry(provider_id="volcengine", profile_id="volcengine"),
        "future-volcengine-model",
    )

    assert capabilities.reasoning.modes == (
        LlmReasoningMode.DEFAULT,
        LlmReasoningMode.AUTO,
        LlmReasoningMode.ENABLED,
        LlmReasoningMode.OFF,
    )


def test_generic_profile_does_not_read_provider_specific_top_level_cache_tokens():
    usage = GenericOpenAICompatibleProfile().parse_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "prompt_cache_hit_tokens": 60,
            "prompt_cache_miss_tokens": 40,
        }
    )

    assert usage == ChatUsage(
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
    )


def test_resolve_provider_profile_uses_registry_mappings():
    assert isinstance(
        resolve_provider_profile(_provider_entry(provider_id="renamed-deepseek", profile_id="deepseek")),
        DeepSeekProfile,
    )
    assert isinstance(
        resolve_provider_profile(_provider_entry(provider_id="renamed-volcengine", profile_id="volcengine")),
        VolcengineProfile,
    )
    assert isinstance(
        resolve_provider_profile(_provider_entry(provider_id="custom", profile_id="generic")),
        GenericOpenAICompatibleProfile,
    )


def test_responses_profile_resolution_uses_explicit_provider_whitelist():
    openai_profile = resolve_provider_profile(
        _provider_entry(
            provider_id="openai",
            profile_id="openai",
            protocol_family=ProviderProtocolFamily.OPENAI_RESPONSES,
        )
    )
    volcengine_profile = resolve_provider_profile(
        _provider_entry(
            provider_id="volcengine",
            profile_id="volcengine",
            protocol_family=ProviderProtocolFamily.OPENAI_RESPONSES,
        )
    )
    generic_profile = resolve_provider_profile(
        _provider_entry(
            provider_id="custom",
            profile_id="generic",
            protocol_family=ProviderProtocolFamily.OPENAI_RESPONSES,
        )
    )

    assert isinstance(openai_profile, OpenAIProfile)
    assert openai_profile.include_responses_message_phase is True
    assert isinstance(volcengine_profile, VolcengineProfile)
    assert volcengine_profile.include_responses_message_phase is False
    assert type(generic_profile) is OpenAIResponsesProfile
    assert generic_profile.include_responses_message_phase is False


def test_deepseek_profile_exposes_current_max_output_limit():
    capabilities = DeepSeekProfile().resolve_capabilities(
        _provider_entry(provider_id="deepseek", profile_id="deepseek"),
        "deepseek-v4-flash",
    )

    assert capabilities.max_output_tokens.max == 384000


def _provider_entry(
    *,
    provider_id: str,
    profile_id: str,
    protocol_family: ProviderProtocolFamily = ProviderProtocolFamily.OPENAI_COMPATIBLE,
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
            text_generation_url_template="chat/completions",
            model_discovery_url=None,
        ),
    )
