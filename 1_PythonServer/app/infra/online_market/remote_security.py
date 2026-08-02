from __future__ import annotations

from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from app.core.errors import BadRequestError
from app.infra.github import (
    GithubApiError,
    normalize_github_repository_source,
    parse_github_repository_source,
    resolve_github_repository_path,
)


def normalize_market_source(raw_source: str, *, resource_label: str) -> str:
    text = raw_source.strip()
    try:
        parts = urlsplit(text)
    except ValueError as exc:
        raise BadRequestError(f"在线{resource_label}仓库地址无效。") from exc
    if parts.username or parts.password or parts.query or parts.fragment:
        raise BadRequestError(f"在线{resource_label}仓库地址无效。")
    hostname = (parts.hostname or "").lower()
    is_local_http = parts.scheme == "http" and hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
    }
    if parts.scheme != "https" and not is_local_http:
        raise BadRequestError(f"在线{resource_label}仓库必须使用 HTTPS。")
    if not hostname:
        raise BadRequestError(f"在线{resource_label}仓库地址无效。")
    github_source = normalize_github_repository_source(text)
    if hostname == "github.com":
        if github_source is None:
            raise BadRequestError(f"在线{resource_label} GitHub 地址必须指向仓库根目录。")
        return github_source
    path = parts.path.rstrip("/")
    if path.endswith("/index.json"):
        path = path[: -len("/index.json")]
    return urlunsplit((parts.scheme, parts.netloc, path, "", "")).rstrip("/")


def resolve_market_asset_url(
    source: str,
    raw_url: str,
    *,
    resource_label: str,
    allow_query: bool = True,
) -> str:
    normalized_source = normalize_market_source(source, resource_label=resource_label)
    if parse_github_repository_source(normalized_source) is not None:
        try:
            path = resolve_github_repository_path(normalized_source, raw_url)
        except GithubApiError as exc:
            raise BadRequestError(str(exc)) from exc
        return f"{normalized_source}/{path}"
    resolved = urljoin(f"{normalized_source}/", raw_url.strip())
    _require_same_market_scope(
        normalized_source,
        resolved,
        resource_label=resource_label,
        allow_query=allow_query,
    )
    return resolved


def require_safe_final_url(
    source: str,
    final_url: httpx.URL | str,
    *,
    resource_label: str,
    allow_query: bool = True,
) -> None:
    if parse_github_repository_source(source) is not None:
        raise BadRequestError(f"{resource_label} GitHub 资源必须通过认证传输层读取。")
    _require_same_market_scope(
        normalize_market_source(source, resource_label=resource_label),
        str(final_url),
        resource_label=resource_label,
        allow_query=allow_query,
    )


def _require_same_market_scope(
    source: str,
    target: str,
    *,
    resource_label: str,
    allow_query: bool,
) -> None:
    source_parts = urlsplit(source)
    target_parts = urlsplit(target)
    if (
        source_parts.scheme.lower(),
        (source_parts.hostname or "").lower(),
        source_parts.port,
    ) != (
        target_parts.scheme.lower(),
        (target_parts.hostname or "").lower(),
        target_parts.port,
    ):
        raise BadRequestError(f"{resource_label}资源地址必须与市场地址同源。")
    if (
        target_parts.username
        or target_parts.password
        or target_parts.fragment
        or (target_parts.query and not allow_query)
    ):
        raise BadRequestError(f"{resource_label}资源地址无效。")
    source_path = source_parts.path.rstrip("/")
    target_path = target_parts.path
    if source_path and target_path != source_path and not target_path.startswith(f"{source_path}/"):
        raise BadRequestError(f"{resource_label}资源地址必须位于市场目录内。")
