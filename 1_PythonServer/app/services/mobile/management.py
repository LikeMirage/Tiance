"""Explicit removal of access identities; never deletes project data or stops AI runs."""
import asyncio

from app.core.errors import BadRequestError


async def require_idle(adapter, peer=None):
    # Removing a delivery owner mid-run would silently discard its result. The
    # user can revoke access immediately, but must settle work before removal.
    jobs = await adapter.records('jobs')
    if any(peer is None or job.get('peer') == peer for _, job in jobs):
        raise BadRequestError('仍有待提交或运行中的手机任务，请先暂停或等待结束，再删除。')
    if any(not task.done() for task in adapter.work):
        raise BadRequestError('该连接仍有消息或文件正在处理，请稍后再删除；可先关闭授权。')


async def remove_peer(adapter, peer):
    async with adapter.dispatch_lock, adapter.desktop.lock:
        record = await adapter.get('peers', peer)
        if not record:
            raise BadRequestError('该接入用户不存在。')
        await require_idle(adapter, peer)
        await asyncio.to_thread(adapter.repository.remove_peer, peer)
    await adapter.activity('user_removed', user_id=record.get('user_id'), chat_id=record.get('chat_id'))


async def remove_connection(adapter, platform, started):
    async with adapter.dispatch_lock, adapter.desktop.lock:
        await require_idle(adapter)
        # Stop all receivers before deleting credentials/cursors. No old poll
        # may recreate records or continue accepting messages after removal.
        await adapter.close()
        try:
            await asyncio.to_thread(adapter.repository.remove_connection, platform)
        except BaseException:
            if started:
                await adapter.start()
            raise
        adapter.transport = None
        adapter.config = {}
