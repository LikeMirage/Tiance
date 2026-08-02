from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
from pathlib import Path, PurePosixPath
import re
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from app.core.config import get_settings
from app.infra.http_client import get_http_timeout, get_shared_http_client
from app.repositories.github_auth_repository import GithubAuthRepository, GithubCredentials


GITHUB_API_VERSION = "2026-03-10"
GITHUB_AUTHORIZATION_URL = "https://github.com/settings/connections/applications"
_GITHUB_API = "https://api.github.com"
_GITHUB_HOST = "github.com"
_GITHUB_DOWNLOAD_HOSTS = frozenset({
    "api.github.com",
    "codeload.github.com",
    "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
    "release-assets.githubusercontent.com",
})
_REPOSITORY_COMPONENT = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


class GithubApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GithubAuthenticationRequiredError(GithubApiError):
    pass


@dataclass(frozen=True, slots=True)
class GithubRepositorySource:
    owner: str
    repository: str

    @property
    def canonical_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repository}"


def parse_github_repository_source(source: str) -> GithubRepositorySource | None:
    try:
        parts = urlsplit(source.strip())
    except ValueError:
        return None
    if parts.scheme != "https" or (parts.hostname or "").lower() != _GITHUB_HOST:
        return None
    if parts.username or parts.password or parts.query or parts.fragment:
        return None
    segments = [segment for segment in parts.path.split("/") if segment]
    if len(segments) != 2:
        return None
    owner, repository = segments
    if repository.endswith(".git"):
        repository = repository[:-4]
    if not _REPOSITORY_COMPONENT.fullmatch(owner) or not _REPOSITORY_COMPONENT.fullmatch(repository):
        return None
    return GithubRepositorySource(owner=owner, repository=repository)


def normalize_github_repository_source(source: str) -> str | None:
    parsed = parse_github_repository_source(source)
    return parsed.canonical_url if parsed is not None else None


def resolve_github_repository_path(source: str, raw_resource: str) -> str:
    repository = parse_github_repository_source(source)
    if repository is None:
        raise GithubApiError("GitHub 仓库地址无效。")
    raw = raw_resource.strip()
    parts = urlsplit(raw)
    if parts.scheme:
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or host not in {
            "github.com",
            "raw.githubusercontent.com",
        }:
            raise GithubApiError("GitHub 仓库资源地址无效。")
        segments = [segment for segment in parts.path.split("/") if segment]
        if host == "github.com":
            if len(segments) < 5 or segments[:2] != [repository.owner, repository.repository]:
                raise GithubApiError("GitHub 仓库资源不属于当前仓库。")
            if segments[2] not in {"blob", "raw"}:
                raise GithubApiError("GitHub 仓库资源地址无效。")
            raw = "/".join(segments[4:])
        else:
            if len(segments) < 4 or segments[:2] != [repository.owner, repository.repository]:
                raise GithubApiError("GitHub 仓库资源不属于当前仓库。")
            raw = "/".join(segments[3:])
    path = PurePosixPath(raw.replace("\\", "/").strip("/"))
    if not path.parts or path.is_absolute() or ".." in path.parts:
        raise GithubApiError("GitHub 仓库资源路径无效。")
    return path.as_posix()


class GithubClient:
    def __init__(
        self,
        *,
        client_id: str,
        auth_repository: GithubAuthRepository,
    ) -> None:
        self._client_id = client_id
        self._auth_repository = auth_repository
        self._refresh_lock = asyncio.Lock()

    @property
    def authorization_url(self) -> str:
        return f"{GITHUB_AUTHORIZATION_URL}/{self._client_id}"

    async def start_device_flow(self) -> dict[str, Any]:
        response = await self._oauth_post(
            "https://github.com/login/device/code",
            {"client_id": self._client_id},
        )
        required = ("device_code", "user_code", "verification_uri", "expires_in", "interval")
        if any(key not in response for key in required):
            raise GithubApiError("GitHub 未返回有效的设备登录信息。")
        return response

    async def poll_device_flow(self, device_code: str) -> dict[str, Any]:
        return await self._oauth_post(
            "https://github.com/login/oauth/access_token",
            {
                "client_id": self._client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )

    async def save_device_flow_token(self, payload: dict[str, Any]) -> None:
        credentials = _credentials_from_oauth_payload(payload)
        await asyncio.to_thread(self._auth_repository.save, credentials)

    async def logout(self) -> None:
        await asyncio.to_thread(self._auth_repository.delete)

    async def get_valid_access_token(self, *, required: bool) -> str | None:
        credentials = await asyncio.to_thread(self._auth_repository.read)
        if credentials is None:
            if required:
                raise GithubAuthenticationRequiredError("请先在设定集中登录 GitHub。")
            return None
        if not _is_expiring(credentials.access_expires_at, within_seconds=90):
            return credentials.access_token
        async with self._refresh_lock:
            current = await asyncio.to_thread(self._auth_repository.read)
            if current is None:
                if required:
                    raise GithubAuthenticationRequiredError("GitHub 登录已失效，请重新登录。")
                return None
            if not _is_expiring(current.access_expires_at, within_seconds=90):
                return current.access_token
            if not current.refresh_token or _is_expiring(current.refresh_expires_at, within_seconds=0):
                await asyncio.to_thread(self._auth_repository.delete)
                if required:
                    raise GithubAuthenticationRequiredError("GitHub 登录已过期，请重新登录。")
                return None
            payload = await self._oauth_post(
                "https://github.com/login/oauth/access_token",
                {
                    "client_id": self._client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": current.refresh_token,
                },
            )
            if "error" in payload:
                await asyncio.to_thread(self._auth_repository.delete)
                if required:
                    raise GithubAuthenticationRequiredError("GitHub 登录已过期，请重新登录。")
                return None
            refreshed = _credentials_from_oauth_payload(payload)
            await asyncio.to_thread(self._auth_repository.save, refreshed)
            return refreshed.access_token

    async def get_authenticated_user(self) -> dict[str, Any]:
        return await self._get_json("/user", required_auth=True)

    async def list_authorized_repositories(self) -> list[dict[str, Any]]:
        installations = await self._get_paginated("/user/installations", required_auth=True)
        repositories: dict[int, dict[str, Any]] = {}
        for installation in installations:
            installation_id = installation.get("id")
            if not isinstance(installation_id, int):
                continue
            path = f"/user/installations/{installation_id}/repositories"
            for repository in await self._get_paginated(path, required_auth=True):
                repository_id = repository.get("id")
                if isinstance(repository_id, int):
                    repositories[repository_id] = repository
        return sorted(
            repositories.values(),
            key=lambda item: str(item.get("full_name") or "").lower(),
        )

    async def get_repository_default_branch(self, repository: GithubRepositorySource) -> str:
        payload = await self._get_json(
            f"/repos/{quote(repository.owner, safe='')}/{quote(repository.repository, safe='')}",
            required_auth=False,
        )
        default_branch = payload.get("default_branch")
        if not isinstance(default_branch, str) or not default_branch:
            raise GithubApiError("GitHub 仓库未返回默认分支。")
        return default_branch

    async def fetch_repository_file(
        self,
        repository: GithubRepositorySource,
        path: str,
        *,
        maximum_bytes: int,
        ref: str | None = None,
    ) -> bytes:
        url = self._contents_url(repository, path, ref=ref)
        return await self._fetch_bytes(
            url,
            maximum_bytes=maximum_bytes,
            accept="application/vnd.github.raw+json",
            required_auth=False,
        )

    async def download_repository_file(
        self,
        repository: GithubRepositorySource,
        path: str,
        *,
        target: Path,
        maximum_bytes: int,
        ref: str | None = None,
    ) -> tuple[int, str]:
        return await self._download_to_file(
            self._contents_url(repository, path, ref=ref),
            target=target,
            maximum_bytes=maximum_bytes,
            accept="application/vnd.github.raw+json",
            required_auth=False,
        )

    async def download_repository_archive(
        self,
        repository: GithubRepositorySource,
        ref: str,
        *,
        target: Path,
        maximum_bytes: int,
    ) -> tuple[int, str]:
        owner = quote(repository.owner, safe="")
        name = quote(repository.repository, safe="")
        safe_ref = quote(ref, safe="/")
        return await self._download_to_file(
            f"{_GITHUB_API}/repos/{owner}/{name}/zipball/{safe_ref}",
            target=target,
            maximum_bytes=maximum_bytes,
            accept="application/vnd.github+json",
            required_auth=False,
        )

    async def _get_paginated(self, path: str, *, required_auth: bool) -> list[dict[str, Any]]:
        page = 1
        items: list[dict[str, Any]] = []
        while True:
            separator = "&" if "?" in path else "?"
            payload = await self._get_json(
                f"{path}{separator}per_page=100&page={page}",
                required_auth=required_auth,
            )
            raw_items = payload.get("installations") or payload.get("repositories")
            if not isinstance(raw_items, list):
                return items
            page_items = [item for item in raw_items if isinstance(item, dict)]
            items.extend(page_items)
            if len(page_items) < 100:
                return items
            page += 1

    async def _get_json(self, path: str, *, required_auth: bool) -> dict[str, Any]:
        token = await self.get_valid_access_token(required=required_auth)
        response = await self._request("GET", f"{_GITHUB_API}{path}", token=token)
        try:
            payload = response.json()
        except ValueError as exc:
            raise GithubApiError("GitHub 返回了无效响应。", status_code=response.status_code) from exc
        if not isinstance(payload, dict):
            raise GithubApiError("GitHub 返回了无效响应。", status_code=response.status_code)
        return payload

    async def _fetch_bytes(
        self,
        url: str,
        *,
        maximum_bytes: int,
        accept: str,
        required_auth: bool,
    ) -> bytes:
        token = await self.get_valid_access_token(required=required_auth)
        chunks: list[bytes] = []
        downloaded = 0
        client = get_shared_http_client()
        try:
            async with client.stream(
                "GET",
                url,
                headers=self._headers(token, accept=accept),
                timeout=get_http_timeout(stream=True),
            ) as response:
                await self._raise_for_status(response, had_token=token is not None)
                self._require_safe_download_url(response.url)
                async for chunk in response.aiter_bytes():
                    downloaded += len(chunk)
                    if downloaded > maximum_bytes:
                        raise GithubApiError("GitHub 仓库资源超过允许大小。")
                    chunks.append(chunk)
        except httpx.RequestError as exc:
            raise GithubApiError("无法连接 GitHub。") from exc
        return b"".join(chunks)

    async def _download_to_file(
        self,
        url: str,
        *,
        target: Path,
        maximum_bytes: int,
        accept: str,
        required_auth: bool,
    ) -> tuple[int, str]:
        token = await self.get_valid_access_token(required=required_auth)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.unlink(missing_ok=True)
        digest = hashlib.sha256()
        downloaded = 0
        client = get_shared_http_client()
        try:
            with target.open("wb") as output:
                async with client.stream(
                    "GET",
                    url,
                    headers=self._headers(token, accept=accept),
                    timeout=get_http_timeout(stream=True),
                ) as response:
                    await self._raise_for_status(response, had_token=token is not None)
                    self._require_safe_download_url(response.url)
                    async for chunk in response.aiter_bytes():
                        downloaded += len(chunk)
                        if downloaded > maximum_bytes:
                            raise GithubApiError("GitHub 仓库资源超过允许大小。")
                        digest.update(chunk)
                        output.write(chunk)
        except (GithubApiError, httpx.RequestError):
            target.unlink(missing_ok=True)
            raise
        return downloaded, digest.hexdigest()

    async def _request(self, method: str, url: str, *, token: str | None) -> httpx.Response:
        client = get_shared_http_client()
        try:
            response = await client.request(
                method,
                url,
                headers=self._headers(token),
                timeout=get_http_timeout(),
            )
        except httpx.RequestError as exc:
            raise GithubApiError("无法连接 GitHub。") from exc
        await self._raise_for_status(response, had_token=token is not None)
        return response

    async def _raise_for_status(self, response: httpx.Response, *, had_token: bool) -> None:
        if response.status_code < 400:
            return
        if response.status_code == 401:
            await asyncio.to_thread(self._auth_repository.delete)
            raise GithubAuthenticationRequiredError("GitHub 登录已失效，请重新登录。")
        if response.status_code == 404:
            message = (
                "GitHub 仓库不存在、未授权给 Tiance Desktop，或缺少请求的文件。"
                if had_token
                else "GitHub 仓库不存在或是私人仓库，请先登录 GitHub。"
            )
            raise GithubApiError(message, status_code=404)
        if response.status_code in {403, 429}:
            raise GithubApiError("GitHub 拒绝了请求，请检查仓库授权或稍后重试。", status_code=response.status_code)
        raise GithubApiError(f"GitHub 请求失败（{response.status_code}）。", status_code=response.status_code)

    async def _oauth_post(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        client = get_shared_http_client()
        try:
            response = await client.post(
                url,
                data=data,
                headers={"Accept": "application/json"},
                timeout=get_http_timeout(),
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GithubApiError("无法连接 GitHub 登录服务。") from exc
        if not isinstance(payload, dict):
            raise GithubApiError("GitHub 登录服务返回了无效响应。")
        return payload

    def _contents_url(
        self,
        repository: GithubRepositorySource,
        path: str,
        *,
        ref: str | None,
    ) -> str:
        safe_path = "/".join(quote(part, safe="") for part in PurePosixPath(path).parts)
        owner = quote(repository.owner, safe="")
        name = quote(repository.repository, safe="")
        url = f"{_GITHUB_API}/repos/{owner}/{name}/contents/{safe_path}"
        return f"{url}?ref={quote(ref, safe='/')}" if ref else url

    @staticmethod
    def _headers(token: str | None, *, accept: str = "application/vnd.github+json") -> dict[str, str]:
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    @staticmethod
    def _require_safe_download_url(url: httpx.URL) -> None:
        if url.scheme != "https" or (url.host or "").lower() not in _GITHUB_DOWNLOAD_HOSTS:
            raise GithubApiError("GitHub 返回了不安全的下载地址。")


def _credentials_from_oauth_payload(payload: dict[str, Any]) -> GithubCredentials:
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise GithubApiError("GitHub 未返回有效登录凭据。")
    now = datetime.now(timezone.utc)
    expires_in = payload.get("expires_in")
    refresh_token = payload.get("refresh_token")
    refresh_expires_in = payload.get("refresh_token_expires_in")
    return GithubCredentials(
        access_token=access_token,
        access_expires_at=(
            now + timedelta(seconds=expires_in)
            if isinstance(expires_in, int) and expires_in > 0
            else None
        ),
        refresh_token=refresh_token if isinstance(refresh_token, str) and refresh_token else None,
        refresh_expires_at=(
            now + timedelta(seconds=refresh_expires_in)
            if isinstance(refresh_expires_in, int) and refresh_expires_in > 0
            else None
        ),
    )


def _is_expiring(value: datetime | None, *, within_seconds: int) -> bool:
    return value is not None and value <= datetime.now(timezone.utc) + timedelta(seconds=within_seconds)


@lru_cache
def get_github_client() -> GithubClient:
    settings = get_settings()
    return GithubClient(
        client_id=settings.github_client_id,
        auth_repository=GithubAuthRepository(settings.secrets_data_path / "github-auth.json"),
    )
