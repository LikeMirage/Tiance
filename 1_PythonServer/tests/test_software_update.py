import asyncio
import json
import zipfile
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.core.errors import ConflictError
from app.services.application.software_update import (
    SoftwareUpdateError,
    SoftwareUpdateService,
    _extract_update_archive,
    _validate_staged_payload,
    _version_tuple,
)


def test_application_version_comes_from_system_version_file() -> None:
    root = get_settings().project_root_path
    expected = json.loads((root / "system" / "version.json").read_text(encoding="utf-8"))["version"]

    assert get_settings().app_version == expected


def test_semantic_version_comparison_is_numeric() -> None:
    assert _version_tuple("0.3.10") > _version_tuple("0.3.9")


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

    _validate_staged_payload(stage_root, "0.3.10")


def test_staged_payload_requires_complete_runtime(tmp_path: Path) -> None:
    stage_root = tmp_path / "Tiance"
    stage_root.mkdir()

    with pytest.raises(SoftwareUpdateError, match="必要程序文件"):
        _validate_staged_payload(stage_root, "0.3.7")


def test_source_checkout_cannot_download_in_place() -> None:
    with pytest.raises(ConflictError, match="Git"):
        asyncio.run(SoftwareUpdateService().download())
