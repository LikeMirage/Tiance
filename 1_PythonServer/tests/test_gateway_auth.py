from fastapi import FastAPI, Request, WebSocket
from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.gateway_auth import GatewayAuthenticationMiddleware
from app.api.routes.llm import provider_capabilities
from app.services.tools.host_capability_access import HostCapabilityAccessService


def application(token="internal-test-token"):
    app = FastAPI()
    app.add_middleware(GatewayAuthenticationMiddleware, token=token)

    @app.get("/api/private")
    async def private(request: Request):
        return {"internal_header_visible": "x-tiance-gateway-token" in request.headers}

    @app.websocket("/api/socket")
    async def socket(ws: WebSocket):
        await ws.accept()
        await ws.send_text("accepted")
        await ws.close()

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    return app


def test_backend_rejects_direct_http_and_websocket_even_with_browser_cookie():
    client = TestClient(application())
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/private").status_code == 401
    assert client.get("/api/private", headers={"cookie": "tiance_access_session=anything", "x-forwarded-for": "127.0.0.1"}).status_code == 401
    assert client.get("/api/private", headers={"x-tiance-gateway-token": "wrong"}).status_code == 401
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/socket"):
            pass
    headers = {"x-tiance-gateway-token": "internal-test-token"}
    assert client.get("/api/private", headers=headers).json() == {"internal_header_visible": False}
    with client.websocket_connect("/api/socket", headers=headers) as ws:
        assert ws.receive_text() == "accepted"


def test_missing_configuration_fails_closed_and_duplicate_headers_are_rejected():
    assert TestClient(application("")).get("/api/private", headers={"x-tiance-gateway-token": ""}).status_code == 401
    client = TestClient(application())
    assert client.get("/api/private", headers=[("x-tiance-gateway-token", "internal-test-token"), ("x-tiance-gateway-token", "wrong")]).status_code == 401


def test_capability_bridge_keeps_its_own_scoped_authentication(monkeypatch):
    access = HostCapabilityAccessService()
    monkeypatch.setattr(provider_capabilities, "get_host_capability_access_service", lambda: access)
    calls = []

    class Service:
        async def execute(self, **kwargs):
            calls.append(kwargs)
            return {"results": []}

    monkeypatch.setattr(provider_capabilities, "get_deepseek_web_service", Service)
    app = application()
    app.include_router(provider_capabilities.router, prefix="/api")
    client = TestClient(app)
    path = "/api/llm/provider-capabilities/deepseek-web"
    body = {"action": "search", "query": "test"}
    assert client.post(path, json=body).status_code == 401
    grant = access.issue_grant(tool_name="deepseek_official_web_search", tool_call_id="call", provider_id=None, model_id=None, project_id=None, session_id=None, lifetime_seconds=60)
    assert grant is not None
    headers = {"authorization": "Bearer " + grant.token}
    assert client.post(path, json=body, headers=headers).status_code == 200
    assert len(calls) == 1
    assert client.get("/api/private", headers=headers).status_code == 401
    assert client.post("/api/github/sync/plans/create", json={}, headers=headers).status_code == 401
    access.revoke(grant.token)
    assert client.post(path, json=body, headers=headers).status_code == 401
