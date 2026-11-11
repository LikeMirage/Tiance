"""Shared private-message runtime: authorization, intake, staging, jobs and delivery."""
from __future__ import annotations

import asyncio
import mimetypes
import json
import time
from pathlib import Path
from contextlib import suppress
from functools import lru_cache
from uuid import uuid4

from app.core.config import get_settings
from app.core.errors import BadRequestError
from app.infra.secrets import decrypt_secret
from app.repositories.mobile_repository import MobileRepository
from .context import resolve_target, target_header, incoming_path, file_reference
from .desktop_bridge import MobileDesktopBridge
from .navigation import MobileNavigation
from .telegram_transport import TelegramTransport, TelegramError, safe_filename, split_message
from .activity import record_activity
from .access_scope import MobileAccessScope, reply_collections, SCOPE_CHANGED


class MobileService:
    platform = 'telegram'
    label = 'Telegram'

    def __init__(self, repository, *, desktop=None):
        self.repository = repository
        self.desktop = desktop or MobileDesktopBridge(repository, self.result, self.is_authorized)
        self.navigation = MobileNavigation(self)
        self.access_scope = MobileAccessScope(self)
        if self.platform == 'telegram':
            from .telegram_navigation import TelegramNavigation
            self.navigation = TelegramNavigation(self)
        self.transport = None
        self.config = {}
        self.error = None
        self.tasks = []
        self.work: set[asyncio.Task] = set()
        self.downloads: dict[str, list[asyncio.Task]] = {}
        self.submissions: set[str] = set()
        self.staging_generations: dict[str, int] = {}
        self.file_lock = asyncio.Lock()
        self.wakeup = asyncio.Event()
        self.outgoing = asyncio.Event()

    async def get(self, *args):
        return await asyncio.to_thread(self.repository.get, *args)

    async def put(self, *args):
        return await asyncio.to_thread(self.repository.put, *args)

    async def delete(self, *args):
        return await asyncio.to_thread(self.repository.delete, *args)

    async def records(self, namespace):
        return await asyncio.to_thread(self.repository.list, namespace)

    async def activity(self, event, **details):
        await record_activity(self.repository, event, **details)

    async def is_authorized(self, peer, target=None):
        identity = await self.get("peers", peer, {})
        return bool(self.config.get("enabled") and identity.get("allowed")
                    and identity.get("bot_id") == self.config.get("bot", {}).get("id")
                    and await self.access_scope.allows_target(target))

    async def status(self):
        config = self.config
        peers = [dict(p, id=k) for k,p in await self.records("peers") if p["bot_id"] == config.get("bot",{}).get("id")]
        return {"connection_id": self.repository.connection_id, "enabled": config.get("enabled",False), "has_token": bool(config.get("token")),
                "api_base": config.get("api_base","https://api.telegram.org"), "bot":config.get("bot"),
                "error":self.error,"desktop_online":self.desktop.online,"peers":peers,
                "pending_deliveries":len(await self.records("outbox")),
                "allowed_collections": self.access_scope.collections()}

    async def apply_config(self, config):
        self.config = config
        try:
            self.transport = self.make_transport(config) if config.get('enabled') else None
            self.error = None
        except Exception:
            self.transport = None
            self.error = f'无法读取{self.label}凭据，请重新配置。'
        if self.tasks:
            self.tasks[0].cancel()
            with suppress(asyncio.CancelledError):
                await self.tasks[0]
            self.tasks[0] = asyncio.create_task(self.receive_loop(), name=f'{self.platform}-receive')
        self.wakeup.set()
        self.outgoing.set()

    def make_transport(self, config):
        return TelegramTransport(decrypt_secret(config['token']), config['api_base'])

    @property
    def channel(self):
        return self.repository.connection_id or f"{self.platform}:{self.config['bot']['id']}"

    async def authorize(self, peer, allowed):
        record = await self.get("peers", peer)
        if not record:
            raise BadRequestError("该接入用户不存在。")
        async with self.desktop.lock:
            await self.put("peers", peer, dict(record, allowed=allowed, reviewed=True))
            if not allowed:
                for key, job in await self.records("jobs"):
                    if job["peer"] == peer and job["status"] == "preparing":
                        await self.desktop.finish(key, job, "error", "授权已撤销，消息未提交。")
        if allowed:
            await self.reply(peer, "已允许访问天策。请选择项目和会话。")
        await self.activity('authorized' if allowed else 'revoked', user_id=record.get('user_id'), chat_id=record.get('chat_id'))
        return await self.status()

    async def start(self):
        await asyncio.to_thread(self.repository.discard_unowned_empty_staging)
        # A crash between accepting an action and committing its side effect is
        # not permission to execute it again. Preserve it for explicit resubmission.
        for key, record in await self.records("inbox"):
            if record.get("processing"):
                if record.get("peer"):
                    await self.reply(record["peer"], "天策在处理上一条手机消息时重启，该消息未自动重发，请检查会话后重发。")
                await self.delete("inbox", key)
        self.tasks = [asyncio.create_task(self.receive_loop(), name=f"{self.platform}-receive"),
                      asyncio.create_task(self.dispatch_loop(), name="mobile-dispatch"),
                      asyncio.create_task(self.delivery_loop(), name=f"{self.platform}-delivery"),
                      asyncio.create_task(self.presence_loop(), name="mobile-presence")]

    async def close(self):
        for task in self.tasks + list(self.work):
            task.cancel()
        await asyncio.gather(*self.tasks, *self.work, return_exceptions=True)
        self.tasks = []

    async def drain_runs(self):
        if self.desktop.tasks:
            await asyncio.gather(*self.desktop.tasks, return_exceptions=True)

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.work.add(task)
        def finished(task):
            self.work.discard(task)
            if not task.cancelled() and task.exception():
                self.error = "手机消息处理未完成，请检查会话后重发。"
        task.add_done_callback(finished)
        return task

    async def clear_staging(self, peer, target):
        key = self.staging_key(peer, target)
        async with self.file_lock:
            self.staging_generations[key] = self.staging_generations.get(key, 0) + 1
            await self.delete("staged", key)
            self.downloads.pop(key, None)

    def track_download(self, key, task):
        self.downloads.setdefault(key, []).append(task)

        def finished(completed):
            pending = self.downloads.get(key, [])
            if completed in pending:
                pending.remove(completed)
            if not pending:
                self.downloads.pop(key, None)

        # Only in-flight files can delay a later instruction. A failed file is
        # reported by download(); it must not poison subsequent text messages.
        task.add_done_callback(finished)

    async def presence_loop(self):
        while True:
            await asyncio.sleep(20)
            if not self.desktop.online:
                async with self.desktop.lock:
                    for key, job in await self.records("jobs"):
                        if job["status"] == "preparing":
                            await self.desktop.finish(key, job, "error", "桌面连接已断开，消息未提交。请恢复天策窗口后重发。")

    @staticmethod
    def staging_key(peer, target):
        return f"{peer}:{target['project_id']}:{target['session_id']}"

    async def receive_loop(self):
        delay = 1
        failed = False
        while True:
            transport = self.transport
            if not transport:
                await asyncio.sleep(20)
                continue
            channel = self.channel
            try:
                if self.platform != 'telegram':
                    async for event in transport.events(self.repository):
                        if event is not None:
                            await asyncio.to_thread(self.repository.receive, channel, str(event['id']),
                                                    {'channel': channel, 'event': event})
                            self.wakeup.set()
                        self.error = None
                        if failed:
                            await self.activity('receive_recovered')
                        failed = False
                        delay = 1
                    continue
                offset = await self.get("offsets", channel, 0)
                updates = await transport.call("getUpdates", {"offset":offset,"timeout":30,
                                                "allowed_updates":["message","callback_query"]}, poll=True)
                for update in updates:
                    await asyncio.to_thread(self.repository.receive, channel, str(update["update_id"]),
                                            {"channel":channel,"update":update})
                    await self.put("offsets", channel, update["update_id"]+1)
                self.error = None
                if failed:
                    await self.activity('receive_recovered')
                failed = False
                delay = 1
                if updates:
                    self.wakeup.set()
            except Exception as exc:
                self.error = str(exc) if isinstance(exc, (TelegramError, BadRequestError)) else f"{self.label}接收失败（{type(exc).__name__}），将重新连接。"
                if not failed:
                    await self.activity('receive_failed', level='error', error=exc)
                failed = True
                await asyncio.sleep(max(delay, getattr(exc,"retry_after",0)))
                delay = min(delay*2, 30)

    async def dispatch_loop(self):
        while True:
            self.wakeup.clear()
            for key, record in await self.records("inbox"):
                if record.get("processing"):
                    continue
                if not self.transport or record["channel"] != self.channel:
                    continue
                deferred = False
                completed = False
                try:
                    deferred = await self.dispatch(key, record)
                    completed = True
                except Exception:
                    # dispatch records a user-facing error when an identity is available.
                    self.error = f"一条{self.label}消息处理失败，请检查会话或重新发送。"
                    completed = True
                finally:
                    if completed and not deferred:
                        await self.delete("inbox", key)
            try:
                await asyncio.wait_for(self.wakeup.wait(), 30)
            except TimeoutError:
                pass

    async def dispatch(self, key, record):
        from .inbound import telegram_event
        event = record.get('event') or telegram_event(record['update'])
        if event is None:
            return
        callback = event.get('callback')
        peer = f"{record['channel']}:{event['chat_id']}:{event['user_id']}"
        await self.put("inbox", key, dict(record, peer=peer, processing=True))
        await self.activity('callback_received' if callback else 'message_received',
                            user_id=event['user_id'], chat_id=event['chat_id'], update_id=event['id'])
        identity = await self.get("peers", peer)
        if identity is None:
            await self.put("peers", peer, {"connection_id":record["channel"], "platform":self.platform, "bot_id":self.config["bot"]["id"],"chat_id":event['chat_id'],
                           "user_id":event['user_id'],"name":event.get('name') or str(event['user_id']),
                           "username":event.get('username'),"allowed":False,"reviewed":False})
            # One generic notice, containing no workspace information.
            if event.get('context'):
                await self.put('reply_context', peer, event['context'])
            await self.reply(peer, f"请在电脑端天策的{self.label}设置中允许此账号访问。", rows=[], public=True)
            return
        if event.get('context'):
            await self.put('reply_context', peer, event['context'])
        if event.get('callback_id') and self.platform == 'telegram':
            self.spawn(self.answer_callback(event['callback_id']))
        if not identity.get("allowed"):
            return
        target = await self.get("selection", peer)
        try:
            if callback:
                data = await self.get("callbacks", callback)
                if not data or data["peer"] != peer:
                    raise BadRequestError("按钮已不可用，请发送 /start 重新打开。")
                await self.navigation.action(peer, **{k:v for k,v in data.items() if k != "peer"})
                return
            text = event.get('text', '')
            if hasattr(self.navigation, 'consume') and await self.navigation.consume(peer, text, event):
                return
            if text.startswith("/"):
                cmd, _, argument = text.partition(" ")
                cmd = cmd.split("@")[0][1:]
                aliases = {"projects":"collections","start":"help"}
                await self.navigation.action(peer, aliases.get(cmd,cmd), title=argument.strip() or None)
                return
            target = await self.navigation.message_target(peer, {'reply_to_message': {'message_id': event['reply_id']}} if event.get('reply_id') else {})
            await asyncio.to_thread(resolve_target, target)
            media = event.get('media', [])
            if not media and not text:
                raise BadRequestError(f"暂不支持这种{self.label}消息。本条未提交，不影响后续消息；请发送文字或文件。")
            staging = self.staging_key(peer, target)
            if media:
                transport = self.transport
                tasks = []
                for attachment in media:
                    task = self.spawn(self.download(peer, target, attachment, transport, self.staging_generations.get(staging, 0)))
                    self.track_download(staging, task)
                    tasks.append(task)
                task = asyncio.gather(*tasks)
                if event.get('album'):
                    await self.reply(peer, "相册正在收件，请等文件保存后另发一条处理要求，以免漏掉同组图片。", target)
                    self.spawn(self.finish_intake(key, task))
                    return True
            if text:
                if staging in self.submissions:
                    raise BadRequestError("当前会话已有手机消息正在准备，本条消息未提交，请稍后重发。")
                self.submissions.add(staging)
                pending = [task for task in self.downloads.get(staging, []) if not task.done()]
                self.spawn(self.finish_intake(key, self.submit(peer, target, text, pending)))
                return True
            elif media:
                self.spawn(self.finish_intake(key, task))
                return True
        except Exception as exc:
            await self.activity('dispatch_failed', level='error', error=exc, user_id=event['user_id'], chat_id=event['chat_id'])
            await self.reply(peer, getattr(exc,"message",str(exc)), target)

    async def finish_intake(self, key, work):
        # Leave the processing receipt on cancellation/crash. Startup reports it,
        # rather than losing an accepted phone message or submitting it twice.
        await work
        await self.delete("inbox", key)

    async def answer_callback(self, callback_id):
        with suppress(TelegramError):
            if self.transport:
                await self.transport.call("answerCallbackQuery", {"callback_query_id":callback_id})

    async def download(self, peer, target, media, transport, generation=0):
        try:
            await self.access_scope.require_target(target)
            name = safe_filename(media.get("file_name") or f"recording_{uuid4().hex}.ogg")
            path, relative = await asyncio.to_thread(incoming_path, target, name, self.label)
            await transport.download(media["file_id"] if self.platform == 'telegram' else media, path)
            await self.access_scope.require_target(target)
            ref = file_reference(target, relative, name)
            key = self.staging_key(peer, target)
            async with self.file_lock:
                if self.staging_generations.get(key, 0) != generation:
                    await self.reply(peer, f"已保存：{relative}\n待发送引用已被清除，本文件未提交。", target)
                    return False
                await asyncio.to_thread(self.repository.append_staged, key, [ref])
            await self.reply(peer, f"已保存：{relative}\n等待你的处理要求。", target)
            await self.activity('file_saved', **target)
            return True
        except Exception as exc:
            await self.activity('file_failed', level='error', error=exc, **target)
            await self.reply(peer, f"文件接收失败：{getattr(exc,'message',str(exc))}", target)
            return False

    async def submit(self, peer, target, text, downloads):
        key = self.staging_key(peer, target)
        try:
            if downloads and not all(await asyncio.gather(*downloads)):
                raise BadRequestError("部分文件接收失败，本条要求未提交。需要这些文件时请补发；也可以直接发送新的文字要求。")
            identity = await self.get("peers", peer, {})
            if not identity.get("allowed"):
                return
            await self.access_scope.require_target(target)
            await asyncio.to_thread(resolve_target, target)
            async with self.file_lock:
                refs = await self.get("staged", key, [])
                project, _ = await asyncio.to_thread(resolve_target, target)
                from pathlib import Path
                from .source import append_message_source
                text = append_message_source(text, platform=self.label, connection_id=self.channel,
                                             user_id=identity['user_id'], chat_id=identity['chat_id'])
                parts = [{"type":"text", "text":text}]
                for item in refs:
                    ref = item["reference"]
                    mime = mimetypes.guess_type(ref["fileName"])[0]
                    if mime in {"image/jpeg","image/png","image/webp","image/gif"}:
                        parts.append({"type":"image_ref","image_ref":{
                            "path":str(Path(project.root_path)/ref["filePath"]),"name":ref["fileName"],"mime_type":mime}})
                job_id = await self.desktop.submit(peer, target, text, refs, parts if len(parts)>1 else [], key)
            await self.activity('task_submitted', job_id=job_id, user_id=identity['user_id'], chat_id=identity['chat_id'], **target)
            await self.reply(peer, "已接收，正在提交到会话。", target, user_message_id=f"mobile_{job_id}")
        except Exception as exc:
            await self.activity('submit_failed', level='error', error=exc, **target)
            await self.reply(peer, getattr(exc,"message",str(exc)), target)
        finally:
            self.submissions.discard(key)
            current = self.downloads.get(key, [])
            self.downloads[key] = [t for t in current if t not in downloads]
            if not self.downloads[key]:
                self.downloads.pop(key, None)

    async def result(self, job, status, content):
        target = {k:job[k] for k in ("project_id","session_id")}
        if status == "permission":
            rows = [[await self.navigation.button(job["peer"], "允许本次", "permission", target=target,
                      request_id=content["request_id"], decision="allow"),
                     await self.navigation.button(job["peer"], "拒绝", "permission", target=target,
                      request_id=content["request_id"], decision="deny")]]
            await self.reply(job["peer"], "工具请求权限：\n" + str(content.get("tool_name",content.get("name",""))) +
                             "\n" + "\n".join(f"{f['permission_type']}：{f['scope']}" for f in content.get("facts",[])), target, rows,
                             delivery_key=job["user_message_id"]+":permission:"+content["request_id"])
        else:
            if job["status"] == "preparing" and job.get("references"):
                key = self.staging_key(job["peer"], target)
                await asyncio.to_thread(self.repository.append_staged, key, job["references"])
            await self.reply(job["peer"], str(content), target, delivery_key=job["user_message_id"]+":result")
            event = {'completed': 'task_completed', 'error': 'task_failed', 'cancelled': 'task_cancelled'}.get(status, 'task_finished')
            await self.activity(event, level='error' if status == 'error' else 'info', **target)

    async def reply(self, peer, text, target=None, rows=None, public=False, user_message_id=None, delivery_key=None):
        if target is None and not public:
            target = await self.get("selection", peer)
        if not public and not await self.access_scope.allows_target(target):
            target, text, rows = None, SCOPE_CHANGED, []
        header = "天策" if public else await asyncio.to_thread(target_header, target)
        if rows is None:
            rows = await self.navigation.controls(peer, target, user_message_id)
        if hasattr(self.navigation, 'prepare_reply') and not public:
            text, rows = await self.navigation.prepare_reply(peer, text, rows)
        record = {"peer":peer,"target":target,"parts":list(split_message(str(text) or "（空回复）")),
                  "header":header,"rows":rows,"sent":0,"next_attempt":0,"attempts":0,"public":public}
        record['access_collections'] = list(reply_collections.get())
        key = delivery_key or uuid4().hex
        if not await self.get("outbox", key) and not await self.get("delivered", key):
            await self.put("outbox", key, record)
            self.outgoing.set()

    async def delivery_loop(self):
        while True:
            self.outgoing.clear()
            wait = 30
            transport = self.transport
            if transport:
                for key, item in await self.records("outbox"):
                    peer = await self.get("peers", item["peer"], {})
                    if peer.get("bot_id") != self.config["bot"]["id"]:
                        continue
                    if item["next_attempt"] > time.time():
                        wait = min(wait,max(.1,item["next_attempt"]-time.time()))
                        continue
                    if not peer.get("allowed") and not item.get("public"):
                        continue
                    try:
                        if not await self.access_scope.allows_delivery(item):
                            if item.get('diagram'):
                                from .relationship_diagram import remove_diagram
                                with suppress(OSError):
                                    await asyncio.to_thread(remove_diagram, item['diagram'])
                            await self.put('delivered', key, True)
                            await self.delete('outbox', key)
                            continue
                        index = item["sent"]
                        if index < len(item["parts"]):
                            text = next(split_message(item["header"], 400))+"\n\n"+item["parts"][index]
                            if self.platform != 'telegram':
                                card_options = {}
                                if self.platform == 'feishu':
                                    text = item['parts'][index]
                                    card_options['header'] = next(split_message(item['header'], 400))
                                result = await transport.deliver(peer, text, item['rows'],
                                    context=await self.get('reply_context', item['peer'], {}),
                                    document=Path(item['diagram']) if item.get('diagram') else None,
                                    delivery_id=f'{key}:{index}', **card_options)
                            elif item.get('diagram'):
                                result = await transport.send_once('sendDocument', {
                                    'chat_id': str(peer['chat_id']), 'caption': text,
                                    'reply_markup': json.dumps({'inline_keyboard': item['rows']}, ensure_ascii=False),
                                }, document=Path(item['diagram']))
                            else:
                                result = await transport.call("sendMessage", {"chat_id":peer["chat_id"],
                                    "text": text, "reply_markup":{"inline_keyboard":item["rows"]},
                                    "link_preview_options":{"is_disabled":True}})
                            item["sent"] += 1
                            item["attempts"] = 0
                            await asyncio.to_thread(self.repository.delivery_progress, key, item, result['message_id'])
                            wait = min(wait,1)
                        if item["sent"] == len(item["parts"]):
                            if item.get('diagram'):
                                from .relationship_diagram import remove_diagram
                                with suppress(OSError):
                                    await asyncio.to_thread(remove_diagram, item['diagram'])
                            await self.put("delivered", key, True)
                            await self.delete("outbox", key)
                            await self.activity('reply_sent', user_id=peer.get('user_id'), chat_id=peer.get('chat_id'))
                    except Exception as exc:
                        item["attempts"] += 1
                        if item['attempts'] == 1:
                            await self.activity('reply_failed', level='error', error=exc, user_id=peer.get('user_id'), chat_id=peer.get('chat_id'))
                        item["next_attempt"] = time.time()+max(getattr(exc,"retry_after",0), min(60,2**min(item["attempts"],6)))
                        await self.put("outbox", key, item)
                        self.error = str(exc) if isinstance(exc,TelegramError) else "结果回传失败，已保留并等待重试。"
                        wait = min(wait,max(.1,item["next_attempt"]-time.time()))
            try:
                await asyncio.wait_for(self.outgoing.wait(),wait)
            except TimeoutError:
                pass

    async def reply_diagram(self, peer, path, title, rows):
        # Send as an original PNG file so Telegram does not blur small labels.
        record = {
            'peer': peer, 'target': None, 'header': title,
            'parts': ['分类 → 项目 → 主会话。打开原图可放大查看。'],
            'rows': rows, 'diagram': str(path), 'sent': 0,
            'next_attempt': 0, 'attempts': 0, 'public': False,
        }
        record['access_collections'] = list(reply_collections.get())
        await self.put('outbox', uuid4().hex, record)
        self.outgoing.set()


class FeishuService(MobileService):
    platform, label = 'feishu', '飞书'

    def __init__(self, repository, *, desktop=None):
        super().__init__(repository, desktop=desktop)
        from .feishu_navigation import FeishuNavigation
        self.navigation = FeishuNavigation(self)

    def make_transport(self, config):
        from .feishu_transport import FeishuTransport
        return FeishuTransport(config['app_id'], decrypt_secret(config['token']))


class WeChatService(MobileService):
    platform, label = 'wechat', '微信'

    def __init__(self, repository, *, desktop=None):
        super().__init__(repository, desktop=desktop)
        from .wechat_navigation import WeChatNavigation
        self.navigation = WeChatNavigation(self)

    def make_transport(self, config):
        from .wechat_transport import WeChatTransport
        return WeChatTransport(decrypt_secret(config['token']), config['api_base'])


@lru_cache(maxsize=1)
def get_mobile_service():
    from .manager import MobileAccessService
    return MobileAccessService(MobileRepository(get_settings().app_database_file))
