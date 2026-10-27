import asyncio
from types import SimpleNamespace

import pytest

from app.core.errors import AppError
from app.core.shutdown_tasks import shutdown_tasks
from app.services.application import desktop_exit as module
from app.services.project.conversation_background_tasks import ConversationBackgroundTaskRegistry
from app.services.project.conversation_run_manager import ConversationRunManager
from app.domain.llm.chat import ChatCompletionRequest


def test_exit_waits_for_cancel_cleanup_then_final_audits_and_blocks_new_work(monkeypatch):
    async def run():
        events = []
        cancelled, release_message, release_audit = asyncio.Event(), asyncio.Event(), asyncio.Event()
        audit_tasks = []
        manager = ConversationRunManager(SimpleNamespace(), tool_permission_bridge_service=SimpleNamespace())
        background = ConversationBackgroundTaskRegistry()

        class Stream:
            async def stream_payloads(self, *args, **kwargs):
                try:
                    yield {'kind': 'delta', 'content': 'partial'}
                    await asyncio.Event().wait()
                finally:
                    events.append('cancelled')
                    cancelled.set()
                    await release_message.wait()
                    events.append('message-saved')
                    async def save():
                        await release_audit.wait()
                        events.append('audit-saved')
                    audit_tasks.append(asyncio.create_task(save()))

        class Audit:
            async def close(self):
                events.append('audit-drain')
                await asyncio.gather(*audit_tasks)

        monkeypatch.setattr(module, 'get_conversation_run_manager', lambda: manager)
        monkeypatch.setattr(module, 'get_conversation_background_task_registry', lambda: background)
        monkeypatch.setattr(module, 'get_conversation_audit_service', lambda: Audit())
        request = ChatCompletionRequest(provider_id='p', model_id='m', project_id='p', session_id='s', messages=())
        await manager.start(request, Stream())
        await asyncio.sleep(0)
        exit = module.DesktopExitCoordinator()
        assert exit.begin() > 0
        await cancelled.wait()
        assert exit.begin() > 0  # polling cannot cancel cleanup a second time
        with pytest.raises(AppError, match='退出'):
            await manager.start(request, Stream())
        started = []
        async def forbidden(): started.append(True)
        suppressed = background.create_task('p', 's', forbidden(), name='late-background')
        await asyncio.gather(suppressed, return_exceptions=True)
        assert not started
        release_message.set()
        for _ in range(8): await asyncio.sleep(0)
        assert 'message-saved' in events and 'audit-saved' not in events
        assert exit.begin() > 0
        release_audit.set()
        await exit.close()
        assert exit.begin() == 0
        assert events.index('message-saved') < events.index('audit-drain') < events.index('audit-saved')
        await exit.abandon()
        shutdown_tasks.require_accepting()

    asyncio.run(run())


def test_failure_keeps_exit_unready_and_can_be_retried(monkeypatch):
    async def run():
        calls = []
        async def stop(): calls.append('stop')
        async def fail(): raise OSError('disk unavailable')
        owner = SimpleNamespace(close=stop)
        audit = SimpleNamespace(close=fail)
        monkeypatch.setattr(module, 'get_conversation_run_manager', lambda: owner)
        monkeypatch.setattr(module, 'get_conversation_background_task_registry', lambda: owner)
        monkeypatch.setattr(module, 'get_conversation_audit_service', lambda: audit)
        exit = module.DesktopExitCoordinator()
        with pytest.raises(RuntimeError, match='保存失败'):
            await exit.close()
        with pytest.raises(RuntimeError): exit.begin()
        assert not shutdown_tasks.accepting
        await exit.abandon()
        audit.close = stop
        await exit.close()
        assert exit.begin() == 0
        await exit.abandon()
    asyncio.run(run())


def test_message_settlement_failure_reaches_exit_coordinator(monkeypatch):
    async def run():
        entered = asyncio.Event()
        manager = ConversationRunManager(SimpleNamespace(), tool_permission_bridge_service=SimpleNamespace())
        class Stream:
            async def stream_payloads(self, *args, **kwargs):
                try:
                    yield {'kind': 'delta', 'content': 'partial'}
                    entered.set()
                    await asyncio.Event().wait()
                finally:
                    raise OSError('cannot save interrupted message')
        drained = []
        async def close(): drained.append(True)
        monkeypatch.setattr(module, 'get_conversation_run_manager', lambda: manager)
        monkeypatch.setattr(module, 'get_conversation_background_task_registry', lambda: SimpleNamespace(close=close))
        monkeypatch.setattr(module, 'get_conversation_audit_service', lambda: SimpleNamespace(close=close))
        request = ChatCompletionRequest(provider_id='p', model_id='m', project_id='p', session_id='s', messages=())
        await manager.start(request, Stream())
        await entered.wait()
        exit = module.DesktopExitCoordinator()
        with pytest.raises(RuntimeError, match='收尾'):
            await exit.close()
        assert len(drained) == 2
        with pytest.raises(RuntimeError): exit.begin()
        await exit.abandon()
    asyncio.run(run())
