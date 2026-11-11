import asyncio
import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import Settings, get_settings
from app.core.errors import ConflictError
from app.services.application import software_update as software_update_module
from app.services.application.software_update import (
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


def test_application_version_ignores_legacy_configuration(monkeypatch, tmp_path) -> None:
    expected = json.loads(
        (get_settings().project_root_path / "system/version.json").read_text(encoding="utf-8")
    )["version"]
    legacy_env = tmp_path / ".env"
    legacy_env.write_text("APP_VERSION=0.1.0\nAPP_NAME=Legacy configured name\n", encoding="utf-8")
    monkeypatch.setenv("APP_VERSION", "9.9.9")
    settings = Settings(_env_file=legacy_env, app_version="8.8.8")
    assert settings.app_version == expected
    assert settings.app_name == "Legacy configured name"
    with pytest.raises(AttributeError):
        settings.app_version = "7.7.7"
    monkeypatch.delenv("APP_VERSION")
    assert Settings(_env_file=legacy_env).app_version == expected


def test_application_version_rejects_invalid_version_file(monkeypatch, tmp_path) -> None:
    from app.core import config

    monkeypatch.setattr(config, "_find_project_root", lambda: tmp_path)
    monkeypatch.setenv("APP_VERSION", "0.1.0")
    with pytest.raises(RuntimeError, match="version file"):
        Settings(_env_file=None)


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

    async def load():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
            monkeypatch.setattr(software_update_module, "get_shared_http_client", lambda: client)
            return await SoftwareUpdateService()._load_latest_manifest()

    manifest = asyncio.run(load())

    assert manifest.full.asset_name == "Tiance-update.zip"
    assert manifest.incremental is not None
    assert manifest.incremental.from_version == "0.3.14"
    assert manifest.name == "Tiance v0.3.15"
    assert manifest.notes == ""


def _index(version="0.3.15", **extra):
    return {
        "schemaVersion": 1, "version": version,
        "assetName": "Tiance-update.zip", "sha256": "a" * 64, "size": 100,
        **extra,
    }


def test_check_reads_static_asset_without_rest_api(monkeypatch, tmp_path):
    calls = []
    payload = _index(releaseName="发布标题", releaseNotes="更新说明\n第二行", publishedAt="2026-11-11T00:00:00Z")

    def handle(request):
        calls.append(request.url)
        assert request.url.host != "api.github.com"
        assert "authorization" not in request.headers
        if request.url == software_update_module.LATEST_MANIFEST_URL:
            return httpx.Response(302, headers={"Location": "https://release-assets.githubusercontent.com/manifest"})
        return httpx.Response(200, json=payload)

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
            monkeypatch.setattr(software_update_module, "get_shared_http_client", lambda: client)
            return await SoftwareUpdateService().check()

    monkeypatch.setattr(software_update_module, "get_settings", lambda: SimpleNamespace(app_version="0.3.14", project_root_path=tmp_path))
    result = asyncio.run(check())
    assert len(calls) == 2
    assert result.latest_version == "0.3.15"
    assert result.update_available is True
    assert result.download_size == 100
    assert result.release_notes == payload["releaseNotes"]
    assert result.published_at == payload["publishedAt"]


@pytest.mark.parametrize("status,headers,code,text", [
    (404, {}, "update_assets_missing", "404"),
    (502, {}, "update_http_error", "502"),
    (429, {"retry-after": "20"}, "update_rate_limited", "20 秒"),
    (403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1794388233"}, "update_rate_limited", "本机时间"),
    (403, {}, "update_http_error", "403"),
])
def test_update_check_reports_actual_http_failure(monkeypatch, status, headers, code, text):
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(status, headers=headers))) as client:
            monkeypatch.setattr(software_update_module, "get_shared_http_client", lambda: client)
            await SoftwareUpdateService().check()
    with pytest.raises(SoftwareUpdateError, match=text) as raised:
        asyncio.run(check())
    assert raised.value.code == code


@pytest.mark.parametrize("exception,code", [
    (httpx.ConnectTimeout, "update_timeout"), (httpx.ReadTimeout, "update_timeout"),
    (httpx.ConnectError, "update_connection_failed"),
])
def test_update_network_errors_are_distinguished(monkeypatch, exception, code):
    def handle(request):
        raise exception("test", request=request)

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            monkeypatch.setattr(software_update_module, "get_shared_http_client", lambda: client)
            await SoftwareUpdateService().check()
    with pytest.raises(SoftwareUpdateError) as raised:
        asyncio.run(check())
    assert raised.value.code == code


@pytest.mark.parametrize("body", [
    b"<html>proxy error</html>", b"[]", b"{}", b"x" * (64 * 1024 + 1),
    json.dumps(_index(version="../bad")).encode(),
    json.dumps(_index(releaseNotes=[])).encode(),
    json.dumps(_index(assetName="../payload.zip")).encode(),
    json.dumps(_index(sha256="bad")).encode(),
], ids=["html", "array", "empty", "oversize", "version", "notes", "asset", "hash"])
def test_update_check_rejects_invalid_manifest(monkeypatch, body):
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))) as client:
            monkeypatch.setattr(software_update_module, "get_shared_http_client", lambda: client)
            await SoftwareUpdateService().check()
    with pytest.raises(SoftwareUpdateError) as raised:
        asyncio.run(check())
    assert raised.value.code == "update_manifest_invalid"


@pytest.mark.parametrize("current_version,corrupt", [("0.3.14", False), ("0.3.10", False), ("0.3.14", True)])
def test_download_pins_version_and_validates_actual_archive(monkeypatch, tmp_path, current_version, corrupt):
    archive = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("Tiance/system/version.json", '{"version":"0.3.15"}')
        output.writestr("Tiance/system/update-manifest.json", json.dumps({
            "schemaVersion": 2, "version": "0.3.15", "replace": ["system/version.json"], "delete": [],
        }))
    content = archive.read_bytes()
    full = {"assetName": "Tiance-update.zip", "sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}
    incremental = {**full, "assetName": "Tiance-update-incremental.zip", "fromVersion": "0.3.14"}
    payload = _index(full=full, incremental=incremental)
    calls = []

    def handle(request):
        url = str(request.url)
        calls.append(url)
        if url == software_update_module.LATEST_MANIFEST_URL:
            return httpx.Response(200, json=payload)
        name = incremental["assetName"] if current_version == "0.3.14" else full["assetName"]
        assert url == f"{software_update_module.RELEASES_URL}/download/v0.3.15/{name}"
        return httpx.Response(200, content=content[:-1] + b"!" if corrupt else content)

    async def download():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            monkeypatch.setattr(software_update_module, "get_shared_http_client", lambda: client)
            return await SoftwareUpdateService().download()

    cache = tmp_path / "cache"
    monkeypatch.setattr(software_update_module, "get_http_timeout", lambda **_: httpx.Timeout(5))
    monkeypatch.setattr(software_update_module, "_update_cache_root", lambda: cache)
    monkeypatch.setattr(software_update_module, "get_settings", lambda: SimpleNamespace(app_version=current_version, project_root_path=tmp_path))
    if corrupt:
        with pytest.raises(SoftwareUpdateError) as raised:
            asyncio.run(download())
        assert raised.value.code == "update_checksum_mismatch"
        assert not list(cache.glob("*"))
    else:
        result = asyncio.run(download())
        assert result.version == "0.3.15"
        assert (Path(result.stage_path) / ".tiance-update-ready").read_text() == "0.3.15"
    assert len(calls) == 2


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
