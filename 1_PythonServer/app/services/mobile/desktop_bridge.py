"""Mobile input uses the desktop's ordinary request builder and client capabilities.

The desktop only prepares a request. Backend run ownership and persistence remain
with ConversationRunManager; a Telegram reconnect never restarts generation.
"""
from __future__ import annotations

import asyncio
import time
from uuid import uuid4

from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.schemas.llm.chat import ChatCompletionRequestBody
from app.services.project.conversation_run_manager import (
    ConversationStreamResyncRequiredError, get_conversation_run_manager,
)
from app.services.project.conversation_stream import get_project_conversation_stream_service
from app.services.project import get_project_conversation_service


class MobileDesktopBridge:
    def __init__(self, repository, on_result, is_authorized=None):
        self.repository = repository
        self.on_result = on_result
        self.is_authorized = is_authorized
        self.owner = None
        self.last_seen = 0.0
        self.changed = asyncio.Event()
        self.lock = asyncio.Lock()
        self.events: dict[str, dict] = {}
        self.notifications: dict[int, dict] = {}
        self.cursor = 0
        self.tasks: set[asyncio.Task] = set()
        self.run_ids: dict[str, str] = {}

    @property
    def online(self):
        # Transport presence, NOT a model/tool execution timeout.
        return self.owner is not None and time.monotonic() - self.last_seen < 60

    def notify(self, event):
        self.cursor += 1
        self.notifications[self.cursor] = event
        self.changed.set()

    async def poll(self, owner: str, after: int = 0):
        if self.owner != owner and self.online:
            await asyncio.sleep(20)
            return {"preparations": [], "events": [], "cursor": 0}
        if self.owner == owner:
            self.notifications = {i:e for i,e in self.notifications.items() if i > after}
        self.owner = owner
        self.last_seen = time.monotonic()
        self.changed.clear()
        jobs = await asyncio.to_thread(self.repository.list, "jobs")
        pending = [dict(job, id=key) for key, job in jobs if job["status"] == "preparing"]
        if not pending and not self.events and not self.notifications:
            try:
                await asyncio.wait_for(self.changed.wait(), 20)
            except TimeoutError:
                pass
            jobs = await asyncio.to_thread(self.repository.list, "jobs")
            pending = [dict(job, id=key) for key, job in jobs if job["status"] == "preparing"]
        if self.owner != owner:
            return {"preparations": [], "events": [], "cursor": 0}
        self.last_seen = time.monotonic()
        return {"preparations": pending, "events": [*self.events.values(), *self.notifications.values()], "cursor": self.cursor}

    def release(self, owner):
        if self.owner == owner:
            self.owner = None
            self.last_seen = 0
            self.changed.set()

    async def submit(self, peer: str, target: dict, text: str, references: list, content_parts=None, staging_key=None):
        if not self.online:
            raise BadRequestError("桌面会话入口尚未连接，请打开天策对话区后重发。本条消息未提交。")
        manager = get_conversation_run_manager()
        async with self.lock:
            if self.is_authorized and not await self.is_authorized(peer, target):
                raise BadRequestError("手机接入未启用或授权已撤销，本条消息未提交。")
            status = await manager.get_run_status(target["project_id"], target["session_id"])
            jobs = await asyncio.to_thread(self.repository.list, "jobs")
            if status["running"] or any(
                j["project_id"] == target["project_id"] and j["session_id"] == target["session_id"]
                for _, j in jobs
            ):
                raise ConflictError("目标会话正在运行，本条消息尚未提交。请等待完成或先暂停后重发。")
            key = uuid4().hex
            job = dict(target, peer=peer, text=text, content=text, content_parts=content_parts or [],
                       references=references, user_message_id=f"mobile_{key}", status="preparing")
            await asyncio.to_thread(self.repository.create_job, key, job, staging_key)
            self.changed.set()
            return key

    async def prepare(self, owner: str, key: str, payload: dict | None, error: str | None):
        async with self.lock:
            if owner != self.owner:
                raise ConflictError("该桌面连接不是当前执行入口。")
            job = await asyncio.to_thread(self.repository.get, "jobs", key)
            if not job or job["status"] != "preparing":
                return
            if self.is_authorized and not await self.is_authorized(job["peer"], job):
                await self.finish(key, job, "error", "手机接入未启用或授权已撤销，消息未提交。")
                return
            if error:
                await self.finish(key, job, "error", f"消息未提交：{error}")
                return
            try:
                body = ChatCompletionRequestBody.model_validate(payload)
                if (body.project_id != job["project_id"] or body.session_id != job["session_id"]
                        or len(body.messages) != 1 or body.messages[0].message_id != job["user_message_id"]):
                    raise BadRequestError("手机消息目标与桌面准备的请求不一致。")
                # Only configuration comes from the common desktop builder.
                payload = dict(payload, messages=[dict(role="user", message_id=job["user_message_id"],
                    content=job["content"], references=job["references"], content_parts=job.get("content_parts", []))])
                request = ChatCompletionRequestBody.model_validate(payload).to_domain()
                service = get_project_conversation_stream_service()
                await asyncio.to_thread(service.validate_conversation_target, request)
                job["status"] = "starting"
                await asyncio.to_thread(self.repository.put, "jobs", key, job)
                subscription = await get_conversation_run_manager().start(request, service)
            except Exception as exc:
                job["status"] = "preparing"  # start did not accept it; restore staged references.
                await self.finish(key, job, "error", f"消息未提交：{getattr(exc, 'message', str(exc))}")
                return
            job["status"] = "running"
            if getattr(subscription, "run_id", None):
                self.run_ids[key] = subscription.run_id
            # Once start succeeds, always attach a follower, even if persisting
            # another status would fail. The durable 'starting' record is enough.
            task = asyncio.create_task(self.follow(key, job, subscription), name=f"mobile-run:{key}")
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    async def follow(self, key, job, subscription):
        settlement = None
        last_error = None
        try:
            async for event in self.run_events(job, subscription):
                kind = event.get("kind")
                if kind == "conversation_run_settled":
                    settlement = event
                elif kind == "error":
                    last_error = event.get("error")
                elif kind == "client_tool_request":
                    request = event["client_tool_request"]
                    self.events[request["request_id"]] = dict(event, mobile_job_id=key)
                    self.changed.set()
                elif kind == "client_tool_request_cancelled":
                    self.events.pop(event.get("request_id"), None)
                    self.notify(event)
                elif kind == "tool_result":
                    call_id = (event.get("tool_result") or {}).get("call_id")
                    self.events = {k: e for k, e in self.events.items()
                                   if e["client_tool_request"]["call_id"] != call_id}
                elif kind == "tool_permission_request":
                    await self.on_result(job, "permission", event["tool_permission_request"])
            if not settlement:
                raise RuntimeError(last_error or "连接已结束，但尚未取得本次任务的结束记录，请在天策中查看。")
            status = settlement["status"]
            content = ""
            message_id = settlement.get("assistant_message_id")
            if message_id:
                message = await asyncio.to_thread(get_project_conversation_service().get_message,
                                                 job["project_id"], job["session_id"], message_id)
                if not message.tool_calls:
                    content = message.content
            if status == "cancelled":
                content = "已暂停。" + ("\n\n" + content if content else "")
            elif status == "error":
                content = (last_error or "本次任务失败，请在天策中查看请求记录。") + ("\n\n" + content if content else "")
            else:
                content = content or "本次任务已结束，未生成正式回复。"
            await self.finish(key, job, status, content)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.finish(key, job, "error", str(exc))
        finally:
            self.run_ids.pop(key, None)
            for request_id, event in self.events.items():
                if event["mobile_job_id"] == key:
                    self.notify({"kind":"client_tool_request_cancelled","request_id":request_id})
            self.events = {k: e for k, e in self.events.items() if e["mobile_job_id"] != key}

    async def run_events(self, job, subscription):
        """Resume observation only; never start generation again after mailbox overflow."""
        manager = get_conversation_run_manager()
        run_id = getattr(subscription, "run_id", None)
        while True:
            try:
                async for event in manager.stream(subscription):
                    yield event
                return
            except ConversationStreamResyncRequiredError:
                if not run_id:
                    raise
                try:
                    subscription = await manager.subscribe(job["project_id"], job["session_id"], expected_run_id=run_id)
                except NotFoundError:
                    # The original run may have settled while the listener was
                    # reconnecting. Read that user's durable turn, never a newer run.
                    turn = await asyncio.to_thread(get_project_conversation_service().get_message_turn,
                                                  job["project_id"], job["session_id"], job["user_message_id"])
                    outcome = turn.run_outcomes[-1] if turn.run_outcomes else None
                    if not outcome or outcome.status == "running":
                        raise RuntimeError("原任务连接已结束，但没有结算记录，请在天策中查看。") from None
                    if outcome.error_message:
                        yield {"kind":"error", "error":outcome.error_message}
                    last = next((m for m in reversed(turn.items) if m.role == "assistant"), None)
                    yield {"kind":"conversation_run_settled", "status":outcome.status,
                           "assistant_message_id": last.message_id if last and not last.tool_calls else None}
                    return

    async def finish(self, key, job, status, text):
        # on_result durably records outbound delivery before releasing this job.
        await self.on_result(job, status, text)
        await asyncio.to_thread(self.repository.delete, "jobs", key)

    async def stop(self, target, expected_user_id=None):
        async with self.lock:
            jobs = await asyncio.to_thread(self.repository.list, "jobs")
            matches = [(k,j) for k,j in jobs if all(j[f] == target[f] for f in ("project_id", "session_id"))]
            if expected_user_id and not any(j["user_message_id"] == expected_user_id for _,j in matches):
                return False
            for key, job in matches:
                if job["status"] == "preparing":
                    await self.finish(key, job, "cancelled", "已取消待提交消息。")
                    return True
            if expected_user_id:
                run_id = next((self.run_ids.get(key) for key, job in matches if job["user_message_id"] == expected_user_id), None)
            else:
                status = await get_conversation_run_manager().get_run_status(target["project_id"], target["session_id"])
                run_id = status.get("run_id")
        # Cancellation may wait for tools and persistence. Do not hold the
        # mobile-wide preparation lock while another conversation is stopping.
        if not run_id:
            return False
        return await get_conversation_run_manager().stop(target["project_id"], target["session_id"], expected_run_id=run_id)

    async def recover(self):
        # Never replay input after an unclean process stop; report the durable outcome.
        for key, job in await asyncio.to_thread(self.repository.list, "jobs"):
            message = "天策已重启，上次任务未自动重发。请检查会话记录后继续。"
            try:
                turn = await asyncio.to_thread(get_project_conversation_service().get_message_turn,
                                              job["project_id"], job["session_id"], job["user_message_id"])
                if turn.run_outcomes and turn.run_outcomes[-1].status == "done":
                    last = next((m for m in reversed(turn.items) if m.role == "assistant"), None)
                    message = last.content if last and not last.tool_calls and last.content else "本次任务已结束，未生成正式回复。"
            except Exception:
                pass
            await self.finish(key, job, "recovered", message)
