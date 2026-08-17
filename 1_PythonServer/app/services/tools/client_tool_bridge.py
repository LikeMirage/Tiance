from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from json import dumps
from typing import Any
from uuid import uuid4

from app.domain.llm.chat import ChatClientToolRequest, ChatToolCall, ChatToolResult


@dataclass(frozen=True, slots=True)
class ClientToolResultPayload:
    ok: bool
    content: Any = None
    error: str | None = None


@dataclass(slots=True)
class _PendingClientToolRequest:
    request: ChatClientToolRequest
    future: asyncio.Future[ClientToolResultPayload]
    loop: asyncio.AbstractEventLoop
    submitted: bool = False
    claimed: bool = False


class ClientToolBridgeService:
    def __init__(self) -> None:
        self._pending: dict[str, _PendingClientToolRequest] = {}
        self._lock = asyncio.Lock()

    async def create_request(
        self,
        tool_call: ChatToolCall,
        *,
        project_id: str | None,
        session_id: str | None,
        timeout_seconds: int,
        model_context: dict[str, Any] | None = None,
        capability=None,
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
        )
        loop = asyncio.get_running_loop()
        pending = _PendingClientToolRequest(
            request=request,
            future=loop.create_future(),
            loop=loop,
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
        async with self._lock:
            pending = self._pending.get(request_id)
        if pending is None:
            return ClientToolResultPayload(ok=False, error="客户端工具请求不存在。")
        try:
            return await asyncio.wait_for(pending.future, timeout=timeout_seconds)
        finally:
            async with self._lock:
                self._pending.pop(request_id, None)

    async def submit_result(
        self,
        request_id: str,
        result: ClientToolResultPayload,
    ) -> bool:
        normalized_request_id = request_id.strip()
        if not normalized_request_id:
            return False
        async with self._lock:
            pending = self._pending.get(normalized_request_id)
            if pending is None or pending.submitted or pending.future.done():
                return False
            pending.submitted = True
        pending.loop.call_soon_threadsafe(
            _set_result_if_pending,
            pending.future,
            result,
        )
        return True

    async def claim_request(self, request_id: str) -> bool:
        normalized_request_id = request_id.strip()
        if not normalized_request_id:
            return False
        async with self._lock:
            pending = self._pending.get(normalized_request_id)
            if (
                pending is None
                or pending.claimed
                or pending.submitted
                or pending.future.done()
            ):
                return False
            pending.claimed = True
            return True

    async def should_replay_request(self, request_id: str) -> bool:
        normalized_request_id = request_id.strip()
        if not normalized_request_id:
            return False
        async with self._lock:
            pending = self._pending.get(normalized_request_id)
            return bool(
                pending is not None
                and not pending.submitted
                and not pending.future.done()
            )

    async def pending_request_ids(
        self,
        *,
        project_id: str,
        session_id: str,
    ) -> tuple[str, ...]:
        """Return active requests owned by one conversation run.

        The bridge does not cancel the frontend action itself.  The run manager
        publishes these identities before it stops waiting, allowing the
        frontend execution coordinator to release its wait without pretending
        that an already-started side effect was rolled back.
        """
        async with self._lock:
            return tuple(
                request_id
                for request_id, pending in self._pending.items()
                if pending.request.project_id == project_id
                and pending.request.session_id == session_id
                and not pending.submitted
                and not pending.future.done()
            )


def _set_result_if_pending(
    future: asyncio.Future[ClientToolResultPayload],
    result: ClientToolResultPayload,
) -> None:
    if not future.done():
        future.set_result(result)


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
