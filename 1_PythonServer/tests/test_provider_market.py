import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.core.errors import BadRequestError
from app.infra.provider_market import ProviderPackageArchive
from app.repositories.llm.provider_catalog_repository import ProviderCatalogRepository
from app.repositories.llm.provider_file_store import ProviderFileStore
from app.repositories.llm.provider_market_cache_repository import ProviderMarketCacheRepository
from app.repositories.llm.provider_market_settings_repository import (
    DEFAULT_PROVIDER_MARKET_SOURCE,
    ProviderMarketSettingsRepository,
)
from app.schemas.llm.provider_market import ProviderMarketEntry, ProviderPackageManifest
from app.services.application.provider_market import ProviderMarketApplicationService


class _CloudModels:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_provider_cache(self, provider_id: str) -> None:
        self.deleted.append(provider_id)


class _WorkspaceRegistry:
    def __init__(self) -> None:
        self.sync_count = 0

    def synchronize(self) -> None:
        self.sync_count += 1


def test_provider_market_package_accepts_only_declarative_public_files(tmp_path) -> None:
    archive_path = tmp_path / "provider.zip"
    files = _package_files("sample-provider", managed_model_ids=["sample-model"])
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            archive.writestr(
                f"sample-provider/{name}",
                json.dumps(payload, ensure_ascii=False),
            )

    extracted = ProviderPackageArchive().validate_and_extract(
        archive_path=archive_path,
        staging_root=tmp_path / "staging",
        market_entry=_entry(),
    )

    assert {path.name for path in extracted.iterdir()} == set(files)
    assert "credentials.json" not in files


def test_provider_market_update_preserves_local_secrets_state_and_models(tmp_path) -> None:
    providers_root = tmp_path / "providers"
    target = providers_root / "sample-provider"
    target.mkdir(parents=True)
    previous_manifest = _package_files(
        "sample-provider",
        managed_model_ids=["old-market-model"],
    )["manifest.json"]
    _write_json(target / "manifest.json", previous_manifest)
    provider_payload = _provider_payload("sample-provider")
    provider_payload.update({"enabled": True, "createdAt": "old", "updatedAt": "old"})
    _write_json(target / "provider.json", provider_payload)
    _write_json(target / "provider-rules.json", _empty_provider_rules())
    _write_json(target / "model-rules.json", _empty_model_rules())
    _write_json(target / "credentials.json", {
        "schemaVersion": 1,
        "items": [{"ciphertext": "encrypted-secret"}],
    })
    _write_json(target / "models.json", {
        "schemaVersion": 1,
        "items": [
            _model("old-market-model"),
            _model("local-model"),
        ],
    })

    package_root = tmp_path / "package" / "sample-provider"
    package_root.mkdir(parents=True)
    for name, payload in _package_files(
        "sample-provider",
        managed_model_ids=["new-market-model"],
    ).items():
        _write_json(package_root / name, payload)

    store = ProviderFileStore(providers_root)
    cloud_models = _CloudModels()
    workspace = _WorkspaceRegistry()
    service = ProviderMarketApplicationService(
        app_version="0.1.0",
        providers_root=providers_root,
        settings_repository=ProviderMarketSettingsRepository(
            providers_root / "market-settings.json"
        ),
        cache_repository=ProviderMarketCacheRepository(providers_root / ".market-cache"),
        remote_client=object(),
        archive=ProviderPackageArchive(),
        file_store=store,
        catalog_repository=ProviderCatalogRepository(store),
        cloud_model_repository=cloud_models,
        workspace_registry=workspace,
        project_service=object(),
    )

    service._update_installed_provider(
        provider_id="sample-provider",
        package_root=package_root,
        previous_manifest=ProviderPackageManifest.model_validate(previous_manifest),
        backup_root=tmp_path / "backup",
    )

    credentials = json.loads((target / "credentials.json").read_text(encoding="utf-8"))
    provider = json.loads((target / "provider.json").read_text(encoding="utf-8"))
    models = json.loads((target / "models.json").read_text(encoding="utf-8"))["items"]
    assert credentials["items"][0]["ciphertext"] == "encrypted-secret"
    assert provider["enabled"] is True
    assert provider["createdAt"] == "old"
    assert {item["modelId"] for item in models} == {"new-market-model", "local-model"}
    assert cloud_models.deleted == ["sample-provider"]
    assert workspace.sync_count == 1

    mismatched_manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    mismatched_manifest["id"] = "another-provider"
    _write_json(target / "manifest.json", mismatched_manifest)
    assert service._read_local_market_manifest("sample-provider") is None


def test_provider_market_default_source_is_directly_publishable(tmp_path) -> None:
    repository = ProviderMarketSettingsRepository(tmp_path / "market-settings.json")
    assert repository.ensure_settings_file().source == DEFAULT_PROVIDER_MARKET_SOURCE
    assert DEFAULT_PROVIDER_MARKET_SOURCE == "https://likemirage.github.io/Tiance-providers"


def test_provider_market_index_rejects_unsupported_protocol() -> None:
    entry = _entry().model_dump(by_alias=True)
    entry["protocol"] = "unsupported_protocol"

    with pytest.raises(BadRequestError, match="不支持的协议"):
        ProviderMarketApplicationService._validate_index_payload(
            "https://example.com/market",
            {
                "schemaVersion": 1,
                "kind": "tiance-provider-market",
                "name": "示例市场",
                "updatedAt": "2026-08-02T00:00:00Z",
                "providers": [entry],
            },
        )


def _entry() -> ProviderMarketEntry:
    return ProviderMarketEntry.model_validate({
        "id": "sample-provider",
        "name": "示例供应商",
        "version": "1.0.0",
        "author": "LikeMirage",
        "summary": "示例供应商。",
        "license": "CC0-1.0",
        "protocol": "openai_compatible",
        "modelCount": 1,
        "packageUrl": "packages/sample-provider-1.0.0.zip",
        "sha256": "0" * 64,
        "size": 1,
        "compatibility": {"minTianceVersion": "0.1.0"},
    })


def _package_files(provider_id: str, *, managed_model_ids: list[str]):
    return {
        "manifest.json": {
            "schemaVersion": 1,
            "kind": "tiance-provider-package",
            "id": provider_id,
            "name": "示例供应商",
            "version": "1.0.0",
            "author": {"name": "LikeMirage"},
            "summary": "示例供应商。",
            "license": "CC0-1.0",
            "compatibility": {"minTianceVersion": "0.1.0"},
            "managedModelIds": managed_model_ids,
        },
        "provider.json": _provider_payload(provider_id),
        "provider-rules.json": _empty_provider_rules(),
        "model-rules.json": _empty_model_rules(),
        "models.json": {
            "schemaVersion": 1,
            "items": [_model(model_id) for model_id in managed_model_ids],
        },
    }


def _provider_payload(provider_id: str):
    return {
        "schemaVersion": 1,
        "id": provider_id,
        "displayName": "示例供应商",
        "profileId": "generic",
        "protocolFamily": "openai_compatible",
        "generationAuthSchemes": {"openai_compatible": "bearer_token"},
        "modelDiscoveryStrategy": "openai_models",
        "modelDiscoveryAuthScheme": "bearer_token",
        "generationUrls": {
            "openai_compatible": "https://example.com/v1/chat/completions"
        },
        "modelDiscoveryUrl": "https://example.com/v1/models",
        "enabled": False,
        "createdAt": "package",
        "updatedAt": "package",
    }


def _model(model_id: str):
    return {
        "modelId": model_id,
        "displayName": model_id,
        "familyGroup": "sample",
        "capabilityTags": [],
        "note": "",
        "priceCurrency": "CNY",
        "inputPricePerMillion": None,
        "cacheHitPricePerMillion": None,
        "outputPricePerMillion": None,
        "createdAt": None,
        "updatedAt": None,
    }


def _empty_provider_rules():
    return {"schemaVersion": 1, "capabilities": {}, "request": {}, "behavior": {}}


def _empty_model_rules():
    return {"schemaVersion": 1, "families": {}, "models": {}}


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
