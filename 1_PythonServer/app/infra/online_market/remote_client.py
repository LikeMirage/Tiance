from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx

from app.core.errors import BadRequestError
from app.infra.github import (
    GithubApiError,
    get_github_client,
    parse_github_repository_source,
    resolve_github_repository_path,
)
from app.infra.http_client import get_http_timeout, get_shared_http_client

from .remote_security import (
    normalize_market_source,
    require_safe_final_url,
    resolve_market_asset_url,
)


class OnlineMarketRemoteClient:
    """GitHub Pages 类市场共用的索引、资源和安装包传输实现。"""

    def __init__(
        self,
        *,
        resource_label: str,
        maximum_index_bytes: int,
        maximum_package_bytes: int,
        connection_error_type: type[BadRequestError] = BadRequestError,
        allow_asset_query: bool = False,
    ) -> None:
        self._resource_label = resource_label
        self._maximum_index_bytes = maximum_index_bytes
        self._maximum_package_bytes = maximum_package_bytes
        self._connection_error_type = connection_error_type
        self._allow_asset_query = allow_asset_query

    def normalize_source(self, source: str) -> str:
        return normalize_market_source(source, resource_label=self._resource_label)

    def resolve_asset_url(self, source: str, raw_url: str) -> str:
        return resolve_market_asset_url(
            source,
            raw_url,
            resource_label=self._resource_label,
            allow_query=self._allow_asset_query,
        )

    async def fetch_index(self, source: str) -> dict[str, object]:
        normalized = self.normalize_source(source)
        github = parse_github_repository_source(normalized)
        if github is not None:
            try:
                content = await get_github_client().fetch_repository_file(
                    github,
                    "index.json",
                    maximum_bytes=self._maximum_index_bytes,
                )
            except GithubApiError as exc:
                raise self._connection_error_type(
                    f"无法连接在线{self._resource_label}仓库：{exc}"
                ) from exc
        else:
            content = await self._fetch_bytes(
                source=normalized,
                url=f"{normalized}/index.json",
                maximum_bytes=self._maximum_index_bytes,
                accept="application/json",
            )
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BadRequestError(
                f"在线{self._resource_label}索引不是有效 JSON。"
            ) from exc
        if not isinstance(payload, dict):
            raise BadRequestError(f"在线{self._resource_label}索引格式无效。")
        return payload

    async def download_package(
        self,
        *,
        source: str,
        package_url: str,
        expected_size: int,
        expected_sha256: str,
        target: Path,
    ) -> None:
        if expected_size < 1 or expected_size > self._maximum_package_bytes:
            raise BadRequestError(f"{self._resource_label}包大小超过允许范围。")
        resolved = self.resolve_asset_url(source, package_url)
        normalized = self.normalize_source(source)
        github = parse_github_repository_source(normalized)
        if github is not None:
            try:
                downloaded, actual_sha256 = await get_github_client().download_repository_file(
                    github,
                    resolve_github_repository_path(normalized, package_url),
                    target=target,
                    maximum_bytes=min(expected_size, self._maximum_package_bytes),
                )
            except GithubApiError as exc:
                raise BadRequestError(f"{self._resource_label}包下载失败：{exc}") from exc
            if downloaded != expected_size:
                target.unlink(missing_ok=True)
                raise BadRequestError(f"{self._resource_label}包实际大小与市场索引不一致。")
            if actual_sha256.lower() != expected_sha256.lower():
                target.unlink(missing_ok=True)
                raise BadRequestError(f"{self._resource_label}包完整性校验失败。")
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.unlink(missing_ok=True)
        digest = hashlib.sha256()
        downloaded = 0
        client = get_shared_http_client()
        try:
            with target.open("wb") as output:
                async with client.stream(
                    "GET",
                    resolved,
                    headers={"Accept": "application/zip, application/octet-stream"},
                    timeout=get_http_timeout(stream=True),
                ) as response:
                    response.raise_for_status()
                    self._require_safe_final_url(source, response.url)
                    async for chunk in response.aiter_bytes():
                        downloaded += len(chunk)
                        if (
                            downloaded > expected_size
                            or downloaded > self._maximum_package_bytes
                        ):
                            raise BadRequestError(
                                f"{self._resource_label}包实际大小与市场索引不一致。"
                            )
                        digest.update(chunk)
                        output.write(chunk)
        except httpx.HTTPError as exc:
            raise BadRequestError(f"{self._resource_label}包下载失败。") from exc
        if downloaded != expected_size:
            raise BadRequestError(
                f"{self._resource_label}包实际大小与市场索引不一致。"
            )
        if digest.hexdigest().lower() != expected_sha256.lower():
            raise BadRequestError(f"{self._resource_label}包完整性校验失败。")

    async def download_resource(
        self,
        *,
        source: str,
        resource_url: str,
        maximum_bytes: int,
        accept: str,
    ) -> bytes:
        normalized = self.normalize_source(source)
        github = parse_github_repository_source(normalized)
        if github is not None:
            try:
                return await get_github_client().fetch_repository_file(
                    github,
                    resolve_github_repository_path(normalized, resource_url),
                    maximum_bytes=maximum_bytes,
                )
            except GithubApiError as exc:
                raise BadRequestError(
                    f"在线{self._resource_label}资源下载失败：{exc}"
                ) from exc
        return await self._fetch_bytes(
            source=source,
            url=self.resolve_asset_url(source, resource_url),
            maximum_bytes=maximum_bytes,
            accept=accept,
        )

    async def _fetch_bytes(
        self,
        *,
        source: str,
        url: str,
        maximum_bytes: int,
        accept: str,
    ) -> bytes:
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
                response.raise_for_status()
                self._require_safe_final_url(source, response.url)
                async for chunk in response.aiter_bytes():
                    downloaded += len(chunk)
                    if downloaded > maximum_bytes:
                        raise BadRequestError(
                            f"在线{self._resource_label}资源超过允许大小。"
                        )
                    chunks.append(chunk)
        except httpx.HTTPError as exc:
            raise self._connection_error_type(
                f"无法连接在线{self._resource_label}仓库。"
            ) from exc
        return b"".join(chunks)

    def _require_safe_final_url(self, source: str, final_url: httpx.URL) -> None:
        require_safe_final_url(
            source,
            final_url,
            resource_label=self._resource_label,
            allow_query=self._allow_asset_query,
        )
