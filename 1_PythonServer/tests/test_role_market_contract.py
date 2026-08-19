import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from app.core.errors import BadRequestError
from app.infra.role_market import (
    RolePackageArchive,
    normalize_role_market_source,
    resolve_role_market_asset_url,
)
from app.repositories.roles import RoleMarketSettingsRepository
from app.schemas.roles import RoleMarketFilterSettings, RoleMarketRoleEntry
from app.services.application.role_market import RoleMarketApplicationService


def test_market_settings_are_created_repaired_and_persist_filters(tmp_path) -> None:
    settings_path = tmp_path / "roles" / "market-settings.json"
    repository = RoleMarketSettingsRepository(settings_path)

    initial = repository.ensure_settings_file()
    saved = repository.save_filters(RoleMarketFilterSettings(
        authors=["LikeMirage", "LikeMirage"],
        statuses=["not-installed"],
    ))
    settings_path.write_text("not-json", encoding="utf-8")
    repaired = repository.ensure_settings_file()

    assert initial.source == "https://likemirage.github.io/Tiance-roles"
    assert saved.filters.authors == ["LikeMirage", "LikeMirage"]
    assert repaired.source == initial.source
    assert json.loads(settings_path.read_text(encoding="utf-8"))["schemaVersion"] == 1


def test_market_urls_enforce_https_scope_and_clean_assets() -> None:
    source = normalize_role_market_source("https://example.com/user/roles/index.json")

    assert source == "https://example.com/user/roles"
    assert resolve_role_market_asset_url(source, "packages/role-1.0.0.zip") == (
        "https://example.com/user/roles/packages/role-1.0.0.zip"
    )
    assert normalize_role_market_source("http://127.0.0.1:8000/market") == (
        "http://127.0.0.1:8000/market"
    )
    for invalid in (
        "http://example.com/roles",
        "https://user:secret@example.com/roles",
        "https://example.com/roles?x=1",
        "https://example.com/roles#fragment",
    ):
        with pytest.raises(BadRequestError):
            normalize_role_market_source(invalid)
    for invalid_asset in (
        "https://other.example/role.zip",
        "../../role.zip",
        "packages/role.zip?token=secret",
    ):
        with pytest.raises(BadRequestError):
            resolve_role_market_asset_url(source, invalid_asset)


def test_market_index_rejects_duplicate_ids_and_invalid_contract() -> None:
    payload = _index_payload()
    payload["roles"] = [payload["roles"][0], payload["roles"][0]]
    with pytest.raises(BadRequestError, match="重复"):
        RoleMarketApplicationService._validate_index_payload(
            "https://example.com/roles",
            payload,
        )

    invalid_cases = [
        ("id", "Bad Role"),
        ("version", "01.0.0"),
        ("size", 0),
        ("sha256", "not-a-hash"),
        ("packageUrl", "https://other.example/role.zip"),
    ]
    for key, value in invalid_cases:
        payload = _index_payload()
        payload["roles"][0][key] = value
        with pytest.raises(BadRequestError):
            RoleMarketApplicationService._validate_index_payload(
                "https://example.com/roles",
                payload,
            )


def test_role_package_validates_exact_files_and_configuration(tmp_path) -> None:
    archive_path = _write_role_archive(tmp_path, _valid_files())
    extracted = RolePackageArchive().validate_and_extract(
        archive_path=archive_path,
        staging_root=tmp_path / "staging",
        market_entry=_entry(),
    )

    assert json.loads((extracted / "prompt.json").read_text(encoding="utf-8")) == {
        "system_prompt": "You are helpful."
    }


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda files: files.pop("tools.json"), "九个正式文件"),
        (lambda files: files.__setitem__("extra.json", {}), "九个正式文件"),
        (
            lambda files: files["prompt.json"].update({"unknown": True}),
            "prompt.json",
        ),
        (
            lambda files: files["generation.json"].update({"temperature": 3}),
            "generation.json",
        ),
        (
            lambda files: files["memory.json"].update(
                {"memory_context_token_trigger_threshold": 0}
            ),
            "memory.json",
        ),
        (
            lambda files: files["tools.json"].update({"enabled_tool_names": [1]}),
            "tools.json",
        ),
    ],
)
def test_role_package_rejects_missing_extra_and_invalid_config(
    tmp_path,
    mutate,
    message,
) -> None:
    files = _valid_files()
    mutate(files)
    archive_path = _write_role_archive(tmp_path, files)

    with pytest.raises(BadRequestError, match=message):
        RolePackageArchive().validate_and_extract(
            archive_path=archive_path,
            staging_root=tmp_path / "staging",
            market_entry=_entry(),
        )


def test_role_package_rejects_traversal_symlink_encryption_and_manifest_mismatch(
    tmp_path,
) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with ZipFile(archive_path, "w") as archive:
        for name, payload in _valid_files().items():
            target = f"sample-role/{name}"
            if name == "tools.json":
                target = "sample-role/../tools.json"
            archive.writestr(target, json.dumps(payload))
    with pytest.raises(BadRequestError, match="越界"):
        RolePackageArchive().validate_and_extract(
            archive_path=archive_path,
            staging_root=tmp_path / "staging-a",
            market_entry=_entry(),
        )

    files = _valid_files()
    files["manifest.json"]["version"] = "2.0.0"
    with pytest.raises(BadRequestError, match="不一致"):
        RolePackageArchive().validate_and_extract(
            archive_path=_write_role_archive(tmp_path, files, name="manifest.zip"),
            staging_root=tmp_path / "staging-b",
            market_entry=_entry(),
        )

    link_archive = tmp_path / "link.zip"
    with ZipFile(link_archive, "w") as archive:
        for name, payload in _valid_files().items():
            info = ZipInfo(f"sample-role/{name}")
            if name == "tools.json":
                info.create_system = 3
                info.external_attr = 0o120777 << 16
            archive.writestr(info, json.dumps(payload))
    with pytest.raises(BadRequestError, match="链接或加密"):
        RolePackageArchive().validate_and_extract(
            archive_path=link_archive,
            staging_root=tmp_path / "staging-c",
            market_entry=_entry(),
        )


def _write_role_archive(
    tmp_path: Path,
    files: dict[str, dict[str, object]],
    *,
    name: str = "role.zip",
) -> Path:
    archive_path = tmp_path / name
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        for file_name, payload in files.items():
            archive.writestr(
                f"sample-role/{file_name}",
                json.dumps(payload, ensure_ascii=False),
            )
    return archive_path


def _valid_files() -> dict[str, dict[str, object]]:
    return {
        "manifest.json": {
            "schemaVersion": 1,
            "kind": "tiance-role-package",
            "id": "sample-role",
            "name": "示例角色",
            "version": "1.0.0",
            "author": {"name": "LikeMirage"},
            "summary": "示例角色。",
            "license": "CC0-1.0",
            "compatibility": {"minTianceVersion": "0.1.0"},
        },
        "profile.json": {"description": "示例角色。"},
        "model.json": {
            "provider_id": "provider-preference",
            "model_id": "model-preference",
            "reasoning_mode": "auto",
        },
        "generation.json": {
            "temperature": 0.7,
            "top_p": 0.9,
            "max_output_tokens": 32768,
        },
        "prompt.json": {"system_prompt": "You are helpful."},
        "response.json": {
            "return_cancelled_messages": True,
            "return_user_before_cancelled": False,
            "streaming_enabled": True,
            "auto_collapse_assistant_process": True,
            "malformed_tool_call_recovery_enabled": True,
            "upstream_retry_count": 1,
        },
        "context.json": {"inject_message_timestamps": True},
        "memory.json": {
            "global_memory_enabled": True,
            "global_memory_extraction_enabled": True,
            "project_memory_enabled": True,
            "project_memory_extraction_enabled": True,
            "memory_compression_enabled": True,
            "memory_context_token_trigger_threshold": 250000,
            "memory_raw_context_token_reserve": 30000,
        },
        "tools.json": {
            "tools_enabled": True,
            "enabled_tool_names": ["search"],
            "max_tool_calls": 20,
        },
    }


def _entry() -> RoleMarketRoleEntry:
    return RoleMarketRoleEntry.model_validate(_index_payload()["roles"][0])


def _index_payload() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "kind": "tiance-role-market",
        "name": "Test roles",
        "updatedAt": "2026-08-02T00:00:00Z",
        "roles": [{
            "id": "sample-role",
            "name": "示例角色",
            "version": "1.0.0",
            "author": "LikeMirage",
            "summary": "示例角色。",
            "license": "CC0-1.0",
            "packageUrl": "packages/sample-role-1.0.0.zip",
            "sha256": "0" * 64,
            "size": 1,
            "compatibility": {"minTianceVersion": "0.1.0"},
        }],
    }
