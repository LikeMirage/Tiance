"""Shared collection access and entry routing for inbound mobile adapters."""
import asyncio
from app.core.errors import BadRequestError
from .access_scope import reply_collections
from .context import COLLECTIONS
from .navigation import MobileNavigation


class ScopedNavigation(MobileNavigation):
    def __init__(self, host):
        super().__init__(host)
        self._action_task = None

    async def action(self, peer, action, **args):
        # Nested navigation stays in the same scope snapshot. A scope save waits
        # for an already accepted action to finish before reporting success.
        task = asyncio.current_task()
        if self._action_task is task:
            return await self._action(peer, action, **args)
        async with self.host.access_scope.lock:
            self._action_task = task
            try:
                return await self._action(peer, action, **args)
            finally:
                self._action_task = None

    async def _action(self, peer, action, **args):
        selected = await self.host.get('selection', peer)
        if selected and not await self.host.access_scope.allows_target(selected):
            await self.host.delete('selection', peer)
            selected = None
        target = args.get('target', selected)
        required = []
        if action == 'collections':
            allowed = self.host.access_scope.collections()
            if len(allowed) == 1:
                await self.action(peer, 'categories', kind=allowed[0], _root=True)
                return
            required = allowed
        if action in {'categories', 'projects'}:
            required = [args.get('kind')]
        elif action in {'newcategory', 'newproject', 'map'}:
            # With exactly one allowed collection, commands have an unambiguous
            # location even before the user opens a menu.
            location = await self.host.get('navigation', peer, {})
            allowed = self.host.access_scope.collections()
            if 'kind' not in args and not location and not selected and len(allowed) == 1:
                args = dict(args, kind=allowed[0], category=None)
            location = await self.catalog.location(peer, args)
            required = [location['kind']]
        elif action in {'project', 'sessions', 'groups', 'select', 'new', 'stop', 'permission',
                        'files', 'clear', 'history', 'status', 'model', 'models', 'setmodel', 'actions'}:
            await self.host.access_scope.require_target(target)
        for kind in required:
            self.host.access_scope.require_collection(kind)
        marker = reply_collections.set(tuple(required))
        try:
            await self.perform_action(peer, action, **args)
        finally:
            reply_collections.reset(marker)

    async def perform_action(self, peer, action, **args):
        if action == 'collections':
            allowed = self.host.access_scope.collections()
            if not allowed:
                await self.host.reply(peer, f'此连接尚未开放任何集，请在电脑端{self.host.label}连接配置中开启访问范围。', rows=[])
            else:
                await self.paged(peer, '选择集', [(COLLECTIONS[k], 'categories', {'kind': k}) for k in allowed], action, {})
        else:
            await super().action(peer, action, **args)

    async def message_target(self, peer, message):
        target = await self.host.get('selection', peer)
        replied = message.get('reply_to_message')
        if replied:
            mapping = await self.host.get('messages', f"{peer}:{replied['message_id']}")
            if not mapping or not (mapping.get('target') or {}).get('session_id'):
                raise BadRequestError('被回复的消息没有可用的会话对应关系，请用按钮重新选择；本条消息未提交。')
            target = mapping['target']
        await self.host.access_scope.require_target(target)
        return await super().message_target(peer, message)
