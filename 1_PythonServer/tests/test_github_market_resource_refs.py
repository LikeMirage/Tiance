import asyncio
import hashlib
from urllib.parse import unquote, urlsplit

import httpx
import pytest

from app.infra.github import (
    GithubApiError, GithubClient, GithubRepositorySource,
    normalize_github_repository_resource, resolve_github_repository_path,
)
from app.infra.online_market.remote_client import OnlineMarketRemoteClient
from app.infra.project_market.remote_client import ProjectMarketRemoteClient
from app.schemas.project.project_market import ProjectMarketDownload


SOURCE = "https://github.com/example/market"
REPOSITORY = GithubRepositorySource("example", "market")
CONTENT = b"package-or-preview"


@pytest.fixture
def github(monkeypatch):
    class NoCredentials:
        def read(self):
            return None

    client = GithubClient(client_id="test", auth_repository=NoCredentials())
    refs = {"heads/main", "heads/feature/new-tool", "tags/release/2026/10"}
    calls = []

    async def request(method, url, *, token, **kwargs):
        request = httpx.Request(method, url)
        calls.append(request)
        path = unquote(request.url.path)
        if "/git/ref/" in path:
            ref = path.split("/git/ref/", 1)[1]
            if ref not in refs:
                raise GithubApiError("missing ref", status_code=404)
            return httpx.Response(200, json={"ref": "refs/" + ref, "object": {"sha": "a" * 40}}, request=request)
        raise AssertionError(url)

    async def fetch(url, **kwargs):
        calls.append(httpx.Request("GET", url))
        return CONTENT

    async def download(url, *, target, **kwargs):
        calls.append(httpx.Request("GET", url))
        target.write_bytes(CONTENT)
        return len(CONTENT), hashlib.sha256(CONTENT).hexdigest()

    monkeypatch.setattr(client, "_request", request)
    monkeypatch.setattr(client, "_fetch_bytes", fetch)
    monkeypatch.setattr(client, "_download_to_file", download)
    monkeypatch.setattr("app.infra.project_market.remote_client.get_github_client", lambda: client)
    monkeypatch.setattr("app.infra.online_market.remote_client.get_github_client", lambda: client)
    return client, calls, refs


@pytest.mark.parametrize("prefix", [
    SOURCE + "/blob/", SOURCE + "/raw/", "https://raw.githubusercontent.com/example/market/",
])
@pytest.mark.parametrize("ref", ["main", "feature/new-tool", "release/2026/10", "a" * 40])
def test_full_urls_resolve_branch_tag_or_commit_before_fetching(github, prefix, ref):
    client, calls, _ = github
    content = asyncio.run(client.fetch_repository_file(
        REPOSITORY, f"{prefix}{ref}/packages/tool.zip", maximum_bytes=100,
    ))
    assert content == CONTENT
    assert calls[-1].url.path == "/repos/example/market/contents/packages/tool.zip"
    assert calls[-1].url.params["ref"] == ref


def test_explicit_ref_avoids_lookup_and_sync_helper_requires_a_known_boundary(github):
    client, calls, _ = github
    url = SOURCE + "/blob/feature/new-tool/packages/tool.zip"
    assert resolve_github_repository_path(SOURCE, url, ref="feature/new-tool") == "packages/tool.zip"
    with pytest.raises(GithubApiError, match="确认完整"):
        resolve_github_repository_path(SOURCE, url)
    asyncio.run(client.fetch_repository_file(REPOSITORY, url, maximum_bytes=100, ref="feature/new-tool"))
    assert len(calls) == 1
    assert calls[0].url.params["ref"] == "feature/new-tool"


def test_encoded_ref_and_filename_are_decoded_once(github):
    client, calls, _ = github
    asyncio.run(client.fetch_repository_file(
        REPOSITORY, SOURCE + "/blob/feature%2Fnew-tool/docs/a%20b%25.txt", maximum_bytes=100,
    ))
    assert len(calls) == 1
    assert calls[0].url.params["ref"] == "feature/new-tool"
    assert calls[0].url.path == "/repos/example/market/contents/docs/a b%.txt"


def test_url_ref_is_not_replaced_by_market_default(github):
    client, calls, _ = github
    asyncio.run(client.fetch_repository_file(
        REPOSITORY, SOURCE + "/blob/feature/new-tool/preview.png", maximum_bytes=100, ref="main",
    ))
    assert calls[-1].url.params["ref"] == "feature/new-tool"
    assert calls[-1].url.path.endswith("/contents/preview.png")


def test_relative_paths_keep_existing_default_branch_behavior(github):
    client, calls, _ = github
    asyncio.run(client.fetch_repository_file(REPOSITORY, "packages/tool.zip", maximum_bytes=100))
    assert len(calls) == 1
    assert "ref" not in calls[0].url.params


def test_github_page_query_and_line_fragment_do_not_change_the_file_or_leak_to_api(github):
    client, calls, _ = github
    asyncio.run(client.fetch_repository_file(
        REPOSITORY, SOURCE + "/blob/main/docs/a.md?raw=true#L10", maximum_bytes=100, ref="main",
    ))
    assert calls[-1].url.path.endswith("/contents/docs/a.md")
    assert dict(calls[-1].url.params) == {"ref": "main"}
    assert not calls[-1].url.fragment


@pytest.mark.parametrize("status", [401, 403, 422, 429, 500])
def test_ref_lookup_does_not_hide_auth_rate_limit_or_server_errors(github, monkeypatch, status):
    client, calls, _ = github
    lookup_calls = []
    async def fail(path, **kwargs):
        lookup_calls.append(path)
        raise GithubApiError("upstream failure", status_code=status)
    monkeypatch.setattr(client, "_get_json", fail)
    with pytest.raises(GithubApiError) as error:
        asyncio.run(client.fetch_repository_file(
            REPOSITORY, SOURCE + "/blob/unknown/branch/file.zip", maximum_bytes=100,
        ))
    assert error.value.status_code == status
    assert len(lookup_calls) == 1
    assert not calls


def test_missing_ref_never_downloads_a_default_branch_file(github):
    client, calls, _ = github
    with pytest.raises(GithubApiError, match="不存在"):
        asyncio.run(client.fetch_repository_file(
            REPOSITORY, SOURCE + "/blob/unknown/branch/tool.zip", maximum_bytes=100,
        ))
    assert all("/git/ref/" in request.url.path for request in calls)


@pytest.mark.parametrize("url", [
    "https://github.com/other/market/blob/main/a.zip",
    "https://example.invalid/example/market/blob/main/a.zip",
    "https://user:password@github.com/example/market/blob/main/a.zip",
    "https://github.com:8443/example/market/blob/main/a.zip",
    SOURCE + "/blob/main/%2e%2e/a.zip",
    SOURCE + "/blob/main/%5c..%5ca.zip",
    "//github.com/example/market/blob/main/a.zip",
])
def test_invalid_resource_is_rejected_before_any_network_request(github, url):
    client, calls, _ = github
    with pytest.raises(GithubApiError):
        asyncio.run(client.fetch_repository_file(REPOSITORY, url, maximum_bytes=100))
    assert not calls


def test_project_market_download_and_preview_use_complete_ref(github, tmp_path):
    _, calls, _ = github
    market = ProjectMarketRemoteClient()
    target = tmp_path / "package.zip"
    asyncio.run(market.download_package(
        source=SOURCE, default_ref="main", target=target,
        download=ProjectMarketDownload(
            kind="archive", url=SOURCE + "/blob/feature/new-tool/packages/tool.zip",
            ref="feature/new-tool", size=len(CONTENT), sha256=hashlib.sha256(CONTENT).hexdigest(),
        ),
    ))
    assert target.read_bytes() == CONTENT
    assert calls[-1].url.params["ref"] == "feature/new-tool"
    assert calls[-1].url.path.endswith("/contents/packages/tool.zip")
    result = asyncio.run(market.download_preview(
        source=SOURCE, preview_url=SOURCE + "/blob/release/2026/10/images/preview.png", default_ref="main",
    ))
    assert result == CONTENT
    assert calls[-1].url.params["ref"] == "release/2026/10"
    assert calls[-1].url.path.endswith("/contents/images/preview.png")


def test_shared_tool_role_theme_market_preserves_url_ref(github, tmp_path):
    _, calls, _ = github
    market = OnlineMarketRemoteClient(resource_label="工具", maximum_index_bytes=100, maximum_package_bytes=100)
    url = SOURCE + "/blob/feature/new-tool/packages/tool.zip"
    assert market.resolve_asset_url(SOURCE, url) == url
    assert normalize_github_repository_resource(SOURCE, url) == url
    asyncio.run(market.download_package(
        source=SOURCE, package_url=url, expected_size=len(CONTENT),
        expected_sha256=hashlib.sha256(CONTENT).hexdigest(), target=tmp_path / "package.zip",
    ))
    assert calls[-1].url.params["ref"] == "feature/new-tool"
    assert calls[-1].url.path.endswith("/contents/packages/tool.zip")
    result = asyncio.run(market.download_resource(source=SOURCE, resource_url=url, maximum_bytes=100, accept="image/*"))
    assert result == CONTENT
    assert calls[-1].url.params["ref"] == "feature/new-tool"
