from __future__ import annotations

import asyncio

import pytest

from app.core.errors import BadRequestError
from app.services.application.github_platform import GithubPlatformService


class _Projects:
    def get_project(self, _project_id: str):
        return None


class _Github:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    async def get_valid_access_token(self, *, required: bool):
        return "token"

    async def request_json(self, method: str, path: str, *, access_token: str, json_body=None, **_kwargs):
        self.calls.append((method, path, json_body))
        if method == "GET":
            return {"id": 1, "full_name": "owner/repo", "default_branch": "main"}
        return {"id": 2, "full_name": "owner/new-repo", "default_branch": "main"}

    async def request_json_list(self, method: str, path: str, *, access_token: str, json_body=None, **_kwargs):
        self.calls.append((method, path, json_body))
        return []

    async def list_repositories_for_sync(self, *, access_token: str):
        return []


def test_dry_run_does_not_send_mutation() -> None:
    github = _Github()
    service = GithubPlatformService(github, _Projects())  # type: ignore[arg-type]

    result = asyncio.run(service.execute(
        tool_name="github_repository",
        project_id=None,
        action="delete_repository",
        dry_run=True,
        parameters={"repository": "owner/repo"},
        fallback_token=None,
    ))

    assert result["dryRun"] is True
    assert all(method == "GET" for method, _path, _body in github.calls)


def test_create_repository_calls_github_once() -> None:
    github = _Github()
    service = GithubPlatformService(github, _Projects())  # type: ignore[arg-type]

    result = asyncio.run(service.execute(
        tool_name="github_repository",
        project_id=None,
        action="create_repository",
        dry_run=False,
        parameters={"name": "new-repo", "private": True},
        fallback_token=None,
    ))

    assert result["repository"]["full_name"] == "owner/new-repo"
    assert github.calls == [("POST", "/user/repos", {"name": "new-repo", "private": True})]


def test_tool_cannot_call_another_tools_action() -> None:
    service = GithubPlatformService(_Github(), _Projects())  # type: ignore[arg-type]

    with pytest.raises(BadRequestError, match="不支持操作"):
        asyncio.run(service.execute(
            tool_name="github_issue",
            project_id=None,
            action="merge",
            dry_run=True,
            parameters={"repository": "owner/repo", "number": 1},
            fallback_token=None,
        ))
