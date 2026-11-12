"""Shared navigation actions and platform-neutral button descriptions; ordinary conversation operations live below it."""
import asyncio
from uuid import uuid4

from app.core.errors import BadRequestError
from app.services.tools.tool_permission_bridge import get_tool_permission_bridge_service
from .context import COLLECTIONS, resolve_target, new_conversation
from .catalog_navigation import CatalogNavigation, CATALOG_ACTIONS
from .menu_state import MenuState, route_origin
from .menu_pages import MenuPages, PAGE_ACTIONS


COMMANDS = [("projects", "打开集与项目菜单"), ("sessions", "当前项目的主会话"), ("new", "新建主会话，可附标题"),
            ("actions", "会话操作"),
            ("newcategory", "在当前集新建分类，附名称"), ("newproject", "在当前分类新建项目，附名称"),
            ("map", "查看当前集的关系图"), ("model", "切换当前会话模型"),
            ("history", "查看当前会话最近5轮对话"),
            ("status", "查看当前目标与状态"), ("stop", "暂停当前会话"),
            ("files", "查看待发送文件"), ("clear", "清除待发送文件引用"), ("help", "使用说明")]


class MobileNavigation:
    def __init__(self, host):
        self.host = host
        self.catalog = CatalogNavigation(self)
        self.menus = MenuState(self)
        self.pages = MenuPages(self)

    async def button(self, peer, text, action, **args):
        key = uuid4().hex
        if '_trail' not in args:
            args['_trail'] = (await self.menus.get(peer))['stack']
        await self.host.put("callbacks", key, dict(peer=peer, action=action, **args))
        return {"text": text, "callback_data": key}

    async def entry_button(self, peer, text, action, **args):
        return await self.button(peer, text[:60], action, **args)

    async def controls(self, peer, target, user_message_id=None):
        rows = []
        if target and target.get("session_id"):
            state = await self.menus.get(peer)
            trail = state.get('resume', []) if await self.host.get('selection', peer) == target else []
            rows.append([await self.button(peer, '进入此会话', 'select', target=target, _trail=trail),
                         await self.button(peer, '会话操作', 'actions', target=target, _trail=trail)])
        elif target and target.get('project_id'):
            rows.append([await self.button(peer, '选择会话', 'sessions', target=target)])
        else:
            rows.append([await self.button(peer, '打开菜单', 'collections')])
        if user_message_id:
            rows.append([await self.button(peer, "暂停本次任务", "stop", target=target, user_message_id=user_message_id)])
        return rows

    async def paged(self, peer, title, entries, action, args, page=0, target=None, extra_rows=None, leading_rows=None, operations=None):
        size = 8
        page = max(0, min(page, max(0, (len(entries)-1)//size)))
        await self.menus.enter(peer, action, dict(args, page=page))
        rows = [[await self.entry_button(peer, name, item_action, **data)]
                for name, item_action, data in entries[page*size:(page+1)*size]]
        nav = []
        if page:
            nav.append(await self.button(peer, "上一页", action, **args, page=page-1))
        if (page+1)*size < len(entries):
            nav.append(await self.button(peer, "下一页", action, **args, page=page+1))
        if nav:
            rows.append(nav)
        rows.extend(leading_rows or [])
        if operations:
            rows.append([await self.button(peer, label, operation, **data) for label, operation, data in operations])
        rows.extend(extra_rows or [])
        rows.extend(await self.menus.footer(peer))
        pages = max(1, (len(entries) + size - 1) // size)
        header = COLLECTIONS.get(args.get('kind'), '天策') if not target else None
        await self.host.reply(peer, self.page_text(title, len(entries), page, pages, action), target, rows, menu=True, header=header)

    def page_text(self, title, count, page, pages, action):
        page_label = f" · 第 {page + 1}/{pages} 页" if pages > 1 else ""
        return f"{title}（{count}）{page_label}" + ("\n暂无内容。" if not count else "")

    async def action(self, peer, action, **args):
        selected = await self.host.get("selection", peer)
        target = args.get("target", selected)
        if action in CATALOG_ACTIONS:
            await self.catalog.action(peer, action, target, args)
        elif action in PAGE_ACTIONS:
            await self.pages.show(peer, action, dict(args, target=target))
        elif action == "project":
            await asyncio.to_thread(resolve_target, target, session_required=False)
            await self.catalog.remember_project(peer, target)
            await self.action(peer, "sessions", target={'project_id': target['project_id']})
        elif action == "select":
            await asyncio.to_thread(resolve_target, target)
            await self.catalog.remember_project(peer, target)
            await self.host.put("selection", peer, target)
            await self.menus.enter(peer, action, {'target': target})
            rows = [[await self.button(peer, '会话操作', 'actions', target=target)]]
            if self.host.platform != 'wechat':
                rows.append([await self.button(peer, '返回会话列表', 'back')])
            await self.host.reply(peer, "已进入会话。之后的消息将发送到此会话。", target, rows)
        elif action == "new":
            path = route_origin.get()
            if path is None:
                path = (await self.menus.get(peer))['stack']
            frame = path[-1] if path else {}
            if frame.get('action') != 'sessions' or frame.get('parent') or frame.get('target', {}).get('project_id') != (target or {}).get('project_id'):
                raise BadRequestError('请在项目的主会话列表中新建会话。')
            target = await asyncio.to_thread(new_conversation, target, args.get("title"))
            await self.action(peer, 'select', target=target)
        elif action == "stop":
            await asyncio.to_thread(resolve_target, target)
            await self.host.reply(peer, "正在请求暂停，等待当前任务保存。", target)
            async def stop_and_report():
                try:
                    stopped = await self.host.desktop.stop(target, args.get("user_message_id"))
                    await self.host.reply(peer, "已暂停。" if stopped else "这次任务已经结束，没有暂停其他任务。", target)
                except Exception as exc:
                    await self.host.reply(peer, f"暂停未完成：{getattr(exc, 'message', str(exc))}", target)
            self.host.spawn(stop_and_report())
        elif action == "permission":
            request_id = args["request_id"]
            accepted = await get_tool_permission_bridge_service().submit_decision(request_id, args["decision"])
            await self.host.reply(peer, "已提交本次权限决定。" if accepted else "该权限请求已结束或已处理。", target)
        elif action in {"files", "clear"}:
            await asyncio.to_thread(resolve_target, target)
            key = self.host.staging_key(peer, target)
            staged = await self.host.get("staged", key, [])
            if action == "clear":
                await self.host.clear_staging(peer, target)
                text = "已清除待发送引用，工作区文件保留。"
            else:
                text = "待发送文件：\n" + "\n".join(f["reference"]["fileName"] for f in staged) if staged else "当前会话没有待发送文件。"
            await self.host.reply(peer, text, target)
        elif action == "history":
            await asyncio.to_thread(resolve_target, target)
            async def show_history():
                from .history import recent_history_text
                try:
                    text = await asyncio.to_thread(recent_history_text, target)
                    if await self.host.is_authorized(peer):
                        await self.host.reply(peer, text, target)
                except Exception as exc:
                    await self.host.reply(peer, f"历史记录读取失败：{getattr(exc, 'message', str(exc))}", target)
            self.host.spawn(show_history())
        elif action == "status":
            if not target or not target.get("session_id"):
                raise BadRequestError('请先进入会话，再查看会话状态。')
            _, session = await asyncio.to_thread(resolve_target, target)
            from app.services.project.conversation_run_manager import get_conversation_run_manager
            status = await get_conversation_run_manager().get_run_status(target["project_id"],target["session_id"])
            text = f"状态：{'运行中' if status['running'] else '空闲'}\n模型：{session.model_id or '未配置，请在天策设置'}"
            await self.host.reply(peer, text, target)
        else:
            await self.host.reply(peer, "先选择项目、会话，之后直接发消息即可。\n"
                "可以随时切换到其他会话；回复某条机器人消息也会切回它所属的会话。\n"
                "文件先保存并暂存引用，再发处理要求；文件附带的说明会直接提交。\n"
                "运行中的会话不接受新消息，请 /stop 暂停后重发。\n\n" +
                "\n".join(f"/{cmd} — {label}" for cmd,label in COMMANDS),
                rows=[[await self.button(peer, '打开菜单', 'collections')]], menu=True, header='天策 · 使用说明')

    async def message_target(self, peer, message):
        target = await self.host.get("selection", peer)
        replied = message.get("reply_to_message")
        if replied:
            mapping = await self.host.get("messages", f"{peer}:{replied['message_id']}")
            if not mapping or not (mapping.get("target") or {}).get("session_id"):
                raise BadRequestError("被回复的消息没有可用的会话对应关系，请用按钮重新选择；本条消息未提交。")
            target = mapping["target"]
            await asyncio.to_thread(resolve_target, target)
            await self.host.put("selection", peer, target)
            await self.catalog.remember_project(peer, target)
            await self.menus.enter(peer, 'select', {'target': target})
        else:
            state = await self.menus.get(peer)
            frame = state['stack'][-1] if state['stack'] else {}
            if state.get('scope') != self.host.access_scope.collections() or state['mode'] != 'conversation' or frame.get('action') != 'select' or frame.get('target') != target:
                raise BadRequestError('当前正在浏览菜单，请先进入会话或选择“返回当前会话”。本条消息未发送。')
        return target

    async def report_error(self, peer, text):
        state = await self.menus.get(peer)
        if state['mode'] == 'conversation':
            return await self.host.reply(peer, text)
        frame = state['stack'][-1] if state['stack'] else {}
        rows = await self.menus.footer(peer)
        if not rows:
            rows = [[await self.button(peer, '打开菜单', 'collections')]]
        await self.host.reply(peer, text, frame.get('target'), rows, menu=True,
                              header=COLLECTIONS.get(frame.get('kind'), '天策') if not frame.get('target') else None)
