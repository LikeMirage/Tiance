"""Durable browsing paths, independent of the last conversation selected for chat."""
import asyncio
from contextvars import ContextVar
from copy import deepcopy

from app.core.errors import BadRequestError, NotFoundError
from .context import resolve_target

route_origin = ContextVar('mobile_menu_origin', default=None)
FRAME_FIELDS = {'kind', 'category', 'target', 'parent', 'group', 'provider', 'page'}


class MenuState:
    def __init__(self, navigation):
        self.nav, self.host = navigation, navigation.host

    async def get(self, peer):
        return await self.host.get('menus', peer, {'mode': 'menu', 'stack': [], 'options': []})

    def root(self):
        return [{'action': 'collections'}] if len(self.host.access_scope.collections()) > 1 else []

    def categories(self, kind):
        return self.root() + [{'action': 'categories', 'kind': kind}]

    @staticmethod
    def prefix(path, action, **match):
        for index in range(len(path) - 1, -1, -1):
            frame = path[index]
            if frame['action'] == action and all(frame.get(k) == v for k, v in match.items()):
                return deepcopy(path[:index + 1])
        return []

    async def path(self, peer, action, args):
        state = await self.get(peer)
        source = route_origin.get()
        source = deepcopy(state['stack'] if source is None else source)
        # Old buttons may predate a scope change; reconstruct only allowed paths.
        if state.get('scope') != self.host.access_scope.collections():
            source = []
        source = [f for f in source if f['action'] != 'collections' or len(self.host.access_scope.collections()) > 1]
        frame = dict(action=action, **{k: v for k, v in args.items() if k in FRAME_FIELDS and v is not None})
        if action == 'collections':
            return [frame]
        if action == 'categories':
            return self.root() + [frame]
        if action in {'projects', 'map'}:
            base = self.prefix(source, 'categories', kind=args['kind']) or self.categories(args['kind'])
            return base + [frame]

        target = args['target']
        project, _ = await asyncio.to_thread(resolve_target, target, session_required=False)
        project_target = {'project_id': target['project_id']}
        base = self.prefix(source, 'projects', kind=project.project_kind)
        if not base or base[-1].get('category') not in {None, project.category_id}:
            base = self.categories(project.project_kind) + [dict(action='projects', kind=project.project_kind, category=project.category_id)]
        roots = base + [dict(action='sessions', target=project_target)]
        if action == 'sessions' and not args.get('parent'):
            return base + [frame]

        def conversation_path(chosen):
            existing = self.prefix(source, 'select', target=chosen)
            if existing:
                return existing
            listing = next((deepcopy(source[:i + 1]) for i in range(len(source) - 1, -1, -1)
                            if source[i]['action'] == 'sessions' and
                            source[i].get('target', {}).get('project_id') == chosen['project_id']), roots)
            return listing + [dict(action='select', target=chosen)]

        if action == 'select':
            return conversation_path(target)
        if action in {'actions', 'groups'}:
            return conversation_path(target) + [frame]
        if action == 'sessions':
            parent = dict(project_target, session_id=args['parent'])
            base = self.prefix(source, 'groups', target=parent) or conversation_path(parent) + [dict(action='groups', target=parent)]
            return base + [frame]
        if action == 'model':
            base = self.prefix(source, 'actions', target=target) or conversation_path(target)
            return base + [frame]
        if action == 'models':
            base = self.prefix(source, 'model', target=target) or conversation_path(target) + [dict(action='model', target=target)]
            return base + [frame]
        raise BadRequestError('菜单已失效，请重新打开菜单。')

    async def enter(self, peer, action, args):
        state = await self.get(peer)
        path = await self.path(peer, action, args)
        state.update(mode='conversation' if action == 'select' else 'menu', stack=path,
                     options=[], scope=self.host.access_scope.collections())
        state.pop('pending', None)
        if action == 'select':
            state['resume'] = deepcopy(path)
        await self.host.put('menus', peer, state)
        return state

    async def back(self, peer, path=None):
        state = await self.get(peer)
        path = deepcopy(state['stack'] if path is None else path)
        if state.get('pending'):
            state.pop('pending')
            await self.host.put('menus', peer, state)
        elif len(path) > 1:
            path.pop()
        if not path:
            return await self.nav.action(peer, 'collections')
        frame = path[-1]
        await self.nav.action(peer, **frame, _trail=path[:-1])

    async def target(self, peer):
        state = await self.get(peer)
        if state.get('scope') != self.host.access_scope.collections():
            return None
        if state['mode'] == 'conversation':
            return await self.host.get('selection', peer)
        return state['stack'][-1].get('target') if state['stack'] else None

    async def footer(self, peer):
        state = await self.get(peer)
        selected = await self.host.get('selection', peer)
        can_resume = bool(selected and selected.get('session_id'))
        if can_resume:
            can_resume = await self.host.access_scope.allows_target(selected)
        if can_resume:
            try:
                await asyncio.to_thread(resolve_target, selected)
            except (BadRequestError, NotFoundError):
                can_resume = False
        parent = state['stack'][-2] if len(state['stack']) > 1 else {}
        # Keep a clearly named return entry at every menu level. When the
        # immediate parent is that conversation, it also serves as Back.
        parent_is_selected = can_resume and parent.get('action') == 'select' and parent.get('target') == selected
        rows = []
        if len(state['stack']) > 1 and self.host.platform != 'wechat' and not parent_is_selected:
            labels = {'collections': '返回集列表', 'categories': '返回分类列表', 'projects': '返回项目列表',
                      'sessions': '返回会话列表', 'select': '返回会话', 'groups': '返回下级会话分类',
                      'model': '返回供应商', 'actions': '返回会话操作'}
            rows.append([await self.nav.button(peer, labels.get(parent['action'], '返回上一级'), 'back')])
        if can_resume:
            rows.append([await self.nav.button(peer, '返回之前会话', 'select', target=selected,
                                              _trail=state.get('resume', []))])
        return rows
