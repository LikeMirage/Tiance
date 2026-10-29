from __future__ import annotations

from http.client import HTTPException
import json
from time import monotonic, sleep
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class BridgeError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class ConversationRun:
    """Follow one submitted message and its backend-authorized continuations.

    A closed transport is not a successful run. Only a matching settlement or
    durable run outcome can finish the request; an intermediate assistant/tool
    message with status=done cannot. Recovery never sends another POST.
    """

    def __init__(self, base_url: str, project_id: str, session_id: str,
                 user_message_id: str, query: Callable[..., dict], timeout: float) -> None:
        self.base_url = base_url
        self.project_id = project_id
        self.session_id = session_id
        self.original_user_id = user_message_id
        self.user_id = user_message_id
        self.authorized_users = {user_message_id}
        self.query = query
        self.deadline = monotonic() + timeout
        self.settlement: dict | None = None
        self.stream_error: str | None = None
        self.path = f"/projects/{quote(project_id, safe='')}/conversations/{quote(session_id, safe='')}"
        self.run_query = urlencode({"project_id": project_id, "session_id": session_id})

    def details(self) -> dict:
        return {"project_id": self.project_id, "session_id": self.session_id,
                "user_message_id": self.original_user_id, "reply_user_message_id": self.user_id}

    def remaining(self) -> float:
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise BridgeError("SESSION_RUN_UNCONFIRMED", "等待已超时，无法确认本次会话的最终结果；目标任务可能仍在运行。", self.details())
        return remaining

    def get(self, path: str) -> dict:
        return self.query("GET", path, timeout=min(30, self.remaining()))

    def advance(self, message: dict) -> None:
        message_id = message.get("message_id")
        if not isinstance(message_id, str) or not message_id:
            self.mismatch("自动续接消息缺少标识。")
        if message_id in self.authorized_users:
            return  # Replayed events must not move the request back to an older turn.
        if (message.get("role") != "user" or message.get("message_source") != "output_limit"
                or message.get("continuation_of") != self.user_id):
            self.mismatch("自动续接消息不属于本次请求。")
        self.authorized_users.add(message_id)
        self.user_id = message_id
        self.settlement = None
        self.stream_error = None

    def mismatch(self, message: str) -> None:
        raise BridgeError("SESSION_RUN_MISMATCH", message, self.details())

    def handle_event(self, event: dict) -> None:
        kind = event.get("kind")
        if kind == "conversation_run_started":
            if event.get("user_message_id") not in self.authorized_users:
                # Replay may start at a newer durable checkpoint and omit the
                # output_limit event. Verify the continuation chain in storage.
                self.read_turn()
            if event.get("user_message_id") not in self.authorized_users:
                self.mismatch("连接到了另一轮会话运行。")
        elif kind == "output_limit" and event.get("will_recover") and event.get("action") == "send_message":
            message = event.get("next_user_message")
            if not isinstance(message, dict):
                self.mismatch("自动续接通知缺少消息。")
            self.advance(message)
        elif kind == "conversation_run_settled":
            user_id = event.get("user_message_id")
            if user_id in self.authorized_users and user_id != self.user_id:
                return  # The truncated parent turn is not the end of the chain.
            if user_id != self.user_id or event.get("status") not in {"done", "error", "cancelled"}:
                self.mismatch("会话结束通知与本次请求不一致。")
            self.settlement = event
        elif kind == "error":
            self.stream_error = str(event.get("error") or "目标会话生成失败。")
        # delta/done describe model output, not durable completion of this run.

    def consume(self, request: Request) -> None:
        data_lines: list[str] = []

        def dispatch() -> None:
            if not data_lines:
                return
            raw = "\n".join(data_lines)
            data_lines.clear()
            if raw == "[DONE]":
                return
            try:
                event = json.loads(raw)
            except ValueError as exc:
                raise BridgeError("BACKEND_INVALID_STREAM", "会话流包含无效事件。", self.details()) from exc
            if not isinstance(event, dict):
                raise BridgeError("BACKEND_INVALID_STREAM", "会话流事件不是对象。", self.details())
            self.handle_event(event)

        # Bounded idle reads allow the overall waiting deadline to be enforced.
        with urlopen(request, timeout=min(30, self.remaining())) as response:
            for raw_line in response:
                self.remaining()
                line = raw_line.decode("utf-8").rstrip("\r\n")
                if not line:
                    dispatch()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip(" "))
            dispatch()

    def read_turn(self) -> dict | None:
        while True:
            try:
                turn = self.get(f"{self.path}/messages/{quote(self.user_id, safe='')}/turn")
            except BridgeError as exc:
                if exc.details.get("http_status") == 404:
                    return None
                raise
            items = turn.get("items")
            if (turn.get("project_id") != self.project_id or turn.get("session_id") != self.session_id
                    or turn.get("user_message_id") != self.user_id or not isinstance(items, list)
                    or not items or not all(isinstance(item, dict) for item in items)
                    or items[0].get("role") != "user" or items[0].get("message_id") != self.user_id):
                self.mismatch("读取到的持久化轮次不属于本次请求。")
            outcomes = self.outcomes(turn)
            reply = self.reply(turn)
            truncated = ((reply or {}).get("finish_reason") == "output_limit"
                         or any(item.get("error_code") == "upstream_output_limit" for item in outcomes))
            if not truncated:
                return turn
            # The next user is excluded by /turn. Read just its following row,
            # rather than loading all session history, to recover a lost notice.
            last_id = items[-1].get("message_id")
            if not isinstance(last_id, str) or not last_id:
                self.mismatch("持久化消息缺少标识。")
            page = self.get(f"{self.path}/messages?{urlencode({'after_message_id': last_id, 'limit': 1})}")
            if page.get("project_id") != self.project_id or page.get("session_id") != self.session_id:
                self.mismatch("续接消息查询返回了其他会话。")
            following = page.get("items")
            next_user = following[0] if isinstance(following, list) and following else None
            if not (isinstance(next_user, dict) and next_user.get("role") == "user"
                    and next_user.get("message_source") == "output_limit"
                    and next_user.get("continuation_of") == self.user_id):
                return turn
            if next_user.get("message_id") in self.authorized_users:
                self.mismatch("自动续接消息形成循环。")
            self.advance(next_user)

    def outcomes(self, turn: dict) -> list[dict]:
        outcomes = turn.get("run_outcomes", [])
        if not isinstance(outcomes, list):
            self.mismatch("持久化运行状态格式无效。")
        matching = [item for item in outcomes if isinstance(item, dict)
                    and item.get("user_message_id") == self.user_id
                    and item.get("session_id") == self.session_id]
        if outcomes and not matching:
            self.mismatch("持久化运行记录不属于本次用户消息。")
        return sorted(matching, key=lambda item: str(item.get("started_at") or ""))

    @staticmethod
    def reply(turn: dict) -> dict | None:
        return next((item for item in reversed(turn["items"])
                     if item.get("role") in {"assistant", "error"}), None)

    def result(self, turn: dict | None) -> dict | None:
        if turn is None:
            return None
        outcomes = self.outcomes(turn)
        outcome = outcomes[-1] if outcomes else None
        status = outcome.get("status") if outcome else None
        if status == "running":
            return None
        if status is not None and status not in {"done", "error", "cancelled"}:
            self.mismatch("持久化运行状态无效。")
        reply = self.reply(turn)
        if self.settlement:
            if self.settlement.get("assistant_message_id") != (reply or {}).get("message_id"):
                self.mismatch("结束通知与持久化回复标识不一致。")
            if status and status != self.settlement["status"]:
                self.mismatch("结束通知与持久化运行状态不一致。")
            status = self.settlement["status"]
        if status is None:
            return None
        if status == "done" and (not reply or reply.get("status") != "done"
                                 or reply.get("role") == "error" or reply.get("tool_calls")
                                 or reply.get("finish_reason") == "output_limit"):
            self.mismatch("已结束的运行缺少完整的最终回复。")
        data = {**self.details(), "assistant_message_id": (reply or {}).get("message_id"),
                "outcome": status, "finish_reason": (reply or {}).get("finish_reason"),
                "reply": (reply or {}).get("content") or ""}
        if status == "error" or self.stream_error:
            raise BridgeError("SESSION_RUN_ERROR", self.stream_error
                              or (outcome or {}).get("error_message") or data["reply"] or "目标会话生成失败。", data)
        return data

    def wait(self, body: dict) -> dict:
        initial = Request(self.base_url + "/llm/chat/completions/stream",
                          data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
                          headers={"Accept": "text/event-stream", "Content-Type": "application/json"})
        try:
            self.consume(initial)
        except HTTPError as exc:
            if exc.code < 500:
                raise BridgeError("BACKEND_HTTP_ERROR", f"Tiance 会话接口返回 HTTP {exc.code}。",
                                  {**self.details(), "http_status": exc.code}) from exc
        except (OSError, HTTPException):
            pass  # The POST may already have been accepted. Never resend it.

        active_missing = False
        retry_delay = 0.1
        while True:
            self.remaining()
            try:
                result = self.result(self.read_turn())
                if result is not None:
                    try:
                        state = self.get(f"/llm/chat/completions/stream/status?{self.run_query}")
                        result["runtime_status"] = (
                            "running" if state.get("running") is True
                            else "idle" if state.get("running") is False else None
                        )
                    except (BridgeError, OSError, HTTPException):
                        result["runtime_status"] = None
                    return result
                if self.stream_error:
                    raise BridgeError("SESSION_RUN_ERROR", self.stream_error, self.details())
                state = self.get(f"/llm/chat/completions/stream/status?{self.run_query}")
                if active_missing or state.get("running") is not True:
                    # The run can settle between the turn read and status read.
                    result = self.result(self.read_turn())
                    if result is not None:
                        result["runtime_status"] = (
                            "running" if state.get("running") is True
                            else "idle" if state.get("running") is False else None
                        )
                        return result
                    raise BridgeError("SESSION_RUN_UNCONFIRMED", "会话连接已结束，但本次回复没有可确认的最终状态。", self.details())
                resume = Request(self.base_url + f"/llm/chat/completions/stream/active?{self.run_query}",
                                 headers={"Accept": "text/event-stream"})
                try:
                    self.consume(resume)
                except HTTPError as exc:
                    if exc.code == 404:
                        active_missing = True  # Re-read storage after this finish race.
                    elif exc.code < 500 and exc.code != 409:
                        raise BridgeError("BACKEND_HTTP_ERROR", f"续接会话返回 HTTP {exc.code}。", self.details()) from exc
            except BridgeError as exc:
                if not (exc.code == "BACKEND_UNREACHABLE" or
                        (exc.code == "BACKEND_HTTP_ERROR" and exc.details.get("http_status", 0) >= 500)):
                    raise
            except (OSError, HTTPException):
                pass
            sleep(min(retry_delay, self.remaining()))
            retry_delay = min(2, retry_delay * 2)
