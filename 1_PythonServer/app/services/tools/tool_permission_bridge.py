from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from uuid import uuid4

from app.domain.llm.chat import ChatToolPermissionRequest
from app.services.tools.tool_permissions import ToolPermissionEvaluation


@dataclass(slots=True)
class _PendingToolPermissionRequest:
    request: ChatToolPermissionRequest
    future: asyncio.Future[str]
    submitted: bool = False


class ToolPermissionBridgeService:
    """Owns one-time user decisions for pending tool calls."""

    def __init__(self) -> None:
        self._pending: dict[str, _PendingToolPermissionRequest] = {}
        self._lock = asyncio.Lock()

    async def create_request(
        self,
        *,
        displayed_call_id: str,
        displayed_tool_name: str,
        project_id: str | None,
        session_id: str | None,
        evaluation: ToolPermissionEvaluation,
    ) -> ChatToolPermissionRequest:
        request = ChatToolPermissionRequest(
            request_id=uuid4().hex,
            call_id=displayed_call_id,
            name=displayed_tool_name,
            project_id=project_id,
            session_id=session_id,
            facts=tuple(
                {
                    "tool_name": fact.tool_name,
                    "parameter_name": fact.parameter_name,
                    "permission_type": fact.permission_type,
                    "scope": fact.scope,
                }
                for fact in evaluation.facts
                if fact.decision == "ask"
            ),
        )
        loop = asyncio.get_running_loop()
        async with self._lock:
            self._pending[request.request_id] = _PendingToolPermissionRequest(
                request=request,
                future=loop.create_future(),
            )
        return request

    async def wait_for_decision(self, request_id: str) -> str:
        try:
            async with self._lock:
                pending = self._pending.get(request_id)
                if pending is None:
                    return "deny"
                future = pending.future
            return await future
        finally:
            async with self._lock:
                self._pending.pop(request_id, None)

    async def submit_decision(self, request_id: str, decision: str) -> bool:
        normalized_id = request_id.strip()
        if not normalized_id or decision not in {"allow", "deny"}:
            return False
        async with self._lock:
            pending = self._pending.get(normalized_id)
            if pending is None or pending.submitted or pending.future.done():
                return False
            pending.submitted = True
            pending.future.set_result(decision)
            return True

    async def should_replay_request(self, request_id: str) -> bool:
        async with self._lock:
            pending = self._pending.get(request_id.strip())
            return bool(pending and not pending.submitted and not pending.future.done())

    async def pending_request_ids(
        self,
        *,
        project_id: str,
        session_id: str,
    ) -> tuple[str, ...]:
        async with self._lock:
            return tuple(
                request_id
                for request_id, pending in self._pending.items()
                if pending.request.project_id == project_id
                and pending.request.session_id == session_id
                and not pending.submitted
                and not pending.future.done()
            )


@lru_cache
def get_tool_permission_bridge_service() -> ToolPermissionBridgeService:
    return ToolPermissionBridgeService()
