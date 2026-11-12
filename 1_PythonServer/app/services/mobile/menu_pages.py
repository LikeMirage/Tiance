"""Collection, project and conversation menus with operations local to each level."""
import asyncio

from app.core.errors import BadRequestError
from app.services.project import get_project_service
from .context import COLLECTIONS, GROUPS, resolve_target, session_children, session_relations

PAGE_ACTIONS = {'collections', 'categories', 'projects', 'sessions', 'groups', 'actions'}


class MenuPages:
    def __init__(self, navigation):
        self.nav, self.host = navigation, navigation.host

    async def show(self, peer, action, args):
        nav = self.nav
        page = args.get('page', 0)
        if action == 'collections':
            allowed = self.host.access_scope.collections()
            if not allowed:
                await nav.menus.enter(peer, action, {})
                await self.host.reply(peer, f'此连接尚未开放任何集，请在电脑端{self.host.label}连接配置中开启访问范围。',
                                      rows=[], menu=True, header='天策')
                return
            await nav.paged(peer, '选择集', [(COLLECTIONS[k], 'categories', {'kind': k}) for k in allowed], action, {})
        elif action == 'categories':
            kind = args['kind']
            await self.host.put('navigation', peer, {'kind': kind, 'category': None})
            categories = await asyncio.to_thread(get_project_service().list_project_categories)
            entries = [('全部项目', 'projects', {'kind': kind, 'category': None})]
            entries += [(c.name, 'projects', {'kind': kind, 'category': c.category_id})
                        for c in categories if c.category_kind == kind]
            await nav.paged(peer, COLLECTIONS[kind], entries, action, {'kind': kind}, page,
                            operations=[('新建分类', 'newcategory', {'kind': kind}), ('关系图', 'map', {'kind': kind})])
        elif action == 'projects':
            kind, category = args['kind'], args.get('category')
            title = '全部项目'
            if category:
                chosen = await asyncio.to_thread(get_project_service().get_project_category, category)
                if not chosen or chosen.category_kind != kind:
                    raise BadRequestError('分类已不存在，请返回分类列表重新选择。')
                title = f'分类：{chosen.name}'
            await self.host.put('navigation', peer, {'kind': kind, 'category': category})
            projects = await asyncio.to_thread(get_project_service().list_projects)
            entries = [(p.name, 'project', {'target': {'project_id': p.project_id}}) for p in projects
                       if p.project_kind == kind and (category is None or p.category_id == category)]
            operations = [('新建项目', 'newproject', {'kind': kind, 'category': category})] if category else []
            await nav.paged(peer, title, entries, action, {'kind': kind, 'category': category}, page, operations=operations)
        elif action == 'sessions':
            target = args['target']
            await asyncio.to_thread(resolve_target, target, session_required=False)
            parent, group = args.get('parent'), args.get('group')
            if parent:
                await asyncio.to_thread(resolve_target, dict(target, session_id=parent))
                if group not in GROUPS:
                    raise BadRequestError('下级会话分类已失效，请重新选择。')
            else:
                target = {'project_id': target['project_id']}
            sessions = await asyncio.to_thread(session_children, target['project_id'], parent, group)
            items = [(s.title, 'select', {'target': {'project_id': target['project_id'], 'session_id': s.session_id}}) for s, _ in sessions]
            operations = [] if parent else [('新建主会话', 'new', {'target': target})]
            await nav.paged(peer, GROUPS.get(group, '主会话'), items, action,
                            {'target': target, 'parent': parent, 'group': group}, page, target, operations=operations)
        elif action == 'groups':
            target = args['target']
            await asyncio.to_thread(resolve_target, target)
            groups, parent = await asyncio.to_thread(session_relations, target)
            entries = [(GROUPS[g], 'sessions', {'target': target, 'parent': target['session_id'], 'group': g}) for g in groups]
            operations = [('进入上级会话', 'select', {'target': dict(target, session_id=parent)})] if parent else []
            await nav.paged(peer, '下级会话分类', entries, action, {'target': target}, target=target, operations=operations)
        elif action == 'actions':
            target = args['target']
            await asyncio.to_thread(resolve_target, target)
            await nav.menus.enter(peer, action, {'target': target})
            rows = await self.conversation_controls(peer, target)
            rows += await nav.menus.footer(peer)
            await self.host.reply(peer, '会话操作', target, rows, menu=True)

    async def conversation_controls(self, peer, target):
        nav = self.nav
        rows = [[await nav.button(peer, '查看前5轮对话', 'history', target=target),
                 await nav.button(peer, '切换模型', 'model', target=target)],
                [await nav.button(peer, '会话状态', 'status', target=target),
                 await nav.button(peer, '暂停会话', 'stop', target=target)]]
        groups, parent = await asyncio.to_thread(session_relations, target)
        if groups:
            rows.append([await nav.button(peer, '下级会话', 'groups', target=target)])
        if parent:
            rows.append([await nav.button(peer, '进入上级会话', 'select', target=dict(target, session_id=parent))])
        staged = await self.host.get('staged', self.host.staging_key(peer, target), [])
        if staged:
            rows.append([await nav.button(peer, '待发送文件', 'files', target=target),
                         await nav.button(peer, '清除待发送引用', 'clear', target=target)])
        return rows
