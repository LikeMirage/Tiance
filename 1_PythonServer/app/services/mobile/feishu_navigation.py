"""Presentation metadata for Feishu cards; callbacks retain shared navigation semantics."""
from .scoped_navigation import ScopedNavigation


class FeishuNavigation(ScopedNavigation):
    async def button(self, peer, text, action, **args):
        button = await super().button(peer, text, action, **args)
        role = 'pagination' if 'page' in args else (
            'navigation' if action in {'collections', 'status', 'sessions', 'groups'} else 'operation')
        tone = 'danger' if action in {'stop', 'clear'} or args.get('decision') == 'deny' else (
            'primary' if action in {'new', 'newcategory', 'newproject', 'select', 'permission'} else 'default')
        button['presentation'] = {'role': role, 'tone': tone}
        return button

    async def entry_button(self, peer, text, action, **args):
        button = await self.button(peer, text, action, **args)
        selected = await self.host.get('selection', peer) or {}
        target = args.get('target') or {}
        current = bool(selected) and (
            action == 'select' and target == selected or
            action == 'project' and target.get('project_id') == selected.get('project_id'))
        button['presentation'] = {
            'role': 'entry', 'current': current,
            'label': '选用' if action == 'setmodel' else '进入' if action == 'select' else '打开',
        }
        return button
