from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from json import dumps
from typing import Any
from uuid import uuid4

from app.domain.llm.chat import ChatClientToolRequest, ChatToolCall, ChatToolResult


# Clients use one third of this value as their status-check
# interval. It is NOT an execution timeout or an ownership expiry.
CLIENT_TOOL_EXECUTOR_LEASE_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class ClientToolResultPayload:
    ok: bool
    content: Any = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ClientToolClaimLease:
    acquired: bool
    claim_id: str | None = None
    lease_duration_seconds: float | None = None
    resumed: bool = False
    attempt_id: str | None = None


@dataclass(slots=True)
class _PendingClientToolRequest:
    request: ChatClientToolRequest
    future: asyncio.Future[ClientToolResultPayload]
    loop: asyncio.AbstractEventLoop
    execution_deadline: float
    submitted: bool = False
    claimed_by: str | None = None
    claim_id: str | None = None
    attempt_id: str | None = None


class ClientToolBridgeService:
    """Coordinates frontend tool ownership and result delivery.

    Ownership survives transport interruptions until the configured tool deadline
    or caller cancellation. A missed heartbeat must not terminate a tool or hand
    its side effects to another executor. Claim attempts are idempotent, distinct
    from the frontend's persisted evidence that execution has actually begun.
    """

    def __init__(self, *, lease_duration_seconds: float = CLIENT_TOOL_EXECUTOR_LEASE_SECONDS) -> None:
        if lease_duration_seconds <= 0:
            raise ValueError("Client tool executor lease duration must be positive.")
        self._pending: dict[str, _PendingClientToolRequest] = {}
        self._lock = asyncio.Lock()
        self._lease_duration_seconds = float(lease_duration_seconds)

    async def create_request(
        self,
        tool_call: ChatToolCall,
        *,
        project_id: str | None,
        session_id: str | None,
        timeout_seconds: int,
        model_context: dict[str, Any] | None = None,
        capability=None,
        tool_project_id: str | None = None,
    ) -> ChatClientToolRequest:
        request = ChatClientToolRequest(
            request_id=uuid4().hex,
            call_id=tool_call.call_id,
            name=tool_call.name,
            arguments=tool_call.arguments,
            project_id=project_id,
            session_id=session_id,
            timeout_seconds=timeout_seconds,
            model_context=dict(model_context or {}),
            capability=capability,
            tool_project_id=tool_project_id,
        )
        loop = asyncio.get_running_loop()
        pending = _PendingClientToolRequest(
            request=request,
            future=loop.create_future(),
            loop=loop,
            execution_deadline=loop.time() + timeout_seconds,
        )
        async with self._lock:
            self._pending[request.request_id] = pending
        return request

    async def wait_for_result(
        self,
        request_id: str,
        *,
        timeout_seconds: int,
    ) -> ClientToolResultPayload:
        loop = asyncio.get_running_loop()
        wait_deadline = loop.time() + timeout_seconds
        try:
            while True:
                async with self._lock:
                    pending = self._pending.get(request_id)
                    if pending is None:
                        return ClientToolResultPayload(
                            ok=False,
                            error="客户端工具请求不存在。",
                        )
                    self._expire_request(pending)
                    future = pending.future
                    execution_deadline = min(wait_deadline, pending.execution_deadline)

                if future.cancelled():
                    raise TimeoutError
                if future.done():
                    return future.result()

                now = loop.time()
                remaining_execution = execution_deadline - now
                if remaining_execution <= 0:
                    raise TimeoutError
                done, _ = await asyncio.wait({future}, timeout=remaining_execution)
                if done:
                    if future.cancelled():
                        raise TimeoutError
                    return future.result()
        finally:
            async with self._lock:
                pending = self._pending.pop(request_id, None)
                if pending is not None and not pending.future.done():
                    pending.future.cancel()

    async def submit_result(
        self,
        request_id: str,
        result: ClientToolResultPayload,
        *,
        executor_id: str,
        claim_id: str,
    ) -> bool:
        normalized_request_id = request_id.strip()
        normalized_executor_id = executor_id.strip()
        normalized_claim_id = claim_id.strip()
        if not normalized_request_id or not normalized_executor_id or not normalized_claim_id:
            return False
        async with self._lock:
            pending = self._pending.get(normalized_request_id)
            if pending is None:
                return False
            self._expire_request(pending)
            if (
                pending.submitted
                or pending.future.done()
                or pending.claimed_by != normalized_executor_id
                or pending.claim_id != normalized_claim_id
            ):
                return False
            pending.submitted = True
            pending.future.set_result(result)
            return True

    async def claim_request(
        self,
        request_id: str,
        *,
        executor_id: str,
        attempt_id: str | None = None,
    ) -> ClientToolClaimLease:
        normalized_request_id = request_id.strip()
        normalized_executor_id = executor_id.strip()
        if not normalized_request_id or not normalized_executor_id:
            return ClientToolClaimLease(acquired=False)
        async with self._lock:
            pending = self._pending.get(normalized_request_id)
            if pending is None:
                return ClientToolClaimLease(acquired=False)
            self._expire_request(pending)
            if pending.submitted or pending.future.done():
                return ClientToolClaimLease(acquired=False)

            resumed = pending.claimed_by == normalized_executor_id
            if pending.claimed_by is not None and not resumed:
                return ClientToolClaimLease(acquired=False)
            if not resumed:
                pending.claimed_by = normalized_executor_id
                pending.claim_id = uuid4().hex
                pending.attempt_id = (attempt_id or "").strip() or None
            return ClientToolClaimLease(
                acquired=True,
                claim_id=pending.claim_id,
                lease_duration_seconds=self._lease_duration_seconds,
                resumed=resumed,
                attempt_id=pending.attempt_id,
            )

    async def renew_claim(
        self,
        request_id: str,
        *,
        executor_id: str,
        claim_id: str,
    ) -> bool:
        normalized_request_id = request_id.strip()
        normalized_executor_id = executor_id.strip()
        normalized_claim_id = claim_id.strip()
        if not normalized_request_id or not normalized_executor_id or not normalized_claim_id:
            return False
        async with self._lock:
            pending = self._pending.get(normalized_request_id)
            if pending is None:
                return False
            self._expire_request(pending)
            if (
                pending.submitted
                or pending.future.done()
                or pending.claimed_by != normalized_executor_id
                or pending.claim_id != normalized_claim_id
            ):
                return False
            return True

    async def should_replay_request(self, request_id: str) -> bool:
        normalized_request_id = request_id.strip()
        if not normalized_request_id:
            return False
        async with self._lock:
            pending = self._pending.get(normalized_request_id)
            if pending is None:
                return False
            self._expire_request(pending)
            return not pending.submitted and not pending.future.done()

    async def pending_request_ids(
        self,
        *,
        project_id: str,
        session_id: str,
    ) -> tuple[str, ...]:
        async with self._lock:
            request_ids: list[str] = []
            for request_id, pending in self._pending.items():
                self._expire_request(pending)
                if (
                    pending.request.project_id == project_id
                    and pending.request.session_id == session_id
                    and not pending.submitted
                    and not pending.future.done()
                ):
                    request_ids.append(request_id)
            return tuple(request_ids)

    @staticmethod
    def _expire_request(pending: _PendingClientToolRequest) -> None:
        # Every entry point enforces the same original deadline, including when
        # the waiter has not resumed yet. Reconnect/renewal never extends it.
        if not pending.future.done() and pending.loop.time() >= pending.execution_deadline:
            pending.future.cancel()


def client_tool_result_to_chat_tool_result(
    tool_call: ChatToolCall,
    result: ClientToolResultPayload,
    *,
    tool_project_id: str | None = None,
    dynamic: bool | None = None,
) -> ChatToolResult:
    content_payload = _build_content_payload(result)
    return ChatToolResult(
        call_id=tool_call.call_id,
        name=tool_call.name,
        arguments=tool_call.arguments,
        ok=result.ok,
        content=dumps(content_payload, ensure_ascii=False, separators=(",", ":")),
        error=None if result.ok else (result.error or "客户端工具执行失败。"),
        tool_project_id=tool_project_id,
        dynamic=dynamic,
    )


def _build_content_payload(result: ClientToolResultPayload) -> dict[str, Any]:
    if isinstance(result.content, dict):
        payload = dict(result.content)
    elif result.content is None:
        payload = {}
    else:
        payload = {"result": result.content}
    payload["ok"] = result.ok
    if result.error:
        payload["error"] = result.error
    return payload


@lru_cache
def get_client_tool_bridge_service() -> ClientToolBridgeService:
    return ClientToolBridgeService()
