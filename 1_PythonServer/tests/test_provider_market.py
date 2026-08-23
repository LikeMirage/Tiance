import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.core.errors import BadRequestError, ConflictError
from app.infra.provider_market import ProviderPackageArchive
from app.repositories.llm.provider_catalog_repository import ProviderCatalogRepository
from app.repositories.llm.provider_file_store import ProviderFileStore
from app.repositories.llm.provider_market_cache_repository import ProviderMarketCacheRepository
from app.repositories.llm.provider_market_settings_repository import (
    DEFAULT_PROVIDER_MARKET_SOURCE,
    ProviderMarketSettingsRepository,
)
from app.schemas.llm.provider_market import (
    ProviderMarketEntry,
    ProviderMarketRemoteIndex,
)
from app.services.application import provider_market as provider_market_module
from app.services.application.provider_market import ProviderMarketApplicationService


class _WorkspaceRegistry:
    def __init__(self) -> None:
        self.sync_count = 0
        self.moves: list[tuple[str, str]] = []

    def synchronize(self) -> None:
        self.sync_count += 1

    def move_provider_to_category(self, provider_id: str, category_id: str) -> None:
        self.moves.append((provider_id, category_id))


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


def test_provider_market_update_only_replaces_manifest_and_adaptation_rules(tmp_path) -> None:
    providers_root = tmp_path / "providers"
    target = providers_root / "sample-provider"
    target.mkdir(parents=True)
    previous_manifest = _package_files(
        "sample-provider",
        managed_model_ids=["old-market-model"],
    )["manifest.json"]
    _write_json(target / "manifest.json", previous_manifest)
    provider_payload = _provider_payload("sample-provider")
    provider_payload.update({
        "displayName": "用户自定义名称",
        "enabled": True,
        "createdAt": "old",
        "updatedAt": "old",
    })
    provider_payload["generationUrls"]["openai_compatible"] = (
        "https://proxy.example/v1/chat/completions"
    )
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
    _write_json(target / "cloud-model-cache.json", {
        "schemaVersion": 1,
        "items": [_model("cached-model")],
    })
    runtime_root = target / ".Tiance"
    runtime_root.mkdir()
    (runtime_root / "sentinel.txt").write_text("conversation-runtime", encoding="utf-8")
    protected_files = {
        name: (target / name).read_bytes()
        for name in (
            "provider.json",
            "credentials.json",
            "models.json",
            "cloud-model-cache.json",
        )
    }

    package_root = tmp_path / "package" / "sample-provider"
    package_root.mkdir(parents=True)
    for name, payload in _package_files(
        "sample-provider",
        managed_model_ids=["new-market-model"],
    ).items():
        if name == "manifest.json":
            payload["version"] = "1.1.0"
        if name == "provider.json":
            payload["displayName"] = "市场新版名称"
            payload["generationUrls"]["openai_responses"] = (
                "https://example.com/v1/responses"
            )
            payload["generationAuthSchemes"]["openai_responses"] = "bearer_token"
        if name == "provider-rules.json":
            payload["behavior"] = {"streamUsage": "include_usage"}
        if name == "model-rules.json":
            payload["families"] = {"sample": {"capabilities": ["tools"]}}
        _write_json(package_root / name, payload)

    store = ProviderFileStore(providers_root)
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
        workspace_registry=workspace,
        project_service=object(),
    )

    service._update_installed_provider(
        provider_id="sample-provider",
        package_root=package_root,
        backup_root=tmp_path / "backup",
    )

    for name, original in protected_files.items():
        assert (target / name).read_bytes() == original
    assert (runtime_root / "sentinel.txt").read_text(encoding="utf-8") == (
        "conversation-runtime"
    )
    assert not (runtime_root / "provider-market.json").exists()
    assert not (runtime_root / "provider-package.json").exists()
    assert json.loads((target / "manifest.json").read_text(encoding="utf-8"))[
        "version"
    ] == "1.1.0"
    assert json.loads((target / "provider-rules.json").read_text(encoding="utf-8"))[
        "behavior"
    ] == {"streamUsage": "include_usage"}
    assert json.loads((target / "model-rules.json").read_text(encoding="utf-8"))[
        "families"
    ] == {"sample": {"capabilities": ["tools"]}}
    assert workspace.sync_count == 0

    mismatched_manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    mismatched_manifest["id"] = "another-provider"
    _write_json(target / "manifest.json", mismatched_manifest)
    assert service._read_local_market_manifest("sample-provider") is None
    index = ProviderMarketRemoteIndex.model_validate({
        "schemaVersion": 1,
        "kind": "tiance-provider-market",
        "name": "示例市场",
        "updatedAt": "2026-08-02T00:00:00Z",
        "providers": [_entry().model_dump(by_alias=True)],
    })
    response = service._to_response(
        index,
        source="https://example.com/market",
        cached=False,
    )
    assert response.providers[0].installation_status == "update-available"


def test_provider_market_update_rejects_incompatible_profile_change(tmp_path) -> None:
    providers_root = tmp_path / "providers"
    target = providers_root / "sample-provider"
    target.mkdir(parents=True)
    _write_json(target / "provider.json", _provider_payload("sample-provider"))
    package_root = tmp_path / "package" / "sample-provider"
    package_root.mkdir(parents=True)
    incoming = _provider_payload("sample-provider")
    incoming["profileId"] = "different-profile"
    _write_json(package_root / "provider.json", incoming)

    service = _service(providers_root)

    with pytest.raises(ConflictError) as error:
        service._update_installed_provider(
            provider_id="sample-provider",
            package_root=package_root,
            backup_root=tmp_path / "backup",
        )
    assert error.value.details["reason"] == "provider_incompatible_update"


def test_provider_market_update_rolls_back_rule_files_without_touching_user_data(
    tmp_path,
    monkeypatch,
) -> None:
    providers_root = tmp_path / "providers"
    target = providers_root / "sample-provider"
    target.mkdir(parents=True)
    for name, payload in _package_files(
        "sample-provider",
        managed_model_ids=["old-model"],
    ).items():
        _write_json(target / name, payload)
    _write_json(target / "credentials.json", {"secret": "keep"})
    original = {name: (target / name).read_bytes() for name in (
        "manifest.json",
        "provider-rules.json",
        "model-rules.json",
        "credentials.json",
        "provider.json",
        "models.json",
    )}
    package_root = tmp_path / "package" / "sample-provider"
    package_root.mkdir(parents=True)
    for name, payload in _package_files(
        "sample-provider",
        managed_model_ids=["new-model"],
    ).items():
        _write_json(package_root / name, payload)

    real_atomic_copy = provider_market_module._atomic_copy
    failed = False

    def fail_once(source: Path, target_path: Path) -> None:
        nonlocal failed
        if source.parent == package_root and source.name == "provider-rules.json" and not failed:
            failed = True
            raise OSError("simulated update failure")
        real_atomic_copy(source, target_path)

    monkeypatch.setattr(provider_market_module, "_atomic_copy", fail_once)

    with pytest.raises(OSError, match="simulated update failure"):
        _service(providers_root)._update_installed_provider(
            provider_id="sample-provider",
            package_root=package_root,
            backup_root=tmp_path / "backup",
        )

    for name, content in original.items():
        assert (target / name).read_bytes() == content


def test_provider_market_new_install_uses_full_package_without_market_runtime_files(
    tmp_path,
) -> None:
    providers_root = tmp_path / "providers"
    providers_root.mkdir()
    store = ProviderFileStore(providers_root)
    store.write_settings({"schemaVersion": 1, "providerOrder": [], "updatedAt": "old"})
    package_root = tmp_path / "package" / "sample-provider"
    package_root.mkdir(parents=True)
    for name, payload in _package_files(
        "sample-provider",
        managed_model_ids=["sample-model"],
    ).items():
        _write_json(package_root / name, payload)
    workspace = _WorkspaceRegistry()
    service = _service(providers_root, workspace=workspace)

    service._install_new_provider(
        provider_id="sample-provider",
        package_root=package_root,
        category_id="provider-category",
    )

    target = providers_root / "sample-provider"
    assert {path.name for path in target.iterdir() if path.is_file()} == {
        "manifest.json",
        "provider.json",
        "provider-rules.json",
        "model-rules.json",
        "models.json",
        "credentials.json",
        "cloud-model-cache.json",
    }
    provider = json.loads((target / "provider.json").read_text(encoding="utf-8"))
    assert provider["enabled"] is False
    assert provider["createdAt"] != "package"
    assert not (target / ".Tiance").exists()
    assert workspace.moves == [("sample-provider", "provider-category")]


def test_provider_market_default_source_is_directly_publishable(tmp_path) -> None:
    repository = ProviderMarketSettingsRepository(tmp_path / "market-settings.json")
    assert repository.ensure_settings_file().source == DEFAULT_PROVIDER_MARKET_SOURCE
    assert DEFAULT_PROVIDER_MARKET_SOURCE == "https://likemirage.github.io/Tiance-providers"


def test_provider_market_settings_remove_obsolete_conflict_filter_without_losing_source(
    tmp_path,
) -> None:
    settings_path = tmp_path / "market-settings.json"
    _write_json(settings_path, {
        "schemaVersion": 1,
        "source": "https://example.com/providers",
        "filters": {
            "authors": ["Author"],
            "protocols": [],
            "statuses": ["local-conflict", "update-available"],
        },
    })

    settings = ProviderMarketSettingsRepository(settings_path).get_settings()

    assert settings.source == "https://example.com/providers"
    assert settings.filters.authors == ["Author"]
    assert settings.filters.statuses == ["update-available"]


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
        "reasoningReplayMode": "tool_call_rounds",
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _service(
    providers_root: Path,
    *,
    workspace: _WorkspaceRegistry | None = None,
) -> ProviderMarketApplicationService:
    store = ProviderFileStore(providers_root)
    return ProviderMarketApplicationService(
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
        workspace_registry=workspace or _WorkspaceRegistry(),
        project_service=object(),
    )
