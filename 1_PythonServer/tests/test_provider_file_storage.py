import json
import sqlite3
from dataclasses import replace

import pytest

from app.core.errors import BadRequestError, NotFoundError
from app.domain.llm.provider_catalog import (
    AuthScheme,
    ModelDiscoveryStrategy,
    ProviderProtocolFamily,
)
from app.domain.llm.reasoning_replay import ReasoningReplayMode
from app.infra.database import (
    ensure_database_schema,
)
from app.repositories.llm.provider_catalog_deletion_repository import (
    ProviderCatalogDeletionRepository,
)
from app.repositories.llm.provider_catalog_repository import ProviderCatalogRepository
from app.repositories.llm.provider_cloud_model_repository import ProviderCloudModelRepository
from app.repositories.llm.provider_config_repository import ProviderConfigRepository
from app.repositories.llm.provider_custom_model_repository import ProviderCustomModelRepository
from app.repositories.llm.provider_file_store import ProviderFileStore
from app.schemas.llm.provider_catalog import (
    ProviderCatalogCreateRequest,
    ProviderCatalogEntryResponse,
)
from app.services.llm.provider.catalog_mutation import ProviderCatalogMutationService
from app.services.llm.provider.preset_catalog import get_provider_endpoint_preset
from app.services.llm.provider.storage_bootstrap import ensure_provider_file_storage
from app.services.llm.provider.storage_actions import ProviderStorageActionsService


def test_preset_provider_uses_same_update_delete_rules_and_stays_deleted(tmp_path):
    providers_path = tmp_path / "providers"
    database_path = tmp_path / "tiance.db"
    ensure_provider_file_storage(providers_path)
    store = ProviderFileStore(providers_path)
    catalog = ProviderCatalogRepository(store)
    mutation = ProviderCatalogMutationService(
        catalog,
        ProviderCloudModelRepository(store),
        ProviderCatalogDeletionRepository(catalog),
    )

    openai = catalog.get_entry("openai")
    assert openai is not None
    assert openai.endpoints.text_generation_url_template == (
        "https://api.openai.com/v1/responses"
    )
    assert openai.endpoints.model_discovery_url == "https://api.openai.com/v1/models"

    deepseek = catalog.get_entry("deepseek")
    assert deepseek is not None
    assert deepseek.protocol_family == ProviderProtocolFamily.OPENAI_COMPATIBLE
    assert deepseek.endpoints.api_base_url == (
        "https://api.deepseek.com/chat/completions"
    )
    assert deepseek.model_discovery_strategy == ModelDiscoveryStrategy.OPENAI_MODELS
    assert deepseek.endpoints.generation_urls[
        ProviderProtocolFamily.OPENAI_RESPONSES
    ] == "https://api.deepseek.com/v1/responses"
    assert deepseek.endpoints.generation_urls[
        ProviderProtocolFamily.ANTHROPIC_MESSAGES
    ] == "https://api.deepseek.com/anthropic/v1/messages"
    assert deepseek.generation_auth_schemes[
        ProviderProtocolFamily.ANTHROPIC_MESSAGES
    ] == AuthScheme.X_API_KEY
    moonshot = catalog.get_entry("moonshot")
    assert moonshot is not None
    assert moonshot.generation_auth_schemes[
        ProviderProtocolFamily.ANTHROPIC_MESSAGES
    ] == AuthScheme.BEARER_TOKEN

    anthropic = mutation.update_provider(
        "deepseek",
        display_name=None,
        protocol_family=ProviderProtocolFamily.ANTHROPIC_MESSAGES,
    )
    assert anthropic.endpoints.api_base_url == (
        "https://api.deepseek.com/anthropic/v1/messages"
    )
    assert anthropic.model_discovery_strategy == ModelDiscoveryStrategy.OPENAI_MODELS
    native_anthropic = catalog.get_entry("anthropic")
    assert native_anthropic is not None
    assert (
        native_anthropic.model_discovery_strategy
        == ModelDiscoveryStrategy.ANTHROPIC_MODELS
    )
    responses = mutation.update_provider(
        "deepseek",
        display_name="DeepSeek Local",
        protocol_family=ProviderProtocolFamily.OPENAI_RESPONSES,
    )
    assert responses.endpoints.api_base_url == "https://api.deepseek.com/v1/responses"
    assert responses.auth_scheme == AuthScheme.BEARER_TOKEN
    restored = mutation.update_provider(
        "deepseek",
        display_name=None,
        protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE,
    )
    assert restored.endpoints.api_base_url == "https://api.deepseek.com/chat/completions"
    mutation.delete_provider("deepseek")
    ensure_provider_file_storage(providers_path)

    assert catalog.get_entry("deepseek") is None
    settings = json.loads(
        (providers_path / "provider-settings.json").read_text(encoding="utf-8")
    )
    assert "deepseek" not in settings["providerOrder"]


@pytest.mark.parametrize("broken_manifest", [None, "{not-json"])
def test_provider_directory_can_be_deleted_when_manifest_is_missing_or_invalid(
    tmp_path,
    broken_manifest,
):
    providers_path = tmp_path / "providers"
    database_path = tmp_path / "tiance.db"
    ensure_provider_file_storage(providers_path)
    store = ProviderFileStore(providers_path)
    catalog = ProviderCatalogRepository(store)
    mutation = ProviderCatalogMutationService(
        catalog,
        ProviderCloudModelRepository(store),
        ProviderCatalogDeletionRepository(catalog),
    )
    provider_root = providers_path / "deepseek"
    manifest_path = provider_root / "provider.json"
    if broken_manifest is None:
        manifest_path.unlink()
    else:
        manifest_path.write_text(broken_manifest, encoding="utf-8")

    mutation.delete_provider("deepseek")

    assert not provider_root.exists()
    settings = json.loads(
        (providers_path / "provider-settings.json").read_text(encoding="utf-8")
    )
    assert "deepseek" not in settings["providerOrder"]


def test_preset_provider_response_keeps_factory_endpoints_separate_from_runtime_data(
    tmp_path,
):
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path)
    store = ProviderFileStore(providers_path)
    catalog = ProviderCatalogRepository(store)
    deepseek = catalog.get_entry("deepseek")
    assert deepseek is not None

    manifest = store.read_provider_file("deepseek", "provider.json")
    assert manifest is not None
    manifest["generationUrls"]["anthropic_messages"] = (
        "https://proxy.example/anthropic/messages"
    )
    store.write_provider_file("deepseek", "provider.json", manifest)

    customized = catalog.get_entry("deepseek")
    assert customized is not None
    endpoint_preset = get_provider_endpoint_preset("deepseek")
    assert endpoint_preset is not None
    response = ProviderCatalogEntryResponse.from_domain(
        customized,
        preset_generation_urls=endpoint_preset.generation_urls,
        preset_model_discovery_url=endpoint_preset.model_discovery_url,
    )

    assert response.generation_urls[ProviderProtocolFamily.ANTHROPIC_MESSAGES] == (
        "https://proxy.example/anthropic/messages"
    )
    assert response.preset_generation_urls[
        ProviderProtocolFamily.ANTHROPIC_MESSAGES
    ] == "https://api.deepseek.com/anthropic/v1/messages"


def test_deepseek_preset_uses_official_model_list_endpoint(tmp_path):
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path)
    store = ProviderFileStore(providers_path)

    manifest = store.read_provider_file("deepseek", "provider.json")

    assert manifest is not None
    assert manifest["generationUrls"]["openai_compatible"] == (
        "https://api.deepseek.com/chat/completions"
    )
    assert manifest["modelDiscoveryUrl"] == "https://api.deepseek.com/models"


def test_custom_provider_protocol_switch_does_not_guess_generation_url(tmp_path):
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path)
    store = ProviderFileStore(providers_path)
    catalog = ProviderCatalogRepository(store)
    mutation = ProviderCatalogMutationService(
        catalog,
        ProviderCloudModelRepository(store),
        ProviderCatalogDeletionRepository(catalog),
    )
    mutation.create_provider(
        display_name="Local CodeX",
        api_base_url="http://127.0.0.1:46973/v1/chat/completions",
        provider_id="local-codex",
        protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE,
        auth_scheme=AuthScheme.BEARER_TOKEN,
    )

    updated = mutation.update_provider(
        "local-codex",
        display_name=None,
        protocol_family=ProviderProtocolFamily.OPENAI_RESPONSES,
    )

    assert updated.endpoints.api_base_url == ""
    assert updated.endpoints.generation_urls == {
        ProviderProtocolFamily.OPENAI_COMPATIBLE: (
            "http://127.0.0.1:46973/v1/chat/completions"
        )
    }


def test_provider_creation_keeps_model_discovery_url_empty_until_configured(tmp_path):
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path)
    store = ProviderFileStore(providers_path)
    catalog = ProviderCatalogRepository(store)
    mutation = ProviderCatalogMutationService(
        catalog,
        ProviderCloudModelRepository(store),
        ProviderCatalogDeletionRepository(catalog),
    )

    created = mutation.create_provider(
        display_name="Local Responses",
        api_base_url="http://127.0.0.1:8317/v1/responses",
        provider_id="local-responses",
        protocol_family=ProviderProtocolFamily.OPENAI_RESPONSES,
        auth_scheme=AuthScheme.BEARER_TOKEN,
    )

    assert created.endpoints.model_discovery_url is None


def test_provider_creation_accepts_name_only_and_starts_unconfigured(tmp_path):
    payload = ProviderCatalogCreateRequest(display_name="Name Only")
    assert payload.api_base_url == ""

    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path)
    store = ProviderFileStore(providers_path)
    catalog = ProviderCatalogRepository(store)
    mutation = ProviderCatalogMutationService(
        catalog,
        ProviderCloudModelRepository(store),
        ProviderCatalogDeletionRepository(catalog),
    )

    created = mutation.create_provider(
        display_name=payload.display_name,
        api_base_url=payload.api_base_url,
        provider_id="name-only",
        protocol_family=payload.protocol_family,
        auth_scheme=payload.auth_scheme,
    )

    manifest = store.read_provider_file("name-only", "provider.json")
    assert created.endpoints.api_base_url == ""
    assert created.endpoints.generation_urls == {}
    assert manifest is not None
    assert manifest["generationUrls"] == {}
    assert manifest["enabled"] is False


def test_late_save_for_previous_protocol_keeps_new_protocol_url(tmp_path):
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path)
    store = ProviderFileStore(providers_path)
    catalog = ProviderCatalogRepository(store)
    configs = ProviderConfigRepository(store)
    mutation = ProviderCatalogMutationService(
        catalog,
        ProviderCloudModelRepository(store),
        ProviderCatalogDeletionRepository(catalog),
    )
    stale_compatible_config = configs.get_config("grok")
    assert stale_compatible_config is not None

    mutation.update_provider(
        "grok",
        display_name=None,
        protocol_family=ProviderProtocolFamily.OPENAI_RESPONSES,
    )
    stale_generation_urls = dict(stale_compatible_config.generation_urls)
    stale_generation_urls[ProviderProtocolFamily.OPENAI_COMPATIBLE.value] = (
        "https://proxy.example/chat/completions"
    )
    configs.save_config(
        replace(
            stale_compatible_config,
            api_base_url="https://proxy.example/chat/completions",
            generation_urls=stale_generation_urls,
            updated_generation_protocol=(
                ProviderProtocolFamily.OPENAI_COMPATIBLE.value
            ),
        )
    )

    saved = configs.get_config("grok")
    assert saved is not None
    assert saved.protocol_family == ProviderProtocolFamily.OPENAI_RESPONSES.value
    assert saved.api_base_url == "https://api.x.ai/v1/responses"
    assert saved.generation_urls == {
        "openai_compatible": "https://proxy.example/chat/completions",
        "openai_responses": "https://api.x.ai/v1/responses",
    }


def test_provider_reasoning_replay_mode_is_persisted(tmp_path):
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path)
    store = ProviderFileStore(providers_path)
    configs = ProviderConfigRepository(store)
    current = configs.get_config("grok")
    assert current is not None

    configs.save_config(
        replace(current, reasoning_replay_mode=ReasoningReplayMode.ALWAYS)
    )

    saved = configs.get_config("grok")
    manifest = store.read_provider_file("grok", "provider.json")
    assert saved is not None
    assert saved.reasoning_replay_mode == ReasoningReplayMode.ALWAYS
    assert manifest is not None
    assert manifest["reasoningReplayMode"] == ReasoningReplayMode.ALWAYS.value


def test_provider_config_list_isolates_one_invalid_provider(tmp_path):
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path)
    store = ProviderFileStore(providers_path)
    manifest = store.read_provider_file("deepseek", "provider.json")
    assert manifest is not None
    manifest.pop("reasoningReplayMode", None)
    store.write_provider_file("deepseek", "provider.json", manifest)

    configs, failures = ProviderConfigRepository(store).list_config_results()

    assert "deepseek" not in {config.provider_id for config in configs}
    assert {failure.provider_id for failure in failures} == {"deepseek"}
    assert "openai" in {config.provider_id for config in configs}


def test_provider_catalog_list_isolates_one_invalid_provider(tmp_path):
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path)
    store = ProviderFileStore(providers_path)
    manifest = store.read_provider_file("deepseek", "provider.json")
    assert manifest is not None
    manifest.pop("displayName", None)
    store.write_provider_file("deepseek", "provider.json", manifest)

    entries, failures = ProviderCatalogRepository(store).list_entry_results()

    assert "deepseek" not in {entry.provider_id for entry in entries}
    assert {failure.provider_id for failure in failures} == {"deepseek"}
    assert "openai" in {entry.provider_id for entry in entries}


def test_provider_directory_reveal_is_limited_to_existing_provider_package(tmp_path):
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path)
    store = ProviderFileStore(providers_path)
    revealed_paths = []
    service = ProviderStorageActionsService(store, revealed_paths.append)

    service.reveal_provider_directory("deepseek")

    assert revealed_paths == [providers_path / "deepseek"]
    with pytest.raises(NotFoundError, match="was not found"):
        service.reveal_provider_directory("provider_missing")
