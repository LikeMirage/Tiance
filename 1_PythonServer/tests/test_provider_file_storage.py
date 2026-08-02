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
from app.domain.llm.provider_endpoint_templates import (
    derive_model_discovery_url,
    retarget_generation_url,
    upgrade_unambiguous_legacy_generation_url,
)
from app.infra.database import (
    ensure_database_schema,
    prepare_database_for_provider_file_migration,
)
from app.repositories.llm.provider_catalog_deletion_repository import (
    ProviderCatalogDeletionRepository,
)
from app.repositories.llm.provider_catalog_repository import ProviderCatalogRepository
from app.repositories.llm.provider_cloud_model_repository import ProviderCloudModelRepository
from app.repositories.llm.provider_config_repository import ProviderConfigRepository
from app.repositories.llm.provider_custom_model_repository import ProviderCustomModelRepository
from app.repositories.llm.provider_file_store import ProviderFileStore
from app.schemas.llm.provider_catalog import ProviderCatalogEntryResponse
from app.services.llm.provider.catalog_mutation import ProviderCatalogMutationService
from app.services.llm.provider.preset_catalog import get_provider_endpoint_preset
from app.services.llm.provider.storage_bootstrap import ensure_provider_file_storage
from app.services.llm.provider.storage_actions import ProviderStorageActionsService


def test_legacy_provider_data_migrates_to_file_packages_and_drops_sqlite_tables(tmp_path):
    database_path = tmp_path / "tiance.db"
    providers_path = tmp_path / "providers"
    prepare_database_for_provider_file_migration(database_path)
    _insert_legacy_provider_data(database_path)

    ensure_provider_file_storage(providers_path, database_path)
    ensure_database_schema(database_path)

    store = ProviderFileStore(providers_path)
    catalog = ProviderCatalogRepository(store)
    configs = ProviderConfigRepository(store)
    models = ProviderCustomModelRepository(store)

    provider = catalog.get_entry("custom-e0e1c9c5")
    config = configs.get_config("custom-e0e1c9c5")
    model = models.get_model(provider_id="custom-e0e1c9c5", model_id="proxy-model")
    assert provider is not None
    assert provider.display_name == "codex"
    assert provider.protocol_family == ProviderProtocolFamily.OPENAI_COMPATIBLE
    assert config is not None
    assert config.api_base_url == "http://127.0.0.1:46973/v1/chat/completions"
    manifest = store.read_provider_file("custom-e0e1c9c5", "provider.json")
    assert manifest is not None
    assert "apiBaseUrl" not in manifest
    assert manifest["generationUrls"] == {
        "openai_compatible": "http://127.0.0.1:46973/v1/chat/completions"
    }
    assert manifest["generationAuthSchemes"] == {
        "openai_compatible": "bearer_token"
    }
    assert manifest["modelDiscoveryAuthScheme"] == "bearer_token"
    assert "authScheme" not in manifest
    assert config.enabled is True
    assert config.api_keys[0].api_key_ciphertext == "win-dpapi-user-v1:test-ciphertext"
    assert model is not None
    assert model.capability_tags == ("reasoning", "vision")
    assert catalog.list_ordered_provider_ids()[0] == "custom-e0e1c9c5"

    with sqlite3.connect(database_path) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "custom_provider_catalog" not in table_names
    assert "provider_configs" not in table_names
    assert "provider_custom_models" not in table_names


def test_preset_provider_uses_same_update_delete_rules_and_stays_deleted(tmp_path):
    providers_path = tmp_path / "providers"
    database_path = tmp_path / "tiance.db"
    ensure_provider_file_storage(providers_path, database_path)
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
    assert deepseek.model_discovery_strategy == ModelDiscoveryStrategy.OPENAI_MODELS
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
    unconfigured = mutation.update_provider(
        "deepseek",
        display_name="DeepSeek Local",
        protocol_family=ProviderProtocolFamily.OPENAI_RESPONSES,
    )
    assert unconfigured.endpoints.api_base_url == ""
    assert unconfigured.auth_scheme == AuthScheme.BEARER_TOKEN
    unconfigured_manifest = store.read_provider_file("deepseek", "provider.json")
    assert unconfigured_manifest is not None
    assert unconfigured_manifest["enabled"] is False
    restored = mutation.update_provider(
        "deepseek",
        display_name=None,
        protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE,
    )
    assert restored.endpoints.api_base_url == "https://api.deepseek.com/chat/completions"
    mutation.delete_provider("deepseek")
    ensure_provider_file_storage(providers_path, database_path)

    assert catalog.get_entry("deepseek") is None
    settings = json.loads(
        (providers_path / "provider-settings.json").read_text(encoding="utf-8")
    )
    assert "deepseek" not in settings["providerOrder"]


def test_startup_repairs_partial_provider_manifest_even_when_versions_are_current(
    tmp_path,
):
    providers_path = tmp_path / "providers"
    database_path = tmp_path / "tiance.db"
    ensure_provider_file_storage(providers_path, database_path)
    store = ProviderFileStore(providers_path)
    manifest = store.read_provider_file("deepseek", "provider.json")
    assert manifest is not None
    original_urls = dict(manifest["generationUrls"])
    credentials_path = providers_path / "deepseek" / "credentials.json"
    original_credentials = credentials_path.read_bytes()

    manifest.pop("modelDiscoveryStrategy")
    manifest.pop("modelDiscoveryAuthScheme")
    store.write_provider_file("deepseek", "provider.json", manifest)

    ensure_provider_file_storage(providers_path, database_path)

    repaired = store.read_provider_file("deepseek", "provider.json")
    assert repaired is not None
    assert repaired["modelDiscoveryStrategy"] == "openai_models"
    assert repaired["modelDiscoveryAuthScheme"] == "bearer_token"
    assert repaired["generationUrls"] == original_urls
    assert credentials_path.read_bytes() == original_credentials


def test_preset_provider_response_keeps_factory_endpoints_separate_from_runtime_data(
    tmp_path,
):
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path, tmp_path / "tiance.db")
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


@pytest.mark.parametrize(
    ("generation_url", "protocol_family", "expected"),
    (
        (
            "http://127.0.0.1:8317/v1/responses",
            ProviderProtocolFamily.OPENAI_RESPONSES,
            "http://127.0.0.1:8317/v1/models",
        ),
        (
            "https://example.test/api/v3/chat/completions",
            ProviderProtocolFamily.OPENAI_COMPATIBLE,
            "https://example.test/api/v3/models",
        ),
        (
            "https://example.test/v1/messages",
            ProviderProtocolFamily.ANTHROPIC_MESSAGES,
            "https://example.test/v1/models",
        ),
        (
            "https://example.test/v1beta/models/{model}:{action}",
            ProviderProtocolFamily.GEMINI_GENERATE_CONTENT,
            "https://example.test/v1beta/models",
        ),
        (
            "https://example.test/v1",
            ProviderProtocolFamily.OPENAI_COMPATIBLE,
            "https://example.test/v1/models",
        ),
    ),
)
def test_model_discovery_url_default_is_derived_from_generation_url(
    generation_url,
    protocol_family,
    expected,
):
    assert derive_model_discovery_url(generation_url, protocol_family) == expected


@pytest.mark.parametrize(
    ("legacy_url", "protocol_family", "expected"),
    (
        (
            "http://127.0.0.1:46973/v1",
            ProviderProtocolFamily.OPENAI_COMPATIBLE,
            "http://127.0.0.1:46973/v1/chat/completions",
        ),
        (
            "https://api.deepseek.com",
            ProviderProtocolFamily.OPENAI_COMPATIBLE,
            "https://api.deepseek.com/chat/completions",
        ),
        (
            "http://127.0.0.1:46973/v1",
            ProviderProtocolFamily.OPENAI_RESPONSES,
            "http://127.0.0.1:46973/v1/responses",
        ),
        (
            "https://api.anthropic.com",
            ProviderProtocolFamily.ANTHROPIC_MESSAGES,
            "https://api.anthropic.com/v1/messages",
        ),
        (
            "https://generativelanguage.googleapis.com",
            ProviderProtocolFamily.GEMINI_GENERATE_CONTENT,
            "https://generativelanguage.googleapis.com/v1beta/models/{model}:{action}",
        ),
        (
            "https://example.test/custom/inference",
            ProviderProtocolFamily.OPENAI_COMPATIBLE,
            "https://example.test/custom/inference",
        ),
        (
            "https://example.test/v1/responses",
            ProviderProtocolFamily.OPENAI_RESPONSES,
            "https://example.test/v1/responses",
        ),
    ),
)
def test_unambiguous_legacy_generation_url_upgrade(
    legacy_url,
    protocol_family,
    expected,
):
    assert (
        upgrade_unambiguous_legacy_generation_url(legacy_url, protocol_family)
        == expected
    )


def test_protocol_switch_retargets_recognized_generation_endpoint_only():
    assert retarget_generation_url(
        "https://example.test/v1/chat/completions",
        ProviderProtocolFamily.OPENAI_COMPATIBLE,
        ProviderProtocolFamily.OPENAI_RESPONSES,
    ) == "https://example.test/v1/responses"
    assert retarget_generation_url(
        "https://example.test/custom/inference",
        ProviderProtocolFamily.OPENAI_COMPATIBLE,
        ProviderProtocolFamily.OPENAI_RESPONSES,
    ) == "https://example.test/custom/inference"


def test_custom_provider_protocol_switch_retargets_recognized_generation_url(tmp_path):
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path, tmp_path / "tiance.db")
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

    assert updated.endpoints.api_base_url == "http://127.0.0.1:46973/v1/responses"


def test_provider_startup_repairs_missing_active_protocol_url_when_unambiguous(tmp_path):
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path, tmp_path / "tiance.db")
    store = ProviderFileStore(providers_path)
    manifest = store.read_provider_file("openai", "provider.json")
    assert manifest is not None
    manifest["protocolFamily"] = "openai_responses"
    manifest["generationUrls"] = {
        "openai_compatible": "http://127.0.0.1:46973/v1/chat/completions",
    }
    store.write_provider_file("openai", "provider.json", manifest)

    ensure_provider_file_storage(providers_path, tmp_path / "tiance.db")

    repaired = store.read_provider_file("openai", "provider.json")
    assert repaired is not None
    assert repaired["generationUrls"]["openai_responses"] == (
        "http://127.0.0.1:46973/v1/responses"
    )


def test_provider_creation_keeps_model_discovery_url_empty_until_configured(tmp_path):
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path, tmp_path / "tiance.db")
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


def test_late_save_for_previous_protocol_keeps_new_protocol_url(tmp_path):
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path, tmp_path / "tiance.db")
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


def test_existing_empty_model_discovery_url_is_migrated_without_overwriting_custom_url(
    tmp_path,
):
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path, tmp_path / "tiance.db")
    store = ProviderFileStore(providers_path)

    openai_manifest = store.read_provider_file("openai", "provider.json")
    assert openai_manifest is not None
    openai_manifest["generationUrls"]["openai_responses"] = (
        "http://127.0.0.1:8317/v1/responses"
    )
    openai_manifest["modelDiscoveryUrl"] = None
    store.write_provider_file("openai", "provider.json", openai_manifest)

    deepseek_manifest = store.read_provider_file("deepseek", "provider.json")
    assert deepseek_manifest is not None
    deepseek_manifest["modelDiscoveryUrl"] = "https://catalog.example/models"
    store.write_provider_file("deepseek", "provider.json", deepseek_manifest)

    settings = store.read_settings()
    assert settings is not None
    settings.pop("modelDiscoveryUrlAutofillVersion", None)
    store.write_settings(settings)

    ensure_provider_file_storage(providers_path, tmp_path / "tiance.db")

    migrated_openai = store.read_provider_file("openai", "provider.json")
    migrated_deepseek = store.read_provider_file("deepseek", "provider.json")
    assert migrated_openai is not None
    assert migrated_deepseek is not None
    assert migrated_openai["modelDiscoveryUrl"] == "http://127.0.0.1:8317/v1/models"
    assert migrated_deepseek["modelDiscoveryUrl"] == "https://catalog.example/models"


def test_existing_legacy_generation_urls_are_migrated_once(tmp_path):
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path, tmp_path / "tiance.db")
    store = ProviderFileStore(providers_path)

    openai_manifest = store.read_provider_file("openai", "provider.json")
    deepseek_manifest = store.read_provider_file("deepseek", "provider.json")
    dmxapi_manifest = store.read_provider_file("dmxapi", "provider.json")
    assert openai_manifest is not None
    assert deepseek_manifest is not None
    assert dmxapi_manifest is not None
    openai_manifest["apiBaseUrl"] = "http://127.0.0.1:8317/v1"
    openai_manifest.pop("generationUrls", None)
    deepseek_manifest["apiBaseUrl"] = "https://custom.example/inference"
    deepseek_manifest.pop("generationUrls", None)
    dmxapi_manifest["apiBaseUrl"] = "https://www.dmxapi.cn"
    dmxapi_manifest.pop("generationUrls", None)
    store.write_provider_file("openai", "provider.json", openai_manifest)
    store.write_provider_file("deepseek", "provider.json", deepseek_manifest)
    store.write_provider_file("dmxapi", "provider.json", dmxapi_manifest)

    settings = store.read_settings()
    assert settings is not None
    settings.pop("generationUrlContractVersion", None)
    settings.pop("generationUrlStorageVersion", None)
    store.write_settings(settings)

    ensure_provider_file_storage(providers_path, tmp_path / "tiance.db")

    migrated_openai = store.read_provider_file("openai", "provider.json")
    migrated_deepseek = store.read_provider_file("deepseek", "provider.json")
    migrated_dmxapi = store.read_provider_file("dmxapi", "provider.json")
    migrated_settings = store.read_settings()
    assert migrated_openai is not None
    assert migrated_deepseek is not None
    assert migrated_dmxapi is not None
    assert migrated_settings is not None
    assert "apiBaseUrl" not in migrated_openai
    assert "apiBaseUrl" not in migrated_deepseek
    assert "apiBaseUrl" not in migrated_dmxapi
    assert migrated_openai["generationUrls"]["openai_responses"] == (
        "http://127.0.0.1:8317/v1/responses"
    )
    assert migrated_deepseek["generationUrls"]["openai_compatible"] == (
        "https://custom.example/inference"
    )
    assert migrated_dmxapi["generationUrls"]["openai_compatible"] == (
        "https://www.dmxapi.cn/v1/chat/completions"
    )
    assert migrated_settings["generationUrlContractVersion"] == 1
    assert migrated_settings["generationUrlStorageVersion"] == 1


def test_preset_generation_url_defaults_repair_auto_generated_legacy_url(tmp_path):
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path, tmp_path / "tiance.db")
    store = ProviderFileStore(providers_path)

    deepseek_manifest = store.read_provider_file("deepseek", "provider.json")
    assert deepseek_manifest is not None
    deepseek_manifest["generationUrls"]["anthropic_messages"] = (
        "https://api.deepseek.com/messages"
    )
    store.write_provider_file("deepseek", "provider.json", deepseek_manifest)

    settings = store.read_settings()
    assert settings is not None
    settings.pop("presetGenerationUrlDefaultsVersion", None)
    store.write_settings(settings)

    ensure_provider_file_storage(providers_path, tmp_path / "tiance.db")

    migrated = store.read_provider_file("deepseek", "provider.json")
    migrated_settings = store.read_settings()
    assert migrated is not None
    assert migrated_settings is not None
    assert migrated["generationUrls"]["anthropic_messages"] == (
        "https://api.deepseek.com/anthropic/v1/messages"
    )
    assert migrated_settings["presetGenerationUrlDefaultsVersion"] == 2


def test_preset_generation_url_defaults_add_supported_protocols_and_remove_old_guess(
    tmp_path,
):
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path, tmp_path / "tiance.db")
    store = ProviderFileStore(providers_path)

    grok_manifest = store.read_provider_file("grok", "provider.json")
    deepseek_manifest = store.read_provider_file("deepseek", "provider.json")
    assert grok_manifest is not None
    assert deepseek_manifest is not None
    grok_manifest["generationUrls"].pop("openai_responses")
    deepseek_manifest["generationUrls"]["openai_responses"] = (
        "https://api.deepseek.com/responses"
    )
    store.write_provider_file("grok", "provider.json", grok_manifest)
    store.write_provider_file("deepseek", "provider.json", deepseek_manifest)

    settings = store.read_settings()
    assert settings is not None
    settings["presetGenerationUrlDefaultsVersion"] = 1
    store.write_settings(settings)

    ensure_provider_file_storage(providers_path, tmp_path / "tiance.db")

    migrated_grok = store.read_provider_file("grok", "provider.json")
    migrated_deepseek = store.read_provider_file("deepseek", "provider.json")
    assert migrated_grok is not None
    assert migrated_deepseek is not None
    assert migrated_grok["generationUrls"]["openai_responses"] == (
        "https://api.x.ai/v1/responses"
    )
    assert "openai_responses" not in migrated_deepseek["generationUrls"]


def test_preset_generation_url_defaults_preserve_user_entered_base_url(tmp_path):
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path, tmp_path / "tiance.db")
    store = ProviderFileStore(providers_path)

    deepseek_manifest = store.read_provider_file("deepseek", "provider.json")
    assert deepseek_manifest is not None
    deepseek_manifest["generationUrls"]["anthropic_messages"] = (
        "https://api.deepseek.com/anthropic"
    )
    store.write_provider_file("deepseek", "provider.json", deepseek_manifest)

    settings = store.read_settings()
    assert settings is not None
    settings.pop("presetGenerationUrlDefaultsVersion", None)
    store.write_settings(settings)

    ensure_provider_file_storage(providers_path, tmp_path / "tiance.db")

    migrated = store.read_provider_file("deepseek", "provider.json")
    assert migrated is not None
    assert migrated["generationUrls"]["anthropic_messages"] == (
        "https://api.deepseek.com/anthropic"
    )


def test_preset_generation_url_defaults_do_not_replace_custom_proxy_urls(tmp_path):
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path, tmp_path / "tiance.db")
    store = ProviderFileStore(providers_path)

    deepseek_manifest = store.read_provider_file("deepseek", "provider.json")
    assert deepseek_manifest is not None
    deepseek_manifest["generationUrls"] = {
        "openai_compatible": "https://proxy.example/v1/chat/completions",
        "anthropic_messages": "https://proxy.example/custom/messages",
    }
    store.write_provider_file("deepseek", "provider.json", deepseek_manifest)

    settings = store.read_settings()
    assert settings is not None
    settings.pop("presetGenerationUrlDefaultsVersion", None)
    store.write_settings(settings)

    ensure_provider_file_storage(providers_path, tmp_path / "tiance.db")

    migrated = store.read_provider_file("deepseek", "provider.json")
    assert migrated is not None
    assert migrated["generationUrls"] == {
        "openai_compatible": "https://proxy.example/v1/chat/completions",
        "anthropic_messages": "https://proxy.example/custom/messages",
    }


def test_provider_directory_reveal_is_limited_to_existing_provider_package(tmp_path):
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path, tmp_path / "tiance.db")
    store = ProviderFileStore(providers_path)
    revealed_paths = []
    service = ProviderStorageActionsService(store, revealed_paths.append)

    service.reveal_provider_directory("deepseek")

    assert revealed_paths == [providers_path / "deepseek"]
    with pytest.raises(NotFoundError, match="was not found"):
        service.reveal_provider_directory("provider_missing")


def _insert_legacy_provider_data(database_path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO custom_provider_catalog (
                provider_id, display_name, upstream_key, protocol_family,
                auth_scheme, supports_custom_base_url, api_base_url,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "custom-e0e1c9c5",
                "codex",
                "custom-e0e1c9c5",
                "openai_compatible",
                "bearer_token",
                1,
                "http://127.0.0.1:46973/v1",
                "2026-07-01T00:00:00+00:00",
                "2026-07-02T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO provider_configs (
                provider_id, api_base_url, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "custom-e0e1c9c5",
                "http://127.0.0.1:46973/v1",
                1,
                "2026-07-01T00:00:00+00:00",
                "2026-07-02T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO provider_config_api_keys (
                key_id, provider_id, api_key_hint, api_key_ciphertext,
                poll_weight, sort_order, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "primary",
                "custom-e0e1c9c5",
                "********test",
                "win-dpapi-user-v1:test-ciphertext",
                1,
                0,
                "2026-07-01T00:00:00+00:00",
                "2026-07-02T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO provider_custom_models (
                provider_id, model_id, display_name, family_group,
                capability_tags, note, price_currency,
                input_price_per_million, cache_hit_price_per_million,
                output_price_per_million, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "custom-e0e1c9c5",
                "proxy-model",
                "Proxy Model",
                "proxy",
                '["reasoning", "vision"]',
                "",
                "CNY",
                1.0,
                0.1,
                2.0,
                "2026-07-01T00:00:00+00:00",
                "2026-07-02T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO provider_catalog_order (provider_id, sort_order, updated_at)
            VALUES (?, ?, ?)
            """,
            ("custom-e0e1c9c5", 0, "2026-07-02T00:00:00+00:00"),
        )
