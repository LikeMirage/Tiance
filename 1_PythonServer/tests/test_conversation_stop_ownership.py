import asyncio
from types import SimpleNamespace

import pytest

from app.core.errors import AppError
from app.domain.llm.chat import ChatCompletionRequest
from app.services.project.conversation_run_manager import ConversationRunManager


def test_repeated_stop_and_disconnected_waiter_do_not_interrupt_settlement():
    async def scenario():
        started, saving, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        saved = []
        class Stream:
            async def stream_payloads(self, *_args, **_kwargs):
                started.set()
                try:
                    yield {'kind': 'delta', 'content': 'partial'}
                    await asyncio.Event().wait()
                finally:
                    saving.set()
                    await release.wait()
                    saved.append(True)
        async def pending(**_kwargs): return ()
        manager = ConversationRunManager(SimpleNamespace(pending_request_ids=pending),
            tool_permission_bridge_service=SimpleNamespace(pending_request_ids=pending))
        request = ChatCompletionRequest(provider_id='p', model_id='m', project_id='p', session_id='s', messages=())
        await manager.start(request, Stream())
        await started.wait()
        first = asyncio.create_task(manager.stop('p', 's'))
        await saving.wait()
        second = asyncio.create_task(manager.stop('p', 's'))
        await asyncio.sleep(0)
        first.cancel()  # Browser/request goes away while durable settlement is running.
        await asyncio.gather(first, return_exceptions=True)
        assert await manager.is_running('p', 's')
        assert not second.done()
        release.set()
        assert await second is True
        assert saved == [True]
        assert not await manager.is_running('p', 's')
    asyncio.run(scenario())


@pytest.mark.parametrize('settled', [False, True])
def test_stop_distinguishes_failed_settlement_from_failure_after_committed_settlement(settled):
    async def scenario():
        started = asyncio.Event()
        class Stream:
            async def stream_payloads(self, *_args, **_kwargs):
                started.set()
                try:
                    yield {'kind': 'delta', 'content': 'partial'}
                    await asyncio.Event().wait()
                finally:
                    if settled:
                        yield {'kind': 'conversation_run_settled', 'status': 'cancelled'}
                    raise OSError('injected database save failure')
        async def pending(**_kwargs): return ()
        manager = ConversationRunManager(SimpleNamespace(pending_request_ids=pending),
            tool_permission_bridge_service=SimpleNamespace(pending_request_ids=pending))
        await manager.start(ChatCompletionRequest(provider_id='p', model_id='m', project_id='p', session_id='s', messages=()), Stream())
        await started.wait()
        if settled:
            assert await manager.stop('p', 's') is True
        else:
            with pytest.raises(AppError) as error:
                await manager.stop('p', 's')
            assert error.value.code == 'conversation_stop_settlement_failed'
        assert not await manager.is_running('p', 's')
    asyncio.run(scenario())
