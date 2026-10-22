from types import SimpleNamespace

import pytest

from app.api.routes.llm import provider_configs as routes
from app.domain.llm.discovered_model import DiscoveredModel
from app.repositories.llm.provider_adaptation_rules_repository import ProviderAdaptationRulesRepository
from app.repositories.llm.provider_custom_model_repository import ProviderCustomModelRepository
from app.repositories.llm.provider_file_store import ProviderFileStore, ProviderFileStoreError
from app.schemas.llm.discovered_models import ModelMetadataInferenceRequest
from app.services.llm.provider.custom_models import ProviderCustomModelSaveInput, ProviderCustomModelService
from app.services.llm.provider.discovered_model_metadata import enrich_discovered_model, enrich_discovered_models
from app.services.llm.runtime.capabilities import LlmRuntimeCapabilitiesService
from app.repositories.llm.provider_catalog_repository import ProviderCatalogRepository


@pytest.fixture
def store(tmp_path):
    store = ProviderFileStore(tmp_path)
    store.write_provider_file("provider-a", "provider.json", {
        "schemaVersion": 1, "id": "provider-a", "displayName": "Provider", "profileId": "generic",
        "protocolFamily": "openai_compatible", "generationAuthSchemes": {"openai_compatible": "bearer_token"},
        "generationUrls": {"openai_compatible": "https://example.invalid/chat/completions"},
        "modelDiscoveryStrategy": "openai_models", "modelDiscoveryAuthScheme": "bearer_token",
    })
    store.write_provider_file("provider-a", "provider-rules.json", {
        "schemaVersion": 1, "capabilityTags": ["function_calling"],
    })
    store.write_provider_file("provider-a", "model-rules.json", {
        "schemaVersion": 1,
        "families": {"new-family": {"capabilityTags": ["vision"]}},
        "models": {"exact-model": {"capabilityTags": ["tts"]}},
    })
    return store


def model(model_id="unknown", family="", raw=None):
    return DiscoveredModel(provider_id="provider-a", model_id=model_id, display_name=model_id,
                           family_group=family, raw_payload=raw)


def test_unadded_model_uses_supplied_family_and_unions_metadata_and_name(store):
    repository = ProviderAdaptationRulesRepository(store)
    inferred = enrich_discovered_model(
        model("deepseek-r1", "new-family", {"features": ["function_calling"]}),
        rules_repository=repository,
    )
    assert inferred.capability_tags == ("reasoning", "vision", "function_calling")
    assert not store.provider_file("provider-a", "models.json").exists()


@pytest.mark.parametrize(("model_id", "family", "tags"), [
    ("unknown", "", ("function_calling",)),
    ("unknown", "new-family", ("vision",)),
    ("EXACT-MODEL", "new-family", ("tts",)),
])
def test_rule_levels_match_without_a_saved_model(store, model_id, family, tags):
    result = enrich_discovered_model(model(model_id, family), rules_repository=ProviderAdaptationRulesRepository(store))
    assert result.capability_tags == tags


@pytest.mark.parametrize("model_id", ["deepseek-flash", "deepseek-v4.1-flash"])
def test_flash_is_reasoning_vision_and_tools_without_upstream_metadata(model_id):
    assert enrich_discovered_model(model(model_id)).capability_tags == ("reasoning", "vision", "function_calling")


@pytest.mark.parametrize(("model_id", "present", "absent"), [
    ("gpt-4-turbo", "vision", "image_generation"),
    ("gpt-4-turbo-preview", "function_calling", "vision"),
    ("whisper-1", "speech_to_text", "vision"),
    ("kokoro", "tts", "function_calling"),
    ("bge-reranker-v2", "rerank", "embedding"),
    ("deepseek-v4-pro", "function_calling", "vision"),
])
def test_shared_name_rules_preserve_categories_and_exclusions(model_id, present, absent):
    tags = enrich_discovered_model(model(model_id)).capability_tags
    assert present in tags
    assert absent not in tags


def test_manual_endpoint_and_cloud_discovery_share_rules(store, monkeypatch):
    repository = ProviderAdaptationRulesRepository(store)
    monkeypatch.setattr(routes, "get_provider_adaptation_rules_repository", lambda: repository)
    monkeypatch.setattr(routes, "get_provider_catalog_repository", lambda: ProviderCatalogRepository(store))
    manual = routes.infer_provider_model_metadata("provider-a", ModelMetadataInferenceRequest(
        model_id="new-family-model", family_group="new-family", capability_tags=["reasoning"],
    ))
    cloud = enrich_discovered_models([model("new-family-model", "new-family", {"features": ["reasoning"]})],
                                    rules_repository=repository)[0]
    assert manual.capability_tags == list(cloud.capability_tags) == ["reasoning", "vision"]
    assert not store.provider_file("provider-a", "models.json").exists()


def test_user_saved_tags_are_not_merged_back_on_edit_or_runtime_lookup(store):
    catalog = ProviderCatalogRepository(store)
    saved_models = ProviderCustomModelRepository(store)
    service = ProviderCustomModelService(catalog, saved_models)
    values = dict(provider_id="provider-a", model_id="new-family-model", display_name="Name", family_group="new-family",
                  note="", price_currency="CNY", input_price_per_million=None, cache_hit_price_per_million=None,
                  output_price_per_million=None)
    service.save_model(ProviderCustomModelSaveInput(**values, capability_tags=("vision",)))
    saved = service.save_model(ProviderCustomModelSaveInput(**values, capability_tags=()))
    runtime = LlmRuntimeCapabilitiesService(catalog, saved_models, ProviderAdaptationRulesRepository(store))
    assert saved.capability_tags == ()
    assert runtime.get_capabilities(provider_id="provider-a", model_id=values["model_id"]).input_modalities == ("text",)
    assert enrich_discovered_model(model(values["model_id"], "new-family"),
                                   rules_repository=ProviderAdaptationRulesRepository(store)).capability_tags == ("vision",)
    assert saved_models.get_model(provider_id="provider-a", model_id=values["model_id"]).capability_tags == ()


@pytest.mark.parametrize("payload", [
    {"capabilities": {"inputModalities": ["text", "image"]}},
    {"capabilityTags": ["not-a-capability"]},
])
def test_rules_reject_removed_or_invalid_fields(store, payload):
    store.write_provider_file("provider-a", "provider-rules.json", {"schemaVersion": 1, **payload})
    with pytest.raises(ProviderFileStoreError):
        ProviderAdaptationRulesRepository(store).resolve(provider_id="provider-a", model_id="unknown")
