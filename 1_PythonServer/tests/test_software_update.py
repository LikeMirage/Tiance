import asyncio
import json
import zipfile
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.core.errors import ConflictError
from app.services.application import software_update as software_update_module
from app.services.application.software_update import (
    ReleaseAsset,
    SoftwareUpdateError,
    SoftwareUpdateService,
    UpdateManifest,
    UpdatePackageManifest,
    _extract_update_archive,
    _select_update_package,
    _validate_staged_payload,
    _version_tuple,
)


def test_application_version_comes_from_system_version_file() -> None:
    root = get_settings().project_root_path
    expected = json.loads((root / "system" / "version.json").read_text(encoding="utf-8"))["version"]

    assert get_settings().app_version == expected


def test_semantic_version_comparison_is_numeric() -> None:
    assert _version_tuple("0.3.10") > _version_tuple("0.3.9")


def test_update_selection_uses_incremental_only_for_declared_source_version() -> None:
    full = UpdatePackageManifest(
        asset_name="Tiance-update.zip",
        sha256="a" * 64,
        size=100,
    )
    incremental = UpdatePackageManifest(
        asset_name="Tiance-update-incremental.zip",
        sha256="b" * 64,
        size=10,
        from_version="0.3.14",
    )
    manifest = UpdateManifest(
        version="0.3.15",
        full=full,
        incremental=incremental,
    )

    assert _select_update_package(manifest, "0.3.14") is incremental
    assert _select_update_package(manifest, "0.3.13") is full
    assert _select_update_package(manifest, "0.2.9") is full


def test_update_index_keeps_legacy_full_package_and_declares_incremental(monkeypatch) -> None:
    payload = {
        "schemaVersion": 1,
        "version": "0.3.15",
        "assetName": "Tiance-update.zip",
        "sha256": "a" * 64,
        "size": 100,
        "full": {
            "assetName": "Tiance-update.zip",
            "sha256": "a" * 64,
            "size": 100,
        },
        "incremental": {
            "assetName": "Tiance-update-incremental.zip",
            "sha256": "b" * 64,
            "size": 10,
            "fromVersion": "0.3.14",
        },
    }

    class _Response:
        content = json.dumps(payload).encode()

        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class _Client:
        async def get(self, _url):
            return _Response()

    monkeypatch.setattr(software_update_module, "get_shared_http_client", lambda: _Client())
    manifest = asyncio.run(
        SoftwareUpdateService()._load_manifest(
            ReleaseAsset(name="update.json", url="https://example.test/update.json", size=500),
        )
    )

    assert manifest.full.asset_name == "Tiance-update.zip"
    assert manifest.incremental is not None
    assert manifest.incremental.from_version == "0.3.14"


def test_update_archive_rejects_user_data(tmp_path: Path) -> None:
    archive_path = tmp_path / "update.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("Tiance/Data/tools/catalog.json", "{}")

    with pytest.raises(SoftwareUpdateError, match="用户数据"):
        _extract_update_archive(archive_path, tmp_path / "out")


def test_update_archive_accepts_root_runtime(tmp_path: Path) -> None:
    archive_path = tmp_path / "update.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("Tiance/runtime/", "")
        archive.writestr("Tiance/runtime/runtime.txt", "runtime")

    _extract_update_archive(archive_path, tmp_path / "out")

    assert (tmp_path / "out" / "Tiance" / "runtime" / "runtime.txt").is_file()


def test_update_archive_rejects_legacy_runtime_inside_data(tmp_path: Path) -> None:
    archive_path = tmp_path / "update.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("Tiance/Data/runtime/python/py313/python.exe", "runtime")

    with pytest.raises(SoftwareUpdateError, match="用户数据"):
        _extract_update_archive(archive_path, tmp_path / "out")


def test_staged_payload_accepts_root_runtime(tmp_path: Path) -> None:
    stage_root = tmp_path / "Tiance"
    required = [
        stage_root / "Tiance.exe",
        stage_root / "system" / "TianceUpdater.exe",
        stage_root / "1_PythonServer" / "run.py",
        stage_root / "2_ReactWeb" / "dist" / "index.html",
        stage_root / "3_PyWebView" / "run.py",
        stage_root / "runtime" / "python" / "py313" / "python.exe",
    ]
    for path in required:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    (stage_root / "system" / "version.json").write_text('{"version":"0.3.10"}', encoding="utf-8")
    (stage_root / "system" / "update-manifest.json").write_text(
        json.dumps({
            "schemaVersion": 2,
            "version": "0.3.10",
            "replace": [
                "Tiance.exe",
                "system/TianceUpdater.exe",
                "system/version.json",
                "1_PythonServer/run.py",
                "2_ReactWeb/dist/index.html",
                "3_PyWebView/run.py",
                "runtime/python/py313/python.exe",
            ],
            "delete": [],
        }),
        encoding="utf-8",
    )

    _validate_staged_payload(stage_root, "0.3.10")


def test_staged_payload_requires_complete_runtime(tmp_path: Path) -> None:
    stage_root = tmp_path / "Tiance"
    stage_root.mkdir()

    with pytest.raises(SoftwareUpdateError, match="更新文件清单"):
        _validate_staged_payload(stage_root, "0.3.7")


def test_source_checkout_cannot_download_in_place() -> None:
    with pytest.raises(ConflictError, match="Git"):
        asyncio.run(SoftwareUpdateService().download())
