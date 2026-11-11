"""Connection-level collection access for inbound adapters; checked again at delivery."""
import asyncio
from contextvars import ContextVar

from app.core.errors import BadRequestError, NotFoundError
from .context import COLLECTIONS, resolve_target

DEFAULT_COLLECTIONS = ('project',)
reply_collections = ContextVar('mobile_reply_collections', default=())
SCOPE_CHANGED = '该内容不在此机器人的访问范围内，请发送 /projects 重新选择。'


def validate_collections(values):
    if not isinstance(values, list) or any(not isinstance(v, str) or v not in COLLECTIONS for v in values):
        raise BadRequestError('访问范围包含无效的集。')
    if len(set(values)) != len(values):
        raise BadRequestError('访问范围不能包含重复的集。')
    return [kind for kind in COLLECTIONS if kind in values]


class MobileAccessScope:
    def __init__(self, host):
        self.host = host
        self.lock = asyncio.Lock()

    def collections(self):
        return list(self.host.config.get('allowed_collections', DEFAULT_COLLECTIONS))

    def require_collection(self, kind):
        if kind not in self.collections():
            raise BadRequestError(SCOPE_CHANGED)

    async def allows_target(self, target):
        if not target:
            return True
        try:
            project, _ = await asyncio.to_thread(resolve_target, {'project_id': target.get('project_id')}, session_required=False)
        except (BadRequestError, NotFoundError):
            return False
        return project.project_kind in self.collections()

    async def require_target(self, target):
        if not await self.allows_target(target):
            raise BadRequestError(SCOPE_CHANGED)

    async def allows_delivery(self, item):
        if item.get('public'):
            return True
        if self.host.platform == 'wechat' and not item.get('target') and 'access_collections' not in item:
            return False
        if not set(item.get('access_collections', ())).issubset(self.collections()):
            return False
        if not await self.allows_target(item.get('target')):
            return False
        # Also covers durable buttons queued before collection scopes existed.
        for row in item.get('rows', []):
            for button in row:
                data = await self.host.get('callbacks', button['callback_data'], {})
                if data.get('kind') and data['kind'] not in self.collections():
                    return False
                if not await self.allows_target(data.get('target')):
                    return False
        return True
