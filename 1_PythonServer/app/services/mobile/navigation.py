"""Shared navigation actions and platform-neutral button descriptions; ordinary conversation operations live below it."""
import asyncio
from uuid import uuid4

from app.core.errors import BadRequestError
from app.services.project import get_project_service, get_project_conversation_service
from app.services.tools.tool_permission_bridge import get_tool_permission_bridge_service
from .context import COLLECTIONS, GROUPS, resolve_target, session_children, new_conversation
from .catalog_navigation import CatalogNavigation, CATALOG_ACTIONS


COMMANDS = [("projects", "选择项目"), ("sessions", "选择会话"), ("new", "新建会话，可附标题"),
            ("newcategory", "在当前集新建分类，附名称"), ("newproject", "在当前分类新建项目，附名称"),
            ("map", "查看当前集的关系图"), ("model", "切换当前会话模型"),
            ("history", "查看当前会话最近5轮对话"),
            ("status", "查看当前目标与状态"), ("stop", "暂停当前会话"),
            ("files", "查看待发送文件"), ("clear", "清除待发送文件引用"), ("help", "使用说明")]


class MobileNavigation:
    def __init__(self, host):
        self.host = host
        self.catalog = CatalogNavigation(self)

    async def button(self, peer, text, action, **args):
        key = uuid4().hex
        await self.host.put("callbacks", key, dict(peer=peer, action=action, **args))
        return {"text": text, "callback_data": key}

    async def controls(self, peer, target, user_message_id=None):
        rows = [[await self.button(peer, "选择项目", "collections"),
                 await self.button(peer, "选择会话", "sessions", target=target or {})]]
        if target and target.get("session_id"):
            rows.insert(0, [await self.button(peer, "回复此会话", "select", target=target),
                            await self.button(peer, "下级会话", "groups", target=target)])
            rows.append([await self.button(peer, '切换模型', 'model', target=target),
                         await self.button(peer, '关系图', 'map')])
            rows.append([await self.button(peer, '查看前5轮对话', 'history', target=target)])
        if user_message_id:
            rows.append([await self.button(peer, "暂停本次任务", "stop", target=target, user_message_id=user_message_id)])
        return rows

    async def paged(self, peer, title, entries, action, args, page=0, target=None, extra_rows=None, leading_rows=None):
        size = 8
        page = max(0, min(page, max(0, (len(entries)-1)//size)))
        rows = list(leading_rows or [])
        rows.extend([[await self.button(peer, name[:60], item_action, **data)]
                     for name, item_action, data in entries[page*size:(page+1)*size]])
        nav = []
        if page:
            nav.append(await self.button(peer, "上一页", action, **args, page=page-1))
        if (page+1)*size < len(entries):
            nav.append(await self.button(peer, "下一页", action, **args, page=page+1))
        if nav:
            rows.append(nav)
        rows.extend(extra_rows or [])
        rows.append([await self.button(peer, "选择项目", "collections"), await self.button(peer, "当前会话", "status")])
        pages = max(1, (len(entries) + size - 1) // size)
        page_label = f" · 第 {page + 1}/{pages} 页" if pages > 1 else ""
        await self.host.reply(peer, f"{title}（{len(entries)}）{page_label}" + ("\n暂无内容。" if not entries else ""), target, rows)

    async def action(self, peer, action, **args):
        selected = await self.host.get("selection", peer)
        target = args.get("target", selected)
        if action in CATALOG_ACTIONS:
            await self.catalog.action(peer, action, target, args)
        elif action == "collections":
            await self.paged(peer, "选择项目集", [(v, "categories", {"kind": k}) for k,v in COLLECTIONS.items()], action, {})
        elif action == "categories":
            kind = args["kind"]
            from .catalog import collection_kind
            collection_kind(kind)
            await self.host.put('navigation', peer, {'kind': kind, 'category': None})
            categories = await asyncio.to_thread(get_project_service().list_project_categories)
            entries = [(c.name, "projects", {"kind": kind, "category": c.category_id})
                       for c in categories if c.category_kind == kind]
            entries.insert(0, ("全部项目", "projects", {"kind": kind, "category": None}))
            await self.paged(peer, COLLECTIONS[kind], entries, action, {"kind": kind}, args.get("page",0),
                             extra_rows=await self.catalog.actions(peer, kind))
        elif action == "projects":
            from .catalog import collection_kind
            collection_kind(args['kind'])
            await self.host.put('navigation', peer, {'kind': args['kind'], 'category': args.get('category')})
            projects = await asyncio.to_thread(get_project_service().list_projects)
            entries = [(p.name, "project", {"target": {"project_id": p.project_id}}) for p in projects
                       if p.project_kind == args["kind"] and (args.get("category") is None or p.category_id == args["category"])]
            await self.paged(peer, "选择项目", entries, action,
                             {"kind":args["kind"],"category":args.get("category")}, args.get("page",0),
                             extra_rows=await self.catalog.actions(peer, args['kind'], args.get('category')))
        elif action == "project":
            await asyncio.to_thread(resolve_target, target, session_required=False)
            await self.catalog.remember_project(peer, target)
            await self.host.put("selection", peer, target)
            await self.action(peer, "sessions", target=target)
        elif action == "sessions":
            await asyncio.to_thread(resolve_target, target, session_required=False)
            entries = await asyncio.to_thread(session_children, target["project_id"], args.get("parent"), args.get("group"))
            items = [(s.title, "select", {"target": {"project_id":target["project_id"],"session_id":s.session_id}}) for s,_ in entries]
            rows_args = {"target": target, "parent":args.get("parent"),"group":args.get("group")}
            leading_rows = [[await self.button(peer, "＋ 新建主会话", "new",
                            target={"project_id": target["project_id"]})]]
            await self.paged(peer, GROUPS.get(args.get("group"), "主会话"), items, action, rows_args,
                             args.get("page",0), target, leading_rows=leading_rows)
        elif action == "groups":
            await asyncio.to_thread(resolve_target, target)
            entries = [(label, "sessions", {"target":target,"parent":target["session_id"],"group":group}) for group,label in GROUPS.items()]
            nodes, _ = await asyncio.to_thread(get_project_conversation_service().list_branch_graph, target["project_id"])
            node = next((n for n in nodes if n.session_id == target["session_id"] and not n.deleted_at), None)
            if node and node.parent_session_id:
                entries.insert(0, ("返回上级会话", "select", {"target":dict(target, session_id=node.parent_session_id)}))
            await self.paged(peer, "下级会话分类", entries, action, {"target":target}, target=target)
        elif action == "select":
            await asyncio.to_thread(resolve_target, target)
            await self.catalog.remember_project(peer, target)
            await self.host.put("selection", peer, target)
            await self.host.reply(peer, "已切换。之后的消息将发送到此会话。", target)
        elif action == "new":
            target = await asyncio.to_thread(new_conversation, target, args.get("title"))
            await self.catalog.remember_project(peer, target)
            await self.host.put("selection", peer, target)
            await self.host.reply(peer, "已新建并选中会话，使用该项目集的默认角色。", target)
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
                await self.host.reply(peer, "请使用按钮选择项目、会话，或 /new 新建。", target)
                return
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
                "\n".join(f"/{cmd} — {label}" for cmd,label in COMMANDS), selected)

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
        return target
