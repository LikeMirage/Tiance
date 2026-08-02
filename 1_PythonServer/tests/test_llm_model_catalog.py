from app.domain.llm.provider_config import ProviderConfig
from app.domain.llm.provider_custom_model import ProviderCustomModel
from app.repositories.llm.provider_file_store import ProviderFileStore
from app.repositories.llm.provider_catalog_repository import ProviderCatalogRepository
from app.repositories.llm.provider_config_repository import ProviderConfigRepository
from app.repositories.llm.provider_custom_model_repository import (
    ProviderCustomModelRepository,
)
from app.services.llm.model_catalog import LlmModelCatalogService
from app.services.llm.provider.storage_bootstrap import ensure_provider_file_storage


def test_model_catalog_lists_enabled_added_chat_models(tmp_path):
    service, config_repository, custom_model_repository = _create_service(tmp_path)
    _save_provider_config(config_repository, provider_id="deepseek", enabled=True)
    _save_provider_config(config_repository, provider_id="dmxapi", enabled=False)
    custom_model_repository.save_model(
        _custom_model("deepseek", "deepseek-v4-flash", tags=("reasoning",))
    )
    custom_model_repository.save_model(
        _custom_model("deepseek", "text-embedding", tags=("embedding",))
    )
    custom_model_repository.save_model(
        _custom_model("dmxapi", "proxy-chat", tags=())
    )

    models = service.list_models(kind="chat")

    assert [model.model_id for model in models] == ["deepseek-v4-flash"]
    assert models[0].provider_id == "deepseek"
    assert models[0].provider_label == "DeepSeek"
    assert models[0].provider_enabled is True
    assert models[0].source == "added"


def test_model_catalog_filters_functional_and_vision_models(tmp_path):
    service, config_repository, custom_model_repository = _create_service(tmp_path)
    _save_provider_config(config_repository, provider_id="deepseek", enabled=True)
    custom_model_repository.save_model(
        _custom_model("deepseek", "text-model", tags=("reasoning",))
    )
    custom_model_repository.save_model(
        _custom_model("deepseek", "vision-model", tags=("vision",))
    )
    custom_model_repository.save_model(
        _custom_model("deepseek", "image-generator", tags=("image_generation",))
    )

    text_models = service.list_models(kind="functional_text")
    vision_models = service.list_models(kind="vision")

    assert [model.model_id for model in text_models] == ["text-model", "vision-model"]
    assert [model.model_id for model in vision_models] == ["vision-model"]


def _create_service(tmp_path):
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path, tmp_path / "tiance.db")
    store = ProviderFileStore(providers_path)
    catalog_repository = ProviderCatalogRepository(store)
    config_repository = ProviderConfigRepository(store)
    custom_model_repository = ProviderCustomModelRepository(store)
    service = LlmModelCatalogService(
        catalog_repository,
        config_repository,
        custom_model_repository,
    )
    return service, config_repository, custom_model_repository


def _save_provider_config(
    config_repository: ProviderConfigRepository,
    *,
    provider_id: str,
    enabled: bool,
) -> None:
    config_repository.save_config(
        ProviderConfig(
            provider_id=provider_id,
            api_base_url="https://example.test",
            enabled=enabled,
            api_keys=(),
            created_at="2026-05-16T00:00:00+00:00",
            updated_at="2026-05-16T00:00:00+00:00",
        )
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
        note="",
        created_at="2026-05-16T00:00:00+00:00",
        updated_at="2026-05-16T00:00:00+00:00",
    )
