from dataclasses import replace

from app.core.errors import AppError
from app.domain.llm.provider_adaptation import ProviderAdaptationRules
from app.domain.llm.provider_catalog import ProviderCatalogEntry, ProviderProtocolFamily
from app.infra.llm.provider_profiles.base import (
    GenericOpenAICompatibleProfile,
    ProviderProfile,
)
from app.infra.llm.provider_profiles.deepseek import DeepSeekProfile
from app.infra.llm.provider_profiles.openai_responses import (
    OpenAIProfile,
    OpenAIResponsesProfile,
)
from app.infra.llm.provider_profiles.volcengine import VolcengineProfile
from app.repositories.llm.provider_adaptation_rules_repository import (
    get_provider_adaptation_rules_repository,
)

_GENERIC_OPENAI_COMPATIBLE_PROFILE = GenericOpenAICompatibleProfile()
_OPENAI_RESPONSES_PROFILE = OpenAIResponsesProfile()

_OPENAI_COMPATIBLE_PROFILES_BY_ID: dict[str, ProviderProfile] = {
    "generic": _GENERIC_OPENAI_COMPATIBLE_PROFILE,
    "custom": _GENERIC_OPENAI_COMPATIBLE_PROFILE,
    "openai": _GENERIC_OPENAI_COMPATIBLE_PROFILE,
    "deepseek": DeepSeekProfile(),
    "volcengine": VolcengineProfile(),
}

_OPENAI_RESPONSES_PROFILES_BY_ID: dict[str, ProviderProfile] = {
    "generic": _OPENAI_RESPONSES_PROFILE,
    "custom": _OPENAI_RESPONSES_PROFILE,
    "deepseek": DeepSeekProfile(),
    "openai": OpenAIProfile(),
    "volcengine": VolcengineProfile(),
}

_KNOWN_PROFILE_IDS = frozenset(
    {"generic", "custom", "openai", "deepseek", "volcengine"}
)


def resolve_provider_profile(
    provider_template: ProviderCatalogEntry,
    model_id: str | None = None,
    *,
    adaptation_rules: ProviderAdaptationRules | None = None,
    load_declared_rules: bool = True,
) -> ProviderProfile:
    if provider_template.profile_id not in _KNOWN_PROFILE_IDS:
        raise AppError(
            f"Provider profile '{provider_template.profile_id}' is not registered.",
            code="provider_profile_not_registered",
        )
    if provider_template.protocol_family == ProviderProtocolFamily.OPENAI_RESPONSES:
        profile = _OPENAI_RESPONSES_PROFILES_BY_ID[provider_template.profile_id]
    elif provider_template.protocol_family == ProviderProtocolFamily.OPENAI_COMPATIBLE:
        profile = _OPENAI_COMPATIBLE_PROFILES_BY_ID[provider_template.profile_id]
    else:
        profile = _GENERIC_OPENAI_COMPATIBLE_PROFILE

    rules = adaptation_rules
    if rules is None and load_declared_rules:
        rules = get_provider_adaptation_rules_repository().resolve(
            provider_id=provider_template.provider_id,
            model_id=model_id,
            expected_profile_id=provider_template.profile_id,
        )
    if rules is None:
        return profile
    behavior = rules.behavior
    updates: dict[str, object] = {"adaptation_rules": rules}
    if behavior.include_responses_message_phase is not None:
        updates["include_responses_message_phase"] = (
            behavior.include_responses_message_phase
        )
    if behavior.include_responses_web_search_sources is not None:
        updates["include_responses_web_search_sources"] = (
            behavior.include_responses_web_search_sources
        )
    return replace(profile, **updates)
