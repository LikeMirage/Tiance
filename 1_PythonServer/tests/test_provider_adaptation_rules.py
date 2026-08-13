import json
from types import SimpleNamespace

import pytest

from app.domain.llm.chat import ChatCompletionRequest, ChatMessage, ChatMessageRole
from app.domain.llm.generation_params import (
    LlmGenerationParams,
    LlmOutputFormat,
    LlmOutputOptions,
    LlmReasoningOptions,
    LlmReasoningMode,
)
from app.domain.llm.provider_catalog import ProviderProtocolFamily
from app.infra.llm.provider_profiles.base import GenericOpenAICompatibleProfile
from app.infra.llm.provider_profiles.volcengine import VolcengineProfile
from app.repositories.llm.provider_adaptation_rules_repository import (
    ProviderAdaptationRulesRepository,
)
from app.repositories.llm.provider_file_store import (
    PROVIDER_MANIFEST_FILE,
    PROVIDER_MODEL_RULES_FILE,
    PROVIDER_MODELS_FILE,
    PROVIDER_RULES_FILE,
    ProviderFileStore,
    ProviderFileStoreError,
)


def test_rules_merge_provider_family_and_exact_model_in_order(tmp_path):
    store = ProviderFileStore(tmp_path)
    _write_manifest(store)
    store.write_provider_file(
        "provider-a",
        PROVIDER_RULES_FILE,
        {
            "schemaVersion": 1,
            "capabilities": {
                "reasoning": {"supported": True, "modes": ["off", "high"]},
            },
            "request": {"omitParameters": ["presence_penalty"]},
            "behavior": {
                "includeResponsesMessagePhase": False,
                "promptCacheRetentionSeconds": 300,
            },
        },
    )
    store.write_provider_file(
        "provider-a",
        PROVIDER_MODEL_RULES_FILE,
        {
            "schemaVersion": 1,
            "families": {
                "family-a": {
                    "capabilities": {"reasoning": {"modes": ["off", "medium"]}},
                    "request": {"omitParameters": ["top_p"]},
                }
            },
            "models": {
                "model-a": {
                    "capabilities": {"reasoning": {"modes": ["off", "max"]}},
                    "request": {"streamUsage": True},
                    "behavior": {
                        "includeResponsesMessagePhase": True,
                        "promptCacheRetentionSeconds": 600,
                    },
                }
            },
        },
    )
    store.write_provider_file(
        "provider-a",
        PROVIDER_MODELS_FILE,
        {
            "schemaVersion": 1,
            "items": [{"modelId": "model-a", "familyGroup": "family-a"}],
        },
    )

    rules = ProviderAdaptationRulesRepository(store).resolve(
        provider_id="provider-a",
        model_id="MODEL-A",
        expected_profile_id="generic",
    )

    assert rules is not None
    assert rules.capabilities.reasoning_supported is True
    assert rules.capabilities.reasoning_modes == (
        LlmReasoningMode.OFF,
        LlmReasoningMode.MAX,
    )
    assert rules.request.omit_parameters == ("top_p",)
    assert rules.request.stream_usage is True
    assert rules.behavior.include_responses_message_phase is True
    assert rules.behavior.prompt_cache_retention_seconds == 600


def test_rules_reject_unknown_fields(tmp_path):
    store = ProviderFileStore(tmp_path)
    _write_manifest(store)
    store.write_provider_file(
        "provider-a",
        PROVIDER_RULES_FILE,
        {
            "schemaVersion": 1,
            "capabilities": {"executableHook": "module.function"},
            "request": {},
        },
    )

    with pytest.raises(ProviderFileStoreError, match="unknown fields"):
        ProviderAdaptationRulesRepository(store).resolve(
            provider_id="provider-a",
            model_id=None,
            expected_profile_id="generic",
        )


def test_declared_request_rules_drive_provider_request_shape(tmp_path):
    store = ProviderFileStore(tmp_path)
    _write_manifest(store)
    store.write_provider_file(
        "provider-a",
        PROVIDER_RULES_FILE,
        {
            "schemaVersion": 1,
            "capabilities": {},
            "request": {
                "omitParameters": ["presence_penalty"],
                "maxOutputTokensParameter": "max_completion_tokens",
                "jsonObjectResponseFormat": True,
                "streamUsage": True,
            },
        },
    )
    rules = ProviderAdaptationRulesRepository(store).resolve(
        provider_id="provider-a",
        model_id="model-a",
        expected_profile_id="generic",
    )
    assert rules is not None
    request = ChatCompletionRequest(
        provider_id="provider-a",
        model_id="model-a",
        messages=(ChatMessage(role=ChatMessageRole.USER, content="test"),),
        generation=LlmGenerationParams(max_output_tokens=100, presence_penalty=0.2),
        output=LlmOutputOptions(format=LlmOutputFormat.JSON_OBJECT),
    )

    body = VolcengineProfile(adaptation_rules=rules).apply_openai_compatible_body(
        {
            "stream": True,
            "max_tokens": 100,
            "presence_penalty": 0.2,
        },
        request,
    )

    assert body["max_completion_tokens"] == 100
    assert body["response_format"] == {"type": "json_object"}
    assert body["stream_options"] == {"include_usage": True}
    assert "max_tokens" not in body
    assert "presence_penalty" not in body


@pytest.mark.parametrize(
    ("mode", "expected_thinking", "expected_effort"),
    [
        (LlmReasoningMode.OFF, {"type": "disabled"}, None),
        (LlmReasoningMode.HIGH, {"type": "enabled"}, "high"),
        (LlmReasoningMode.MAX, {"type": "enabled"}, "max"),
    ],
)
def test_generic_profile_applies_declared_reasoning_request_shape(
    tmp_path,
    mode,
    expected_thinking,
    expected_effort,
):
    store = ProviderFileStore(tmp_path)
    _write_manifest(store)
    store.write_provider_file(
        "provider-a",
        PROVIDER_MODEL_RULES_FILE,
        {
            "schemaVersion": 1,
            "families": {},
            "models": {
                "model-a": {
                    "capabilities": {
                        "reasoning": {
                            "supported": True,
                            "modes": ["off", "high", "max"],
                        },
                        "sampling": {
                            "disabledWhenReasoning": True,
                            "parameters": ["temperature", "top_p"],
                        },
                    },
                    "request": {
                        "reasoningEffortParameter": "reasoning_effort",
                        "reasoningToggleParameter": "thinking",
                        "reasoningEnabledValue": {"type": "enabled"},
                        "reasoningDisabledValue": {"type": "disabled"},
                    },
                }
            },
        },
    )
    rules = ProviderAdaptationRulesRepository(store).resolve(
        provider_id="provider-a",
        model_id="model-a",
        expected_profile_id="generic",
    )
    assert rules is not None
    request = ChatCompletionRequest(
        provider_id="provider-a",
        model_id="model-a",
        messages=(ChatMessage(role=ChatMessageRole.USER, content="test"),),
        generation=LlmGenerationParams(
            temperature=0.5,
            top_p=0.9,
            reasoning=LlmReasoningOptions(mode=mode),
        ),
    )
    profile = GenericOpenAICompatibleProfile(adaptation_rules=rules)

    capabilities = profile.resolve_capabilities(
        SimpleNamespace(
            provider_id="provider-a",
            protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE,
        ),
        "model-a",
    )
    body = profile.apply_openai_compatible_body(
        {"temperature": 0.5, "top_p": 0.9},
        request,
    )

    assert capabilities.reasoning.supported is True
    assert capabilities.reasoning.modes == (
        LlmReasoningMode.OFF,
        LlmReasoningMode.HIGH,
        LlmReasoningMode.MAX,
    )
    assert body["thinking"] == expected_thinking
    assert body.get("reasoning_effort") == expected_effort
    if mode != LlmReasoningMode.OFF:
        assert "temperature" not in body
        assert "top_p" not in body


def test_sidecars_create_empty_rule_files(tmp_path):
    store = ProviderFileStore(tmp_path)
    _write_manifest(store)

    store.ensure_provider_sidecars("provider-a")

    assert json.loads((tmp_path / "provider-a" / PROVIDER_RULES_FILE).read_text("utf-8")) == {
        "schemaVersion": 1,
        "capabilities": {},
        "request": {},
        "behavior": {},
    }
    assert json.loads(
        (tmp_path / "provider-a" / PROVIDER_MODEL_RULES_FILE).read_text("utf-8")
    ) == {
        "schemaVersion": 1,
        "families": {},
        "models": {},
    }


def test_prompt_cache_retention_defaults_and_saves_without_replacing_other_rules(
    tmp_path,
):
    store = ProviderFileStore(tmp_path)
    _write_manifest(store)
    store.ensure_provider_sidecars("provider-a")
    repository = ProviderAdaptationRulesRepository(store)

    assert repository.resolve_prompt_cache_retention_seconds(
        provider_id="provider-a"
    ) == 300

    repository.save_prompt_cache_retention_seconds(
        provider_id="provider-a",
        seconds=21600,
    )

    saved = json.loads(
        (tmp_path / "provider-a" / PROVIDER_RULES_FILE).read_text("utf-8")
    )
    assert saved["behavior"]["promptCacheRetentionSeconds"] == 21600
    assert repository.resolve_prompt_cache_retention_seconds(
        provider_id="provider-a"
    ) == 21600


def _write_manifest(store: ProviderFileStore) -> None:
    store.write_provider_file(
        "provider-a",
        PROVIDER_MANIFEST_FILE,
        {
            "schemaVersion": 1,
            "id": "provider-a",
            "profileId": "generic",
        },
    )
