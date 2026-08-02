from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import httpx

from app.core.errors import BadRequestError
from app.infra.http_client import get_http_timeout, get_shared_http_client
from app.infra.github import (
    GithubApiError,
    GithubRepositorySource,
    get_github_client,
    parse_github_repository_source,
    resolve_github_repository_path,
)
from app.infra.online_market import normalize_market_source, resolve_market_asset_url
from app.schemas.project.project_market import ProjectMarketDownload


MAX_PROJECT_MARKET_INDEX_BYTES = 2 * 1024 * 1024
MAX_PROJECT_PACKAGE_BYTES = 512 * 1024 * 1024
MAX_PROJECT_PREVIEW_BYTES = 5 * 1024 * 1024
_GITHUB_CONTENT_HOSTS = frozenset({
    "api.github.com",
    "github.com",
    "raw.githubusercontent.com",
    "codeload.github.com",
    "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
})
_SAFE_REF_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")


class ProjectMarketConnectionError(BadRequestError):
    pass


class ProjectMarketRemoteClient:
    async def fetch_index(self, source: str) -> dict[str, object]:
        normalized_source = normalize_project_market_source(source)
        github = parse_github_repository_source(normalized_source)
        if github is not None:
            try:
                default_ref = await get_github_client().get_repository_default_branch(github)
                content = await get_github_client().fetch_repository_file(
                    github,
                    "index.json",
                    maximum_bytes=MAX_PROJECT_MARKET_INDEX_BYTES,
                    ref=default_ref,
                )
            except GithubApiError as exc:
                raise ProjectMarketConnectionError(f"无法连接在线项目仓库：{exc}") from exc
            payload = _decode_index(content)
            payload.setdefault("defaultRef", default_ref)
            return payload

        content = await self._fetch_bytes(
            source=normalized_source,
            url=f"{normalized_source}/index.json",
            maximum_bytes=MAX_PROJECT_MARKET_INDEX_BYTES,
            accept="application/json",
        )
        if content is None:
            raise ProjectMarketConnectionError("无法连接在线项目仓库。")
        return _decode_index(content)

    async def download_package(
        self,
        *,
        source: str,
        download: ProjectMarketDownload,
        default_ref: str,
        target: Path,
    ) -> str | None:
        normalized_source = normalize_project_market_source(source)
        github = parse_github_repository_source(normalized_source)
        if github is not None and download.kind == "github-directory":
            ref = _safe_ref(download.ref or default_ref)
            source_path = _safe_repository_path(download.path or "", label="项目目录")
            try:
                downloaded, actual_sha256 = await get_github_client().download_repository_archive(
                    github,
                    ref,
                    target=target,
                    maximum_bytes=MAX_PROJECT_PACKAGE_BYTES,
                )
            except GithubApiError as exc:
                raise BadRequestError(f"项目包下载失败：{exc}") from exc
            _validate_download(downloaded, actual_sha256, download)
            return source_path
        if github is not None and download.kind == "archive":
            try:
                downloaded, actual_sha256 = await get_github_client().download_repository_file(
                    github,
                    resolve_github_repository_path(normalized_source, download.url or ""),
                    target=target,
                    maximum_bytes=MAX_PROJECT_PACKAGE_BYTES,
                    ref=_safe_ref(download.ref or default_ref),
                )
            except GithubApiError as exc:
                raise BadRequestError(f"项目包下载失败：{exc}") from exc
            _validate_download(downloaded, actual_sha256, download)
            return None
        resolved_url, source_path = resolve_project_download(
            source,
            download,
            default_ref=default_ref,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.unlink(missing_ok=True)
        expected_size = download.size
        expected_sha256 = download.sha256
        digest = hashlib.sha256()
        downloaded = 0
        client = get_shared_http_client()
        try:
            with target.open("wb") as output:
                async with client.stream(
                    "GET",
                    resolved_url,
                    headers={"Accept": "application/zip, application/octet-stream"},
                    timeout=get_http_timeout(stream=True),
                ) as response:
                    response.raise_for_status()
                    _require_safe_project_market_url(source, str(response.url))
                    async for chunk in response.aiter_bytes():
                        downloaded += len(chunk)
                        if downloaded > MAX_PROJECT_PACKAGE_BYTES:
                            raise BadRequestError("项目包大小超过允许范围。")
                        if expected_size is not None and downloaded > expected_size:
                            raise BadRequestError("项目包实际大小与市场索引不一致。")
                        digest.update(chunk)
                        output.write(chunk)
        except httpx.HTTPError as exc:
            raise BadRequestError("项目包下载失败。") from exc
        if downloaded < 1:
            raise BadRequestError("项目包内容为空。")
        if expected_size is not None and downloaded != expected_size:
            raise BadRequestError("项目包实际大小与市场索引不一致。")
        if expected_sha256 is not None and digest.hexdigest().lower() != expected_sha256:
            raise BadRequestError("项目包完整性校验失败。")
        return source_path

    async def download_preview(
        self,
        *,
        source: str,
        preview_url: str,
        default_ref: str,
    ) -> bytes:
        resolved = resolve_project_asset_url(
            source,
            preview_url,
            default_ref=default_ref,
        )
        normalized_source = normalize_project_market_source(source)
        github = parse_github_repository_source(normalized_source)
        if github is not None:
            try:
                return await get_github_client().fetch_repository_file(
                    github,
                    resolve_github_repository_path(normalized_source, preview_url),
                    maximum_bytes=MAX_PROJECT_PREVIEW_BYTES,
                    ref=_safe_ref(default_ref),
                )
            except GithubApiError as exc:
                raise BadRequestError(f"项目预览图下载失败：{exc}") from exc
        content = await self._fetch_bytes(
            source=source,
            url=resolved,
            maximum_bytes=MAX_PROJECT_PREVIEW_BYTES,
            accept="image/*",
        )
        if content is None:
            raise BadRequestError("项目预览图不存在。")
        return content

    async def _fetch_bytes(
        self,
        *,
        source: str,
        url: str,
        maximum_bytes: int,
        accept: str,
        allow_not_found: bool = False,
    ) -> bytes | None:
        chunks: list[bytes] = []
        downloaded = 0
        client = get_shared_http_client()
        try:
            async with client.stream(
                "GET",
                url,
                headers={"Accept": accept},
                timeout=get_http_timeout(stream=True),
            ) as response:
                if allow_not_found and response.status_code == 404:
                    return None
                response.raise_for_status()
                _require_safe_project_market_url(source, str(response.url))
                async for chunk in response.aiter_bytes():
                    downloaded += len(chunk)
                    if downloaded > maximum_bytes:
                        raise BadRequestError("在线项目资源超过允许大小。")
                    chunks.append(chunk)
        except httpx.HTTPError as exc:
            raise ProjectMarketConnectionError("无法连接在线项目仓库。") from exc
        return b"".join(chunks)


def normalize_project_market_source(raw_source: str) -> str:
    normalized = normalize_market_source(raw_source, resource_label="项目")
    parts = urlsplit(normalized)
    if (parts.hostname or "").lower() != "github.com":
        path = parts.path
        if path.endswith("/index.json"):
            path = path[: -len("/index.json")]
        return urlunsplit((parts.scheme, parts.netloc, path.rstrip("/"), "", ""))
    github = parse_github_repository_source(normalized)
    if github is None:
        raise BadRequestError("GitHub 项目市场地址必须指向仓库根目录。")
    return f"https://github.com/{github.owner}/{github.repository}.git"

def resolve_project_asset_url(source: str, raw_url: str, *, default_ref: str) -> str:
    normalized_source = normalize_project_market_source(source)
    github = parse_github_repository_source(normalized_source)
    raw_url = raw_url.strip()
    if github is None:
        return resolve_market_asset_url(
            normalized_source,
            raw_url,
            resource_label="项目",
            allow_query=False,
        )
    if urlsplit(raw_url).scheme:
        _require_safe_project_market_url(normalized_source, raw_url)
        return raw_url
    path = _safe_repository_path(raw_url, label="项目资源")
    return _github_raw_url(github, ref=_safe_ref(default_ref), path=path)


def resolve_project_download(
    source: str,
    download: ProjectMarketDownload,
    *,
    default_ref: str,
) -> tuple[str, str | None]:
    normalized_source = normalize_project_market_source(source)
    github = parse_github_repository_source(normalized_source)
    ref = _safe_ref(download.ref or default_ref)
    if download.kind == "github-directory":
        if github is None:
            raise BadRequestError("仓库目录下载只支持 GitHub 仓库源。")
        path = _safe_repository_path(download.path or "", label="项目目录")
        return (
            f"https://codeload.github.com/{github.owner}/{github.repository}/zip/{quote(ref, safe='')}",
            path,
        )
    return (
        resolve_project_asset_url(
            normalized_source,
            download.url or "",
            default_ref=ref,
        ),
        None,
    )


def _decode_index(content: bytes) -> dict[str, object]:
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BadRequestError("在线项目索引不是有效 JSON。") from exc
    if not isinstance(payload, dict):
        raise BadRequestError("在线项目索引格式无效。")
    return payload


def _validate_download(
    downloaded: int,
    actual_sha256: str,
    download: ProjectMarketDownload,
) -> None:
    if downloaded < 1:
        raise BadRequestError("项目包内容为空。")
    if download.size is not None and downloaded != download.size:
        raise BadRequestError("项目包实际大小与市场索引不一致。")
    if download.sha256 is not None and actual_sha256.lower() != download.sha256:
        raise BadRequestError("项目包完整性校验失败。")


def _github_raw_url(github: GithubRepositorySource, *, ref: str, path: str) -> str:
    encoded_path = "/".join(quote(part, safe="") for part in PurePosixPath(path).parts)
    encoded_ref = quote(ref, safe="/")
    return (
        f"https://raw.githubusercontent.com/{github.owner}/{github.repository}/"
        f"{encoded_ref}/{encoded_path}"
    )


def _safe_ref(ref: str) -> str:
    value = ref.strip()
    if not _SAFE_REF_PATTERN.fullmatch(value) or ".." in value.split("/"):
        raise BadRequestError("在线项目索引包含无效 Git 引用。")
    return value


def _safe_repository_path(raw_path: str, *, label: str) -> str:
    path = PurePosixPath(raw_path.replace("\\", "/").strip("/"))
    if not path.parts or path.is_absolute() or ".." in path.parts:
        raise BadRequestError(f"{label}路径无效。")
    return path.as_posix()


def _require_safe_project_market_url(source: str, target: str) -> None:
    normalized_source = normalize_project_market_source(source)
    github = parse_github_repository_source(normalized_source)
    if github is None:
        resolved = urljoin(f"{normalized_source}/", target)
        resolve_market_asset_url(
            normalized_source,
            resolved,
            resource_label="项目",
            allow_query=False,
        )
        return
    parts = urlsplit(target)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host not in _GITHUB_CONTENT_HOSTS:
        raise BadRequestError("GitHub 项目资源地址无效。")
    if parts.username or parts.password or parts.fragment:
        raise BadRequestError("GitHub 项目资源地址无效。")
    scoped_prefix = f"/{github.owner}/{github.repository}/"
    if host in {"github.com", "raw.githubusercontent.com", "codeload.github.com"}:
        if not parts.path.startswith(scoped_prefix):
            raise BadRequestError("GitHub 项目资源不属于当前仓库。")
