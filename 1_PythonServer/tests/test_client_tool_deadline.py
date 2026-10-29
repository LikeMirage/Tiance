import asyncio

import pytest

from app.domain.llm.chat import ChatToolCall
from app.services.tools.client_tool_bridge import ClientToolBridgeService, ClientToolResultPayload


async def create(bridge, timeout=600):
    return await bridge.create_request(ChatToolCall(call_id="call", name="test", arguments="{}"),
                                       project_id="project", session_id="session", timeout_seconds=timeout)


@pytest.mark.parametrize("operation", ["claim", "renew", "submit", "replay"])
def test_original_deadline_is_enforced_without_a_waiter(monkeypatch, operation):
    async def run():
        loop = asyncio.get_running_loop()
        now = [loop.time()]
        monkeypatch.setattr(loop, "time", lambda: now[0])
        bridge = ClientToolBridgeService()
        request = await create(bridge, 600)
        owner = await bridge.claim_request(request.request_id, executor_id="owner", attempt_id="first")
        for _ in range(59):
            now[0] += 10
            assert await bridge.renew_claim(request.request_id, executor_id="owner", claim_id=owner.claim_id)
        now[0] += 11
        if operation == "claim":
            assert not (await bridge.claim_request(request.request_id, executor_id="owner")).acquired
        elif operation == "renew":
            assert not await bridge.renew_claim(request.request_id, executor_id="owner", claim_id=owner.claim_id)
        elif operation == "submit":
            assert not await bridge.submit_result(request.request_id, ClientToolResultPayload(ok=True),
                                                  executor_id="owner", claim_id=owner.claim_id)
        else:
            assert not await bridge.should_replay_request(request.request_id)
        # A late waiter/reconnect cannot start another 600-second budget.
        with pytest.raises(TimeoutError):
            await bridge.wait_for_result(request.request_id, timeout_seconds=600)
        assert not bridge._pending
    asyncio.run(run())


def test_waiter_uses_tool_budget_and_cleans_up_after_timeout():
    async def run():
        bridge = ClientToolBridgeService(lease_duration_seconds=0.001)
        request = await create(bridge, 0.05)
        waiter = asyncio.create_task(bridge.wait_for_result(request.request_id, timeout_seconds=1))
        await asyncio.sleep(0)
        assert not waiter.done()
        with pytest.raises(TimeoutError):
            await waiter
        assert not (await bridge.claim_request(request.request_id, executor_id="owner")).acquired
        assert not bridge._pending
    asyncio.run(run())


def test_claim_attempt_is_stable_across_lost_responses_and_new_attempts():
    async def run():
        bridge = ClientToolBridgeService()
        request = await create(bridge)
        first = await bridge.claim_request(request.request_id, executor_id="owner", attempt_id="attempt-1")
        retry = await bridge.claim_request(request.request_id, executor_id="owner", attempt_id="attempt-1")
        unknown = await bridge.claim_request(request.request_id, executor_id="owner", attempt_id="attempt-2")
        assert not first.resumed and retry.resumed and unknown.resumed
        assert first.claim_id == retry.claim_id == unknown.claim_id
        assert first.attempt_id == retry.attempt_id == unknown.attempt_id == "attempt-1"
        assert not (await bridge.claim_request(request.request_id, executor_id="other", attempt_id="attempt-1")).acquired
        assert await bridge.submit_result(request.request_id, ClientToolResultPayload(ok=True),
                                         executor_id="owner", claim_id=retry.claim_id)
        assert (await bridge.wait_for_result(request.request_id, timeout_seconds=600)).ok
    asyncio.run(run())


def test_cancelled_waiter_rejects_late_results():
    async def run():
        bridge = ClientToolBridgeService()
        request = await create(bridge)
        owner = await bridge.claim_request(request.request_id, executor_id="owner")
        waiter = asyncio.create_task(bridge.wait_for_result(request.request_id, timeout_seconds=600))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert not await bridge.submit_result(request.request_id, ClientToolResultPayload(ok=True),
                                              executor_id="owner", claim_id=owner.claim_id)
        assert not bridge._pending
    asyncio.run(run())


def test_claim_api_roundtrips_attempt_identity_and_owner_result(monkeypatch):
    from fastapi import FastAPI
    import httpx
    from app.api.routes.llm import client_tools

    async def run():
        bridge = ClientToolBridgeService()
        monkeypatch.setattr(client_tools, "get_client_tool_bridge_service", lambda: bridge)
        app = FastAPI()
        app.include_router(client_tools.router)
        request = await create(bridge)
        path = f"/llm/client-tools/{request.request_id}"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            payload = {"executor_id": "owner", "attempt_id": "same-attempt"}
            first = (await client.post(path + "/claim", json=payload)).json()
            retry = (await client.post(path + "/claim", json=payload)).json()
            assert first["acquired"] and not first["resumed"]
            assert retry["resumed"] and retry["attempt_id"] == "same-attempt"
            assert retry["claim_id"] == first["claim_id"]
            result = await client.post(path + "/result", json={"executor_id": "owner",
                "claim_id": retry["claim_id"], "ok": True, "content": {"done": True}})
            assert result.json() == {"accepted": True}
        assert (await bridge.wait_for_result(request.request_id, timeout_seconds=600)).ok
    asyncio.run(run())
