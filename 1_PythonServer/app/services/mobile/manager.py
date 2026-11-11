"""One desktop entry point; independent, connection-scoped platform adapters."""
import asyncio

from app.core.errors import BadRequestError
from .desktop_bridge import MobileDesktopBridge
from .service import MobileService, FeishuService, WeChatService
from .telegram_config import validate_configuration
from .activity import record_activity

INBOUND_ADAPTERS = {'telegram': MobileService, 'feishu': FeishuService, 'wechat': WeChatService}


class MobileAccessService:
    def __init__(self, repository):
        self.repository = repository
        self.adapters = {}
        self.desktop = MobileDesktopBridge(repository, self.result, self.is_authorized)
        self.lock = asyncio.Lock()
        self.started = False
        from .wechat_login import WeChatLogin
        self.wechat_login = WeChatLogin(self)

    async def connection_records(self, platform=None):
        return await asyncio.to_thread(self.repository.connections, platform)

    async def selected(self, connection_id=None, platform='telegram'):
        return connection_id or await asyncio.to_thread(self.repository.get, 'settings', f'{platform}_selected')

    async def activity(self, connection_id=None, offset=0, limit=50, platform='telegram'):
        key = await self.selected(connection_id, platform)
        return await asyncio.to_thread(self.repository.scoped(key or '').activity_page, offset, limit)

    async def status(self, connection_id=None, platform='telegram'):
        from .messaging import public_connection
        if platform not in INBOUND_ADAPTERS:
            raise BadRequestError('不支持此接入平台。')
        key = await self.selected(connection_id, platform)
        records = await self.connection_records(platform)
        record = next((r for r in records if r['connection_id'] == key), None)
        if key and record is None:
            raise BadRequestError('连接不存在或不属于此平台。')
        adapter = self.adapters.get(key)
        if adapter is None:
            if record:
                adapter = await self.install(record)
        status = await (adapter or INBOUND_ADAPTERS[platform](self.repository.scoped(''), desktop=self.desktop)).status()
        return dict(status, platform=platform, app_id=(record or {}).get('config', {}).get('app_id', ''),
                    connections=[public_connection(r) for r in records])

    async def configure_platform(self, platform, *, enabled, connection_id=None, app_id='', secret=''):
        from app.infra.secrets import encrypt_secret, decrypt_secret
        from .feishu_transport import FeishuTransport
        async with self.lock:
            key = await self.selected(connection_id, platform)
            old = next((r for r in await self.connection_records(platform) if r['connection_id'] == key), None)
            if not enabled:
                if old:
                    await self.save_platform(platform, old['remote_id'], dict(old['config'], enabled=False))
                return await self.status(key, platform)
            if platform == 'feishu':
                app_id = app_id.strip() or (old or {}).get('config', {}).get('app_id', '')
                value = secret.strip()
                if not value and old and old['remote_id'] == app_id:
                    value = decrypt_secret(old['config']['token'])
                if not app_id or not value:
                    raise BadRequestError('请填写飞书 App ID 和 App Secret。')
                bot = await FeishuTransport(app_id, value).identity()
                key = await self.save_platform(platform, app_id, {'enabled': True, 'app_id': app_id,
                    'token': encrypt_secret(value), 'bot': bot})
            elif platform == 'wechat':
                if not old:
                    raise BadRequestError('请先扫码连接微信。')
                key = await self.save_platform(platform, old['remote_id'], dict(old['config'], enabled=True))
            else:
                raise BadRequestError('不支持此接入平台。')
            return await self.status(key, platform)

    async def save_platform(self, platform, remote_id, config):
        key = f'{platform}:{remote_id}'
        await asyncio.to_thread(self.repository.save_connection, key, platform, str(remote_id), config, select=True)
        adapter = await self.install(dict(connection_id=key, platform=platform, config=config))
        await record_activity(adapter.repository, 'enabled' if config.get('enabled') else 'disabled')
        return key

    async def install(self, record):
        key = record['connection_id']
        # Add another platform here when its adapter is implemented. Unknown
        # platforms stay stored, and cannot accidentally use Telegram transport.
        factory = INBOUND_ADAPTERS.get(record['platform'])
        if factory is None:
            raise BadRequestError('当前版本尚未实现此平台的接入适配器。')
        adapter = self.adapters.get(key)
        if adapter is None:
            adapter = factory(self.repository.scoped(key), desktop=self.desktop)
            self.adapters[key] = adapter
        await adapter.apply_config(record['config'])
        if self.started and not adapter.tasks:
            await adapter.start()
        return adapter

    async def configure(self, *, token, enabled, api_base, connection_id=None):
        async with self.lock:
            selected = await self.selected(connection_id)
            records = await self.connection_records('telegram')
            old = next((r['config'] for r in records if r['connection_id'] == selected), {})
            try:
                config = await validate_configuration(old, token=token, enabled=enabled, api_base=api_base)
            except Exception as exc:
                await record_activity(self.repository.scoped(selected or ''), 'configuration_failed', level='error', error=exc)
                raise
            if not config.get('bot'):
                return await self.status()
            key = f"telegram:{config['bot']['id']}"
            # A token for a different bot creates/selects a different connection.
            # It never changes the identity of an in-flight upload or AI reply.
            await asyncio.to_thread(self.repository.save_connection, key, 'telegram', str(config['bot']['id']), config, select=True)
            adapter = await self.install(dict(connection_id=key, platform='telegram', config=config))
            await record_activity(adapter.repository, 'enabled' if enabled else 'disabled')
            return await self.status(key)

    async def for_peer(self, peer):
        identity = await asyncio.to_thread(self.repository.get, 'peers', peer, {})
        key = identity.get('connection_id')
        if not key:
            key = await asyncio.to_thread(self.repository.record_connection, 'peers', peer)
        return self.adapters.get(key)

    async def is_authorized(self, peer):
        adapter = await self.for_peer(peer)
        return bool(adapter and await adapter.is_authorized(peer))

    async def authorize(self, peer, allowed):
        adapter = await self.for_peer(peer)
        if not adapter:
            raise BadRequestError('该用户所属连接不存在。')
        await adapter.authorize(peer, allowed)
        return await self.status(adapter.repository.connection_id, adapter.platform)

    async def result(self, job, status, content):
        adapter = await self.for_peer(job['peer'])
        if not adapter:
            # Leave the durable job in place rather than dropping its final reply.
            raise BadRequestError('结果所属接入连接不存在，已保留待回传记录。')
        await adapter.result(job, status, content)

    async def start(self):
        for record in await self.connection_records():
            if record['platform'] in INBOUND_ADAPTERS:
                await self.install(record)
        await self.desktop.recover()
        self.started = True
        for adapter in self.adapters.values():
            await adapter.start()

    async def close(self):
        self.started = False
        await self.wechat_login.close()
        await asyncio.gather(*(adapter.close() for adapter in self.adapters.values()))

    async def drain_runs(self):
        if self.desktop.tasks:
            await asyncio.gather(*self.desktop.tasks, return_exceptions=True)
