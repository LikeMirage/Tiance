import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event

import httpx
import pytest

from app.infra.github import client as client_module
from app.infra.github.client import GithubApiError, GithubAuthenticationRequiredError, GithubClient, GithubRepositorySource
from app.repositories.github_auth_repository import GithubAuthRepository, GithubCredentials


OLD = GithubCredentials("fake-old", None, None, None)
NEW = GithubCredentials("fake-new", None, None, None)


@pytest.fixture
def repository(tmp_path, monkeypatch):
    monkeypatch.setattr("app.repositories.github_auth_repository.encrypt_secret", lambda value: "encrypted:" + value)
    monkeypatch.setattr("app.repositories.github_auth_repository.decrypt_secret", lambda value: value.removeprefix("encrypted:"))
    monkeypatch.setattr(client_module, "get_http_timeout", lambda **_: 1)
    repository = GithubAuthRepository(tmp_path / "auth.json")
    repository.save(OLD)
    return repository


@pytest.mark.parametrize("channel", ["json", "explicit_bytes", "fetch_bytes", "download", "upload"])
@pytest.mark.parametrize("new_login_during_request", [False, True])
def test_401_only_clears_the_credentials_used_by_that_request(repository, tmp_path, monkeypatch, channel, new_login_during_request):
    client = GithubClient(client_id="test", auth_repository=repository)
    seen = []

    def response(request):
        seen.append(request.headers.get("Authorization"))
        if new_login_during_request:
            repository.save(NEW)
        return httpx.Response(401, json={"message": "expired"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
            monkeypatch.setattr(client_module, "get_shared_http_client", lambda: http)
            with pytest.raises(GithubAuthenticationRequiredError):
                if channel == "json":
                    await client.get_authenticated_user_with_token(OLD.access_token)
                elif channel == "explicit_bytes":
                    await client.request_bytes("/repos/o/r/archive", access_token=OLD.access_token, maximum_bytes=100)
                elif channel == "fetch_bytes":
                    await client._fetch_bytes("https://api.github.com/test", maximum_bytes=100, accept="application/octet-stream", required_auth=True)
                elif channel == "download":
                    await client._download_to_file("https://api.github.com/test", target=tmp_path / "download", maximum_bytes=100, accept="application/octet-stream", required_auth=True)
                else:
                    source = tmp_path / "upload.txt"
                    source.write_text("test", encoding="utf-8")
                    await client.upload_release_asset(GithubRepositorySource("o", "r"), 1, name="upload.txt", content_type="text/plain", source=source, maximum_bytes=100, access_token=OLD.access_token)

    asyncio.run(run())
    assert seen == ["Bearer fake-old"]
    assert repository.read() == (NEW if new_login_during_request else None)


@pytest.mark.parametrize("token", [None, "fake-unrelated"])
def test_anonymous_or_unrelated_token_failure_preserves_saved_login(repository, monkeypatch, token):
    client = GithubClient(client_id="test", auth_repository=repository)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(401))) as http:
            monkeypatch.setattr(client_module, "get_shared_http_client", lambda: http)
            with pytest.raises(GithubAuthenticationRequiredError):
                await client._request("GET", "https://api.github.com/user", token=token)
    asyncio.run(run())
    assert repository.read() == OLD


@pytest.mark.parametrize("status", [403, 404, 429, 500])
def test_non_auth_failure_does_not_clear_login(repository, status):
    client = GithubClient(client_id="test", auth_repository=repository)
    with pytest.raises(GithubApiError):
        asyncio.run(client._raise_for_status(httpx.Response(status), token=OLD.access_token))
    assert repository.read() == OLD


def test_credential_compare_and_delete_cannot_interleave_with_new_login(repository, monkeypatch):
    other_repository = GithubAuthRepository(repository._credentials_path)
    read_started, release_read, saving_started, saving_finished = Event(), Event(), Event(), Event()
    original_read = repository._read
    def delayed_read():
        credentials = original_read()
        read_started.set()
        assert release_read.wait(3)
        return credentials
    monkeypatch.setattr(repository, "_read", delayed_read)
    def save_new():
        saving_started.set()
        other_repository.save(NEW)
        saving_finished.set()
    with ThreadPoolExecutor(max_workers=2) as executor:
        deleting = executor.submit(repository.delete_if_access_token_matches, OLD.access_token)
        try:
            assert read_started.wait(3)
            saving = executor.submit(save_new)
            assert saving_started.wait(3)
            assert not saving_finished.wait(0.05)
        finally:
            release_read.set()
        deleting.result(timeout=3)
        saving.result(timeout=3)
    assert other_repository.read() == NEW


def test_failed_refresh_does_not_delete_login_saved_while_waiting(repository, monkeypatch):
    repository.save(GithubCredentials("fake-old", datetime.now(timezone.utc) - timedelta(seconds=1), "refresh-old", None))
    client = GithubClient(client_id="test", auth_repository=repository)
    async def failed_refresh(*_):
        repository.save(NEW)
        return {"error": "invalid_grant"}
    monkeypatch.setattr(client, "_oauth_post", failed_refresh)
    with pytest.raises(GithubAuthenticationRequiredError):
        asyncio.run(client.get_valid_access_token(required=True))
    assert repository.read() == NEW


def test_explicit_logout_still_removes_saved_credentials(repository):
    client = GithubClient(client_id="test", auth_repository=repository)
    asyncio.run(client.logout())
    assert repository.read() is None
