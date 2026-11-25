from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import lru_cache
from secrets import token_urlsafe
from threading import Lock
from time import monotonic
from uuid import uuid4
from typing import Callable, TypeVar, cast

from app.domain.tools.host_capabilities import HostCapability, ProviderEndpointGrant, SessionModelEndpoint

RUN_OBSERVER_LEASE_SECONDS = 90


T = TypeVar("T")


class GrantBindings:
    """Keep selections stable through one invocation, including multi-request protocols."""

    def __init__(self):
        self._lock = Lock()
        self._values = {}

    def resolve(self, name: str, create: Callable[[], T]) -> T:
        with self._lock:
            if name not in self._values:
                self._values[name] = create()
            return cast(T, self._values[name])


@dataclass(frozen=True, slots=True)
class HostCapabilityGrant:
    grant_id: str
    token: str
    capabilities: frozenset[HostCapability]
    tool_name: str
    tool_call_id: str
    provider_id: str | None
    model_id: str | None
    project_id: str | None
    session_id: str | None
    expires_at: float
    tool_project_id: str | None = None
    enabled_tool_names: tuple[str, ...] | None = None
    run_id: str | None = None
    bindings: GrantBindings = field(default_factory=GrantBindings, repr=False, compare=False)
    observer: bool = False
    model_usage_feature: str = "tool_model_request"
    provider_endpoints: tuple[ProviderEndpointGrant, ...] = ()
    session_model_endpoints: tuple[SessionModelEndpoint, ...] = ()


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
        capabilities: tuple[HostCapability, ...] = (),
        provider_endpoints: tuple[ProviderEndpointGrant, ...] = (),
        session_model_endpoints: tuple[SessionModelEndpoint, ...] = (),
        model_usage_feature: str = "tool_model_request",
        tool_project_id: str | None = None,
        enabled_tool_names: tuple[str, ...] | None = None,
        run_id: str | None = None,
    ) -> HostCapabilityGrant | None:
        allowed_capabilities = frozenset(HostCapability(value) for value in capabilities)
        if not allowed_capabilities:
            return None

        if HostCapability.SESSION_MODEL in allowed_capabilities and (not provider_id or not model_id):
            return None

        now = monotonic()
        grant = HostCapabilityGrant(
            grant_id=uuid4().hex,
            token=token_urlsafe(32),
            capabilities=allowed_capabilities,
            provider_endpoints=provider_endpoints,
            session_model_endpoints=session_model_endpoints,
            model_usage_feature=model_usage_feature,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            provider_id=provider_id,
            model_id=model_id,
            project_id=project_id,
            session_id=session_id,
            expires_at=now + max(1, lifetime_seconds),
            tool_project_id=tool_project_id,
            enabled_tool_names=enabled_tool_names,
            run_id=run_id,
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
            if grant is None or capability not in grant.capabilities:
                return None
            return grant

    def delegate_run_observer(self, grant: HostCapabilityGrant) -> HostCapabilityGrant:
        """Delegate only read-only observation, never the parent's other powers."""
        now = monotonic()
        with self._lock:
            self._remove_expired_locked(now)
            if (self._grants.get(grant.token) != grant or grant.observer
                    or HostCapability.RUN_STATUS not in grant.capabilities or not grant.run_id):
                raise ValueError("当前授权不能申请任务观察租约。")
            observer = replace(grant, grant_id=uuid4().hex, token=token_urlsafe(32), bindings=GrantBindings(),
                provider_endpoints=(), session_model_endpoints=(), capabilities=frozenset({HostCapability.RUN_STATUS}), observer=True,
                expires_at=now + RUN_OBSERVER_LEASE_SECONDS)
            self._grants[observer.token] = observer
            return observer

    def renew_run_observer(self, token: str) -> bool:
        # Caller must first check that the bound run is still active.
        now = monotonic()
        with self._lock:
            self._remove_expired_locked(now)
            grant = self._grants.get(token)
            if grant is None or not grant.observer:
                return False
            self._grants[token] = replace(grant, expires_at=now + RUN_OBSERVER_LEASE_SECONDS)
            return True

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
