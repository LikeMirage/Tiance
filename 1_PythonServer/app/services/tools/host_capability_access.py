from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from secrets import token_urlsafe
from threading import Lock
from time import monotonic
from uuid import uuid4


class HostCapability(StrEnum):
    WEB_SEARCH = "web_search"


@dataclass(frozen=True, slots=True)
class HostCapabilityGrant:
    grant_id: str
    token: str
    capability: HostCapability
    tool_name: str
    tool_call_id: str
    provider_id: str
    model_id: str
    project_id: str | None
    session_id: str | None
    expires_at: float


_TOOL_CAPABILITY_POLICY: dict[str, frozenset[HostCapability]] = {
    "network_search": frozenset({HostCapability.WEB_SEARCH}),
}


class HostCapabilityAccessService:
    def __init__(self) -> None:
        self._grants: dict[str, HostCapabilityGrant] = {}
        self._lock = Lock()

    def issue_grant(
        self,
        *,
        tool_name: str,
        tool_call_id: str,
        provider_id: str | None,
        model_id: str | None,
        project_id: str | None,
        session_id: str | None,
        lifetime_seconds: int,
    ) -> HostCapabilityGrant | None:
        allowed_capabilities = _TOOL_CAPABILITY_POLICY.get(tool_name, frozenset())
        if (
            HostCapability.WEB_SEARCH not in allowed_capabilities
            or not provider_id
            or not model_id
        ):
            return None

        now = monotonic()
        grant = HostCapabilityGrant(
            grant_id=uuid4().hex,
            token=token_urlsafe(32),
            capability=HostCapability.WEB_SEARCH,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            provider_id=provider_id,
            model_id=model_id,
            project_id=project_id,
            session_id=session_id,
            expires_at=now + max(1, lifetime_seconds),
        )
        with self._lock:
            self._remove_expired_locked(now)
            self._grants[grant.token] = grant
        return grant

    def authorize(
        self,
        token: str,
        capability: HostCapability,
    ) -> HostCapabilityGrant | None:
        normalized_token = token.strip()
        if not normalized_token:
            return None
        now = monotonic()
        with self._lock:
            self._remove_expired_locked(now)
            grant = self._grants.get(normalized_token)
            if grant is None or grant.capability != capability:
                return None
            return grant

    def revoke(self, token: str) -> None:
        with self._lock:
            self._grants.pop(token, None)

    def _remove_expired_locked(self, now: float) -> None:
        expired_tokens = [
            token
            for token, grant in self._grants.items()
            if grant.expires_at <= now
        ]
        for token in expired_tokens:
            self._grants.pop(token, None)


@lru_cache
def get_host_capability_access_service() -> HostCapabilityAccessService:
    return HostCapabilityAccessService()
