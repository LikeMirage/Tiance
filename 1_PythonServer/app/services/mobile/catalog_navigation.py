"""Shared catalog creation, diagrams and model selection."""
import asyncio

from app.core.errors import BadRequestError
from app.core.shutdown_tasks import finish_commit
from app.services.project import get_project_service
from . import catalog, models
from .context import COLLECTIONS, resolve_target
from .relationship_diagram import render_diagram, remove_diagram
from .access_scope import SCOPE_CHANGED

CATALOG_ACTIONS = {'newcategory', 'newproject', 'map', 'model', 'models', 'setmodel'}


class CatalogNavigation:
    def __init__(self, navigation):
        self.nav = navigation
        self.host = navigation.host
        self.diagrams = set()

    async def remember_project(self, peer, target):
        project, _ = await asyncio.to_thread(resolve_target, target, session_required=False)
        await self.host.put('navigation', peer, {'kind': project.project_kind, 'category': project.category_id})

    async def location(self, peer, args):
        if 'kind' in args:
            location = {'kind': args['kind'], 'category': args.get('category')}
        else:
            state = await self.nav.menus.get(peer)
            if state['stack'] and state.get('scope') != self.host.access_scope.collections():
                raise BadRequestError(SCOPE_CHANGED)
            frame = state['stack'][-1] if state['stack'] and state.get('scope') == self.host.access_scope.collections() else {}
            location = {'kind': frame.get('kind'), 'category': frame.get('category')}
            target = args.get('target') or await self.nav.menus.target(peer)
            if target:
                project, _ = await asyncio.to_thread(resolve_target, target, session_required=False)
                location = {'kind': project.project_kind, 'category': project.category_id}
            if not location.get('kind') and len(self.host.access_scope.collections()) == 1:
                location['kind'] = self.host.access_scope.collections()[0]
        catalog.collection_kind(location.get('kind'))
        return location

    async def action(self, peer, action, target, args):
        if action in {'model', 'models', 'setmodel'}:
            await self.model_action(peer, action, target, args)
            return
        location = await self.location(peer, args)
        kind, category = location['kind'], location.get('category')
        if action == 'map':
            key = (peer, kind)
            if key in self.diagrams:
                await self.host.reply(peer, '这个集的关系图正在生成。')
                return
            await self.nav.menus.enter(peer, 'map', {'kind': kind})
            rows = [[await self.nav.button(peer, '刷新关系图', 'map', kind=kind)]]
            rows += await self.nav.menus.footer(peer)
            await self.host.reply(peer, '正在生成关系图…', rows=rows, menu=True, header=COLLECTIONS[kind])
            self.diagrams.add(key)
            self.host.spawn(self.diagram(peer, kind, key))
            return
        # Persist the explicit button location, so a subsequent /new... command
        # cannot accidentally use an unrelated previously selected conversation.
        await self.host.put('navigation', peer, location)
        title = args.get('title')
        if action == 'newcategory':
            if not title:
                await self.nav.menus.enter(peer, 'categories', {'kind': kind})
                rows = [[await self.nav.button(peer, '取消，返回分类列表', 'categories', kind=kind)]]
                await self.host.reply(peer, f"在{COLLECTIONS[kind]}新建分类，请发送：\n/newcategory 分类名称",
                                      rows=rows, menu=True, header=COLLECTIONS[kind])
                return
            created = await asyncio.to_thread(catalog.create_category, kind, title)
            await self.nav.action(peer, 'projects', kind=kind, category=created.category_id)
        elif action == 'newproject':
            chosen = await asyncio.to_thread(get_project_service().get_project_category, category) if category else None
            if chosen is None or chosen.category_kind != kind:
                raise BadRequestError('请先选择一个具体分类，再新建项目。')
            if not title:
                await self.nav.menus.enter(peer, 'projects', {'kind': kind, 'category': category})
                rows = [[await self.nav.button(peer, '取消，返回项目列表', 'projects', kind=kind, category=category)]]
                await self.host.reply(peer, f"在{COLLECTIONS[kind]} / {chosen.name}新建项目，请发送：\n/newproject 项目名称",
                                      rows=rows, menu=True, header=COLLECTIONS[kind])
                return
            project = await asyncio.to_thread(catalog.create_project, kind, category, title)
            target = {'project_id': project.project_id}
            await self.host.reply(peer, '项目已新建，请选择会话。', target, rows=[], menu=True)
            await self.nav.action(peer, 'project', target=target)

    async def diagram(self, peer, kind, key):
        paths = []
        transferred = set()
        try:
            outline = await asyncio.to_thread(catalog.collection_outline, kind)
            async def render():
                nonlocal paths
                paths = await asyncio.to_thread(render_diagram, outline)
            # Join the worker and capture its paths before cancellation cleanup.
            await finish_commit(render())
            if not await self.host.is_authorized(peer):
                return
            rows = [[await self.nav.button(peer, '返回该集', 'categories', kind=kind),
                     await self.nav.button(peer, '刷新关系图', 'map', kind=kind)]]
            if self.host.platform == 'wechat':
                # Its numbered controls were sent synchronously before rendering.
                # A late image must not replace a newer menu's numeric choices.
                rows = []
            total = len(paths)
            for number, path in enumerate(paths, 1):
                async def enqueue():
                    await self.host.reply_diagram(peer, path, f'{COLLECTIONS[kind]} · 第 {number}/{total} 张', rows)
                    transferred.add(path)
                await finish_commit(enqueue())  # Record ownership before cancellation.
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.host.reply(peer, f"关系图生成失败：{getattr(exc, 'message', str(exc))}",
                                  rows=[], menu=True, header=COLLECTIONS[kind])
        finally:
            for path in paths:
                if path not in transferred:
                    await asyncio.to_thread(remove_diagram, path)
            self.diagrams.discard(key)

    async def model_action(self, peer, action, target, args):
        _, session = await asyncio.to_thread(resolve_target, target)
        if action == 'setmodel':
            model = await asyncio.to_thread(models.select_model, target, args['provider'], args['model'])
            await self.host.reply(peer, f'已切换模型：{model.provider_label} / {model.model_label}。\n下次发送消息使用此模型；已经运行的任务继续使用原模型。', target)
            return
        entries = await asyncio.to_thread(models.available_models)
        if action == 'model':
            providers = dict((m.provider_id, m.provider_label) for m in entries)
            items = [(label, 'models', {'target': target, 'provider': provider}) for provider, label in providers.items()]
            await self.nav.paged(peer, '切换模型 · 选择供应商', items, action, {'target': target}, args.get('page', 0), target)
        else:
            provider = args['provider']
            items = [(('✓ ' if session.provider_id == provider and session.model_id == m.model_id else '') + m.model_label,
                      'setmodel', {'target': target, 'provider': provider, 'model': m.model_id})
                     for m in entries if m.provider_id == provider]
            await self.nav.paged(peer, '选择模型', items, action, {'target': target, 'provider': provider},
                                 args.get('page', 0), target)
