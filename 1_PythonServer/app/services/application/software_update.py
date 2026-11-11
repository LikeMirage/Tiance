from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from tempfile import gettempdir
from uuid import uuid4

import httpx

from app.core.config import get_settings
from app.core.errors import AppError, ConflictError
from app.infra.http_client import lease_http_client, get_http_timeout, get_shared_http_client
from app.schemas.software_update import (
    SoftwareUpdateCheckResponse,
    SoftwareUpdateDownloadResponse,
)


RELEASES_URL = "https://github.com/LikeMirage/Tiance/releases"
UPDATE_MANIFEST_ASSET = "update.json"
LATEST_MANIFEST_URL = f"{RELEASES_URL}/latest/download/{UPDATE_MANIFEST_ASSET}"
UPDATE_PACKAGE_ASSET = "Tiance-update.zip"
INCREMENTAL_UPDATE_PACKAGE_ASSET = "Tiance-update-incremental.zip"
VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
MAX_MANIFEST_BYTES = 64 * 1024
MAX_UPDATE_PACKAGE_BYTES = 1024 * 1024 * 1024
MAX_EXTRACTED_UPDATE_BYTES = 2 * 1024 * 1024 * 1024
UPDATE_MANIFEST_PATH = PurePosixPath("system/update-manifest.json")
ALLOWED_ROOT_FILES = {
    "LICENSE",
    "Tiance.exe",
}
ALLOWED_ROOT_DIRECTORIES = {
    "1_PythonServer",
    "2_ReactWeb",
    "3_PyWebView",
    "runtime",
    "system",
}


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    name: str
    url: str
    size: int


@dataclass(frozen=True, slots=True)
class UpdatePackageManifest:
    asset_name: str
    sha256: str
    size: int
    from_version: str | None = None


@dataclass(frozen=True, slots=True)
class UpdateManifest:
    version: str
    full: UpdatePackageManifest
    incremental: UpdatePackageManifest | None
    name: str = ""
    notes: str = ""
    published_at: str | None = None


class SoftwareUpdateService:
    async def check(self) -> SoftwareUpdateCheckResponse:
        settings = get_settings()
        manifest = await self._load_latest_manifest()
        selected_package = None
        if _version_tuple(manifest.version) > _version_tuple(settings.app_version):
            selected_package = _select_update_package(manifest, settings.app_version)
        return SoftwareUpdateCheckResponse(
            currentVersion=settings.app_version,
            latestVersion=manifest.version,
            updateAvailable=_version_tuple(manifest.version) > _version_tuple(settings.app_version),
            releaseName=manifest.name,
            releaseNotes=manifest.notes,
            publishedAt=manifest.published_at,
            downloadSize=selected_package.size if selected_package else None,
            sourceCheckout=(settings.project_root_path / ".git").exists(),
        )

    async def download(self) -> SoftwareUpdateDownloadResponse:
        settings = get_settings()
        if (settings.project_root_path / ".git").exists():
            raise ConflictError("源码工作区不能使用在线覆盖更新，请通过 Git 更新源码。")

        manifest = await self._load_latest_manifest()
        if _version_tuple(manifest.version) <= _version_tuple(settings.app_version):
            raise ConflictError("当前已经是最新版本。")
        selected_package = _select_update_package(manifest, settings.app_version)
        # Pin the package to the manifest version: a new release appearing during
        # download must not redirect us to a different version's archive.
        release_package = ReleaseAsset(
            name=selected_package.asset_name,
            url=f"{RELEASES_URL}/download/v{manifest.version}/{selected_package.asset_name}",
            size=selected_package.size,
        )

        update_root = _update_cache_root() / manifest.version
        temporary_root = update_root.with_name(f".{manifest.version}-{uuid4().hex}.tmp")
        shutil.rmtree(temporary_root, ignore_errors=True)
        temporary_root.mkdir(parents=True, exist_ok=False)
        archive_path = temporary_root / selected_package.asset_name
        try:
            package_size, package_hash = await self._download_package(release_package, archive_path)
            if (
                package_size != selected_package.size
                or package_hash.lower() != selected_package.sha256.lower()
            ):
                raise SoftwareUpdateError("更新文件校验失败，已停止安装。", code="update_checksum_mismatch")
            payload_root = temporary_root / "payload"
            _extract_update_archive(archive_path, payload_root)
            stage_root = payload_root / "Tiance"
            _validate_staged_payload(stage_root, manifest.version)
            archive_path.unlink(missing_ok=True)
            shutil.rmtree(update_root, ignore_errors=True)
            os.replace(temporary_root, update_root)
        except Exception:
            shutil.rmtree(temporary_root, ignore_errors=True)
            raise

        final_stage_root = update_root / "payload" / "Tiance"
        return SoftwareUpdateDownloadResponse(
            version=manifest.version,
            stagePath=str(final_stage_root),
            packageSize=selected_package.size,
        )

    async def _load_latest_manifest(self) -> UpdateManifest:
        async with lease_http_client(get_shared_http_client()) as client:
            try:
                async with client.stream(
                    "GET", LATEST_MANIFEST_URL,
                    headers={"Accept": "application/json", "Cache-Control": "no-cache"},
                ) as response:
                    response.raise_for_status()
                    content = bytearray()
                    async for chunk in response.aiter_bytes(16 * 1024):
                        content.extend(chunk)
                        if len(content) > MAX_MANIFEST_BYTES:
                            raise ValueError("manifest too large")
                payload = json.loads(content)
                schema_version = payload["schemaVersion"]
                version = payload["version"]
            except httpx.HTTPError as exc:
                raise _update_network_error(exc, "更新清单") from exc
            except (ValueError, KeyError, TypeError) as exc:
                raise SoftwareUpdateError("在线更新清单格式无效。", code="update_manifest_invalid") from exc
            if (
                schema_version != 1
                or not isinstance(version, str)
                or VERSION_PATTERN.fullmatch(version) is None
            ):
                raise SoftwareUpdateError("在线更新清单内容无效。", code="update_manifest_invalid")
            try:
                full = _parse_package_manifest(payload.get("full") or payload)
                incremental_payload = payload.get("incremental")
                incremental = (
                    _parse_package_manifest(incremental_payload, require_from_version=True)
                    if incremental_payload is not None
                    else None
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise SoftwareUpdateError("在线更新清单内容无效。", code="update_manifest_invalid") from exc
            name = payload.get("releaseName", f"Tiance v{version}")
            notes = payload.get("releaseNotes", "")
            published_at = payload.get("publishedAt")
            if (
                not isinstance(name, str) or not isinstance(notes, str)
                or (published_at is not None and not isinstance(published_at, str))
            ):
                raise SoftwareUpdateError("在线更新说明格式无效。", code="update_manifest_invalid")
            return UpdateManifest(
                version=version, full=full, incremental=incremental,
                name=name, notes=notes, published_at=published_at,
            )

    async def _download_package(self, asset: ReleaseAsset, target: Path) -> tuple[int, str]:
        if asset.size <= 0 or asset.size > MAX_UPDATE_PACKAGE_BYTES:
            raise SoftwareUpdateError("更新包大小无效。", code="update_size_invalid")
        digest = hashlib.sha256()
        written = 0
        async with lease_http_client(get_shared_http_client()) as client:
            try:
                async with client.stream("GET", asset.url, timeout=get_http_timeout(stream=True)) as response:
                    response.raise_for_status()
                    with target.open("wb") as output:
                        async for chunk in response.aiter_bytes(1024 * 1024):
                            written += len(chunk)
                            if written > MAX_UPDATE_PACKAGE_BYTES:
                                raise SoftwareUpdateError("更新包超过允许大小。", code="update_size_invalid")
                            digest.update(chunk)
                            output.write(chunk)
            except httpx.HTTPError as exc:
                raise _update_network_error(exc, "更新包") from exc
            return written, digest.hexdigest()


class SoftwareUpdateError(AppError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message, code=code, status_code=502)


def _update_network_error(error: httpx.HTTPError, resource: str) -> SoftwareUpdateError:
    if isinstance(error, httpx.HTTPStatusError):
        response = error.response
        status = response.status_code
        if status == 429 or (status == 403 and response.headers.get("x-ratelimit-remaining") == "0"):
            retry = response.headers.get("retry-after", "")
            reset = response.headers.get("x-ratelimit-reset", "")
            detail = "请稍后重试。"
            if retry.isdigit() and len(retry) < 10:
                detail = f"请在 {int(retry)} 秒后重试。"
            elif reset.isdigit() and len(reset) < 12:
                try:
                    local_time = datetime.fromtimestamp(int(reset), timezone.utc).astimezone()
                    detail = f"可在本机时间 {local_time:%Y-%m-%d %H:%M:%S} 后重试。"
                except (ValueError, OverflowError, OSError):
                    pass
            return SoftwareUpdateError(f"GitHub 暂时限制访问{resource}。{detail}", code="update_rate_limited")
        if status == 404:
            return SoftwareUpdateError(f"GitHub 发布中找不到{resource}（HTTP 404）。", code="update_assets_missing")
        return SoftwareUpdateError(f"获取{resource}失败：服务器返回 HTTP {status}。", code="update_http_error")
    if isinstance(error, httpx.TimeoutException):
        return SoftwareUpdateError(f"获取{resource}超时，请检查网络或代理后重试。", code="update_timeout")
    return SoftwareUpdateError(f"获取{resource}时网络连接失败（{type(error).__name__}），请检查网络设置。", code="update_connection_failed")


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = VERSION_PATTERN.fullmatch(value)
    if match is None:
        raise RuntimeError(f"Invalid application version: {value}")
    return tuple(int(part) for part in match.groups())


def _parse_package_manifest(
    payload: object,
    *,
    require_from_version: bool = False,
) -> UpdatePackageManifest:
    if not isinstance(payload, dict):
        raise TypeError("package manifest must be an object")
    asset_name = payload["assetName"]
    sha256 = payload["sha256"]
    size = payload["size"]
    from_version = payload.get("fromVersion")
    allowed_asset = (
        INCREMENTAL_UPDATE_PACKAGE_ASSET
        if require_from_version
        else UPDATE_PACKAGE_ASSET
    )
    if (
        asset_name != allowed_asset
        or not isinstance(sha256, str)
        or re.fullmatch(r"[0-9a-fA-F]{64}", sha256) is None
        or not isinstance(size, int)
        or size <= 0
        or size > MAX_UPDATE_PACKAGE_BYTES
        or (
            require_from_version
            and (
                not isinstance(from_version, str)
                or VERSION_PATTERN.fullmatch(from_version) is None
            )
        )
    ):
        raise ValueError("invalid package manifest")
    return UpdatePackageManifest(
        asset_name=asset_name,
        sha256=sha256,
        size=size,
        from_version=from_version if isinstance(from_version, str) else None,
    )


def _select_update_package(
    manifest: UpdateManifest,
    current_version: str,
) -> UpdatePackageManifest:
    incremental = manifest.incremental
    if incremental is not None and incremental.from_version == current_version:
        return incremental
    return manifest.full


def _update_cache_root() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path(gettempdir())
    root = base / "Tiance" / "updates"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _extract_update_archive(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if not members:
            raise SoftwareUpdateError("更新包为空。", code="update_package_invalid")
        if sum(member.file_size for member in members) > MAX_EXTRACTED_UPDATE_BYTES:
            raise SoftwareUpdateError("更新包解压后超过允许大小。", code="update_package_invalid")
        seen_paths: set[str] = set()
        for member in members:
            if "\\" in member.filename or "\x00" in member.filename or member.flag_bits & 0x1:
                raise SoftwareUpdateError("更新包包含无效文件。", code="update_package_invalid")
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "Tiance":
                raise SoftwareUpdateError("更新包包含无效路径。", code="update_package_invalid")
            normalized_name = "/".join(path.parts).casefold()
            if normalized_name in seen_paths:
                raise SoftwareUpdateError("更新包包含重复路径。", code="update_package_invalid")
            seen_paths.add(normalized_name)
            if any(part in {"", "."} or ":" in part for part in path.parts):
                raise SoftwareUpdateError("更新包包含 Windows 不支持的路径。", code="update_package_invalid")
            relative_parts = path.parts[1:]
            if not relative_parts:
                continue
            if relative_parts == ("Data",) and member.is_dir():
                continue
            _validate_update_relative_path(relative_parts)
            if ((member.external_attr >> 16) & 0o170000) == 0o120000:
                raise SoftwareUpdateError("更新包不能包含符号链接。", code="update_package_invalid")
            target = destination.joinpath(*path.parts)
            resolved_target = target.resolve()
            if destination.resolve() not in resolved_target.parents:
                raise SoftwareUpdateError("更新包路径越界。", code="update_package_invalid")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)


def _validate_update_relative_path(parts: tuple[str, ...]) -> None:
    first = parts[0]
    if first in ALLOWED_ROOT_FILES and len(parts) == 1:
        return
    if first in ALLOWED_ROOT_DIRECTORIES:
        return
    raise SoftwareUpdateError("更新包包含不允许覆盖的用户数据。", code="update_package_invalid")


def _validate_staged_payload(stage_root: Path, version: str) -> None:
    manifest_path = stage_root / UPDATE_MANIFEST_PATH.as_posix()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SoftwareUpdateError("更新文件清单无效。", code="update_package_invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 2:
        raise SoftwareUpdateError("更新文件清单版本无效。", code="update_package_invalid")
    replace = _validate_update_manifest_paths(manifest.get("replace"), "replace")
    deleted = _validate_update_manifest_paths(manifest.get("delete"), "delete")
    if set(replace) & set(deleted) or "system/version.json" not in replace:
        raise SoftwareUpdateError("更新文件清单存在冲突或缺少版本文件。", code="update_package_invalid")
    listed = set(replace) | {UPDATE_MANIFEST_PATH.as_posix()}
    actual = {
        path.relative_to(stage_root).as_posix()
        for path in stage_root.rglob("*")
        if path.is_file() and path.name != ".tiance-update-ready"
    }
    if actual != listed:
        raise SoftwareUpdateError("更新包内容与文件清单不一致。", code="update_package_invalid")
    if manifest.get("version") != version:
        raise SoftwareUpdateError("更新文件清单版本与发布版本不一致。", code="update_package_invalid")
    try:
        payload = json.loads(
            (stage_root / "system" / "version.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SoftwareUpdateError("更新包版本文件无效。", code="update_package_invalid") from exc
    if payload.get("version") != version:
        raise SoftwareUpdateError("更新包版本与发布版本不一致。", code="update_package_invalid")
    (stage_root / ".tiance-update-ready").write_text(version, encoding="utf-8")


def _validate_update_manifest_paths(raw: object, field: str) -> list[str]:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise SoftwareUpdateError(f"更新文件清单的 {field} 字段无效。", code="update_package_invalid")
    result: list[str] = []
    for value in raw:
        path = PurePosixPath(value)
        if (
            not value or path.is_absolute() or ".." in path.parts or "\\" in value
            or path.as_posix() != value or path == UPDATE_MANIFEST_PATH
        ):
            raise SoftwareUpdateError("更新文件清单包含非法路径。", code="update_package_invalid")
        _validate_update_relative_path(path.parts)
        if value in result:
            raise SoftwareUpdateError("更新文件清单包含重复路径。", code="update_package_invalid")
        result.append(value)
    return result


_service = SoftwareUpdateService()


def get_software_update_service() -> SoftwareUpdateService:
    return _service
