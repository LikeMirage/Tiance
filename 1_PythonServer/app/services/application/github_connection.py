from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import time
from uuid import uuid4

from app.core.errors import BadRequestError
from app.infra.github import (
    GithubApiError,
    GithubAuthenticationRequiredError,
    GithubClient,
    get_github_client,
)
from app.schemas.github_connection import (
    GithubAccountSummary,
    GithubConnectionStatusResponse,
    GithubDeviceFlowPollResponse,
    GithubDeviceFlowStartResponse,
    GithubRepositorySummary,
)


GITHUB_INSTALLATIONS_URL = "https://github.com/settings/installations"
_REQUIRED_PERMISSIONS = {
    "metadata": "read",
    "contents": "write",
    "administration": "write",
    "pull_requests": "write",
    "issues": "write",
    "actions": "write",
    "workflows": "write",
}
_PERMISSION_LEVEL = {"read": 1, "write": 2}


@dataclass(slots=True)
class _DeviceFlowSession:
    device_code: str
    user_code: str
    verification_uri: str
    expires_at: float
    interval: int
    next_poll_at: float


class GithubConnectionService:
    def __init__(self, client: GithubClient | None = None) -> None:
        self._client = client or get_github_client()
        self._flows: dict[str, _DeviceFlowSession] = {}

    async def get_status(self) -> GithubConnectionStatusResponse:
        token = await self._client.get_valid_access_token(required=False)
        if token is None:
            return self._disconnected_status()
        try:
            user = await self._client.get_authenticated_user()
            installations = await self._client.list_authorized_installations()
            repositories = await self._client.list_authorized_repositories()
        except GithubAuthenticationRequiredError:
            return self._disconnected_status()
        except GithubApiError as exc:
            raise BadRequestError(str(exc)) from exc
        login = user.get("login")
        if not isinstance(login, str) or not login:
            raise BadRequestError("GitHub 账号信息无效。")
        permissions = _merge_installation_permissions(installations)
        missing_permissions = [
            name
            for name, required in _REQUIRED_PERMISSIONS.items()
            if _PERMISSION_LEVEL.get(permissions.get(name, ""), 0)
            < _PERMISSION_LEVEL[required]
        ]
        return GithubConnectionStatusResponse(
            connected=True,
            account=GithubAccountSummary(
                login=login,
                name=user.get("name") if isinstance(user.get("name"), str) else None,
                avatar_url=str(user.get("avatar_url") or ""),
                profile_url=str(user.get("html_url") or f"https://github.com/{login}"),
            ),
            repositories=[
                GithubRepositorySummary(
                    id=repository_id,
                    full_name=full_name,
                    private=bool(item.get("private")),
                    default_branch=str(item.get("default_branch") or "main"),
                    can_push=bool(
                        isinstance(item.get("permissions"), dict)
                        and item["permissions"].get("push") is True
                    ),
                )
                for item in repositories
                if isinstance((repository_id := item.get("id")), int)
                and isinstance((full_name := item.get("full_name")), str)
                and full_name
            ],
            permissions=permissions,
            missing_permissions=missing_permissions,
            requires_reauthorization=bool(missing_permissions),
            authorization_url=GITHUB_INSTALLATIONS_URL,
        )

    async def start_device_flow(self) -> GithubDeviceFlowStartResponse:
        try:
            payload = await self._client.start_device_flow()
        except GithubApiError as exc:
            raise BadRequestError(str(exc)) from exc
        flow_id = uuid4().hex
        now = time.monotonic()
        expires_in = int(payload["expires_in"])
        interval = max(5, int(payload["interval"]))
        self._flows[flow_id] = _DeviceFlowSession(
            device_code=str(payload["device_code"]),
            user_code=str(payload["user_code"]),
            verification_uri=str(payload["verification_uri"]),
            expires_at=now + expires_in,
            interval=interval,
            next_poll_at=now,
        )
        self._prune_flows(now)
        return GithubDeviceFlowStartResponse(
            flow_id=flow_id,
            user_code=str(payload["user_code"]),
            verification_uri=str(payload["verification_uri"]),
            expires_in=expires_in,
            interval=interval,
        )

    async def poll_device_flow(self, flow_id: str) -> GithubDeviceFlowPollResponse:
        session = self._flows.get(flow_id.strip())
        if session is None:
            raise BadRequestError("GitHub 登录请求不存在或已经失效。")
        now = time.monotonic()
        if now >= session.expires_at:
            self._flows.pop(flow_id, None)
            raise BadRequestError("GitHub 登录码已过期，请重新登录。")
        if now < session.next_poll_at:
            retry_after = max(1, int(session.next_poll_at - now + 0.999))
            return GithubDeviceFlowPollResponse(status="pending", retry_after=retry_after)
        session.next_poll_at = now + session.interval
        try:
            payload = await self._client.poll_device_flow(session.device_code)
        except GithubApiError as exc:
            raise BadRequestError(str(exc)) from exc
        error = payload.get("error")
        if error == "authorization_pending":
            return GithubDeviceFlowPollResponse(status="pending", retry_after=session.interval)
        if error == "slow_down":
            session.interval += 5
            session.next_poll_at = now + session.interval
            return GithubDeviceFlowPollResponse(status="slow_down", retry_after=session.interval)
        if error in {"expired_token", "access_denied"}:
            self._flows.pop(flow_id, None)
            message = "用户取消了 GitHub 登录。" if error == "access_denied" else "GitHub 登录码已过期。"
            raise BadRequestError(message)
        if error:
            raise BadRequestError("GitHub 登录失败，请重新尝试。")
        try:
            await self._client.save_device_flow_token(payload)
        except (GithubApiError, RuntimeError) as exc:
            raise BadRequestError(str(exc)) from exc
        self._flows.pop(flow_id, None)
        return GithubDeviceFlowPollResponse(
            status="completed",
            connection=await self.get_status(),
        )

    async def logout(self) -> None:
        self._flows.clear()
        await self._client.logout()

    @staticmethod
    def _disconnected_status() -> GithubConnectionStatusResponse:
        return GithubConnectionStatusResponse(
            connected=False,
            authorization_url=GITHUB_INSTALLATIONS_URL,
        )

    def _prune_flows(self, now: float) -> None:
        for flow_id, session in tuple(self._flows.items()):
            if session.expires_at <= now:
                self._flows.pop(flow_id, None)


@lru_cache
def get_github_connection_service() -> GithubConnectionService:
    return GithubConnectionService()


def _merge_installation_permissions(installations: list[dict]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for installation in installations:
        raw = installation.get("permissions")
        if not isinstance(raw, dict):
            continue
        for name, level in raw.items():
            if not isinstance(name, str) or not isinstance(level, str):
                continue
            if _PERMISSION_LEVEL.get(level, 0) > _PERMISSION_LEVEL.get(merged.get(name, ""), 0):
                merged[name] = level
    return dict(sorted(merged.items()))
