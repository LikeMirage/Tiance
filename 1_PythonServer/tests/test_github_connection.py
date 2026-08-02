from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json

import pytest

from app.infra.github import (
    GithubApiError,
    normalize_github_repository_source,
    parse_github_repository_source,
    resolve_github_repository_path,
)
from app.infra.online_market.remote_client import OnlineMarketRemoteClient
from app.repositories.github_auth_repository import GithubAuthRepository, GithubCredentials
from app.services.application.github_connection import GithubConnectionService


class _FakeGithubClient:
    def __init__(self) -> None:
        self.saved_payload: dict[str, object] | None = None
        self.requested_files: list[str] = []

    async def get_valid_access_token(self, *, required: bool) -> str | None:
        return "token"

    async def get_authenticated_user(self) -> dict[str, object]:
        return {
            "login": "LikeMirage",
            "name": "Like Mirage",
            "avatar_url": "https://avatars.githubusercontent.com/u/1",
            "html_url": "https://github.com/LikeMirage",
        }

    async def list_authorized_repositories(self) -> list[dict[str, object]]:
        return [{
            "id": 42,
            "full_name": "example/private-projects",
            "private": True,
            "default_branch": "main",
        }]

    async def list_authorized_installations(self) -> list[dict[str, object]]:
        return [{"id": 7, "permissions": {
            "metadata": "read", "contents": "write", "administration": "write",
            "pull_requests": "write", "issues": "write", "actions": "write",
            "workflows": "write",
        }}]

    async def start_device_flow(self) -> dict[str, object]:
        return {
            "device_code": "device-secret",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        }

    async def poll_device_flow(self, _device_code: str) -> dict[str, object]:
        return {"access_token": "github-token"}

    async def save_device_flow_token(self, payload: dict[str, object]) -> None:
        self.saved_payload = payload

    async def logout(self) -> None:
        return None

    async def fetch_repository_file(self, _repository, path: str, **_kwargs) -> bytes:
        self.requested_files.append(path)
        return json.dumps({"schemaVersion": 1, "items": []}).encode()


def test_github_repository_source_and_resources_are_scoped() -> None:
    assert normalize_github_repository_source(
        "https://github.com/example/private-projects.git"
    ) == "https://github.com/example/private-projects"
    assert parse_github_repository_source("https://github.com/a/b/tree/main") is None
    assert resolve_github_repository_path(
        "https://github.com/example/private-projects",
        "https://raw.githubusercontent.com/example/private-projects/main/packages/a.zip",
    ) == "packages/a.zip"
    with pytest.raises(GithubApiError, match="不属于当前仓库"):
        resolve_github_repository_path(
            "https://github.com/example/private-projects",
            "https://raw.githubusercontent.com/other/repo/main/index.json",
        )


def test_github_credentials_are_encrypted_at_rest(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.repositories.github_auth_repository.encrypt_secret",
        lambda value: f"cipher:{value[::-1]}",
    )
    monkeypatch.setattr(
        "app.repositories.github_auth_repository.decrypt_secret",
        lambda value: value.removeprefix("cipher:")[::-1],
    )
    path = tmp_path / "secrets" / "github-auth.json"
    repository = GithubAuthRepository(path)
    credentials = GithubCredentials(
        access_token="access-secret",
        access_expires_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        refresh_token="refresh-secret",
        refresh_expires_at=None,
    )

    repository.save(credentials)

    raw = path.read_text(encoding="utf-8")
    assert "access-secret" not in raw
    assert "refresh-secret" not in raw
    assert repository.read() == credentials
    repository.delete()
    assert not path.exists()


def test_device_flow_completion_returns_authorized_repositories() -> None:
    client = _FakeGithubClient()
    service = GithubConnectionService(client=client)  # type: ignore[arg-type]

    async def run():
        flow = await service.start_device_flow()
        result = await service.poll_device_flow(flow.flow_id)
        return result

    result = asyncio.run(run())

    assert result.status == "completed"
    assert result.connection is not None
    assert result.connection.connected is True
    assert result.connection.repositories[0].full_name == "example/private-projects"
    assert result.connection.requires_reauthorization is False
    assert client.saved_payload == {"access_token": "github-token"}


def test_shared_market_uses_github_transport_for_repository_source(monkeypatch) -> None:
    client = _FakeGithubClient()
    monkeypatch.setattr(
        "app.infra.online_market.remote_client.get_github_client",
        lambda: client,
    )
    remote = OnlineMarketRemoteClient(
        resource_label="工具",
        maximum_index_bytes=1024,
        maximum_package_bytes=1024,
    )

    result = asyncio.run(remote.fetch_index("https://github.com/LikeMirage/private-tools"))

    assert result["schemaVersion"] == 1
    assert client.requested_files == ["index.json"]
