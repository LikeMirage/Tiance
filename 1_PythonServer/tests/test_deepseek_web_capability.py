from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from app.api.routes.llm import provider_capabilities as routes
from app.core.errors import AppError
from app.domain.llm.provider_config import ProviderApiKeyConfig, ProviderConfig
from app.infra.llm.provider_capabilities import deepseek_web as remote
from app.services.llm.provider import config_runtime
from app.services.llm.provider.api_key_scheduler import ProviderApiKeyScheduler
from app.services.llm.provider_capabilities.deepseek_web import DeepSeekWebService
from app.services.tools.host_capability_access import HostCapability, HostCapabilityAccessService


def key(name, weight=1):
    return ProviderApiKeyConfig(
        key_id=name, provider_id="deepseek", api_key_hint=None, poll_weight=weight,
        sort_order=0, created_at="now", updated_at="now", api_key_ciphertext=name,
    )


def service_fixture(monkeypatch, *, keys=None, enabled=True, missing=False):
    provider = SimpleNamespace(provider_id="deepseek", display_name="DeepSeek")
    config = ProviderConfig(
        provider_id="deepseek", api_base_url="https://model-only.invalid/v1/responses",
        enabled=enabled, api_keys=tuple(keys if keys is not None else [key("key-a"), key("key-b")]),
        created_at="now", updated_at="now",
    )
    monkeypatch.setattr(config_runtime, "resolve_api_key_secret", lambda item: item.api_key_ciphertext or "")
    calls = []
    async def request(**kwargs):
        calls.append(kwargs)
        return {"results": []}
    service = DeepSeekWebService(
        SimpleNamespace(get_entry=lambda ident: provider if ident == "deepseek" and not missing else None),
        SimpleNamespace(get_config=lambda ident: config if ident == "deepseek" and not missing else None),
        ProviderApiKeyScheduler(), request,
    )
    return service, calls


def grant(access, tool="deepseek_official_web_search", provider="unrelated-provider", model="other-model"):
    return access.issue_grant(
        capabilities=(HostCapability.WEB_SEARCH if tool == "network_search" else HostCapability.DEEPSEEK_WEB,), tool_name=tool, tool_call_id="call-1", provider_id=provider, model_id=model,
        project_id="project-1", session_id="session-1", lifetime_seconds=60,
    )


def test_independent_search_grant_does_not_require_a_chat_model():
    access = HostCapabilityAccessService()
    token = grant(access, provider=None, model=None)
    assert token is not None
    assert access.authorize(token.token, HostCapability.DEEPSEEK_WEB) == token
    assert access.authorize(token.token, HostCapability.WEB_SEARCH) is None
    access.revoke(token.token)
    assert access.authorize(token.token, HostCapability.DEEPSEEK_WEB) is None


def test_bridge_uses_only_deepseek_and_reuses_key_rotation(monkeypatch):
    service, calls = service_fixture(monkeypatch)
    for _ in range(3):
        assert asyncio.run(service.execute(action="search", payload={"query": "test"})) == {"results": []}
    assert [c["api_key"] for c in calls] == ["key-a", "key-b", "key-a"]
    assert all(set(c) == {"action", "payload", "api_key"} for c in calls)
    assert all(c["payload"] == {"query": "test"} for c in calls)


@pytest.mark.parametrize("options,code", [
    ({"missing": True}, "DEEPSEEK_KEY_MISSING"),
    ({"keys": []}, "DEEPSEEK_KEY_MISSING"),
    ({"keys": [key("disabled", 0)]}, "DEEPSEEK_KEY_MISSING"),
    ({"keys": [key("")]}, "DEEPSEEK_KEY_MISSING"),
    ({"enabled": False}, "DEEPSEEK_PROVIDER_DISABLED"),
])
def test_missing_disabled_or_unusable_credentials_do_not_request_upstream(monkeypatch, options, code):
    service, calls = service_fixture(monkeypatch, **options)
    with pytest.raises(AppError) as error:
        asyncio.run(service.execute(action="search", payload={"query": "test"}))
    assert error.value.code == code
    assert "模型集" in str(error.value) and "configure" in str(error.value)
    assert calls == []


@pytest.fixture
def client(monkeypatch):
    service, calls = service_fixture(monkeypatch)
    access = HostCapabilityAccessService()
    monkeypatch.setattr(routes, "get_host_capability_access_service", lambda: access)
    monkeypatch.setattr(routes, "get_deepseek_web_service", lambda: service)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        yield client, access, service, calls


def test_route_accepts_scoped_grant_without_exposing_credentials(client):
    http, access, service, calls = client
    token = grant(access)
    response = http.post("/llm/provider-capabilities/deepseek-web",
                         headers={"Authorization": f"Bearer {token.token}"},
                         json={"action": "search", "query": "query", "count": 2, "need_content": True})
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "data": {"results": []}}
    assert calls[0]["api_key"] == "key-a"
    assert calls[0]["payload"] == {"query": "query", "count": 2, "need_content": True, "localization": ""}
    assert "key-a" not in response.text


def test_route_rejects_foreign_missing_and_revoked_grants(client):
    http, access, _, calls = client
    foreign = grant(access, tool="network_search")
    own = grant(access)
    access.revoke(own.token)
    for token in ("", foreign.token, own.token):
        response = http.post("/llm/provider-capabilities/deepseek-web",
                             headers={"Authorization": f"Bearer {token}"},
                             json={"action": "fetch", "url": "https://example.com"})
        assert response.status_code == 401
    assert calls == []


@pytest.mark.parametrize("body", [
    {"action": "search", "query": "test", "provider_id": "other"},
    {"action": "search", "query": "test", "api_key": "override"},
    {"action": "search", "query": "test", "model": "override"},
    {"action": "search", "query": "test", "count": True},
    {"action": "search", "query": "test", "need_content": "true"},
    {"action": "search", "query": "中" * 129},
    {"action": "search", "query": " "},
    {"action": "fetch", "url": "https://user:pass@example.com"},
    {"action": "fetch", "url": "file:///test"},
    {"action": "fetch", "url": "https://[invalid"},
    {"action": "fetch", "url": "https://example.com", "query": "ignored"},
    {"action": "configure", "api_key": "new-key"},
])
def test_bridge_contract_rejects_credential_override_and_invalid_parameters(client, body):
    http, access, _, calls = client
    token = grant(access)
    response = http.post("/llm/provider-capabilities/deepseek-web",
                         headers={"Authorization": f"Bearer {token.token}"}, json=body)
    assert response.status_code == 422, response.text
    assert calls == []


def test_provider_failure_is_returned_as_structured_tool_error(client):
    http, access, service, _ = client
    async def fail(**kwargs):
        raise AppError("余额不足", code="DEEPSEEK_HTTP_ERROR", details={"http_status": 402})
    service._request = fail
    token = grant(access)
    response = http.post("/llm/provider-capabilities/deepseek-web",
                         headers={"Authorization": f"Bearer {token.token}"},
                         json={"action": "search", "query": "test"})
    assert response.json()["error_info"] == {
        "code": "DEEPSEEK_HTTP_ERROR", "message": "余额不足", "details": {"http_status": 402},
    }


def test_remote_client_uses_fixed_endpoint_and_does_not_follow_redirect(monkeypatch):
    seen = []
    async def exercise():
        def handler(request):
            seen.append(request)
            return httpx.Response(302, headers={"location": "https://not-deepseek.invalid"}, json={})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
            monkeypatch.setattr(remote, "get_shared_http_client", lambda: client)
            with pytest.raises(AppError) as error:
                await remote.request_deepseek_web(action="search", payload={"query": "test"}, api_key="private-key")
            assert error.value.details["http_status"] == 302
    asyncio.run(exercise())
    assert len(seen) == 1
    assert str(seen[0].url) == "https://api.deepseek.com/v1/tools/search"
    assert seen[0].headers["authorization"] == "Bearer private-key"
    assert seen[0].content == b'{"query":"test"}'


@pytest.mark.parametrize("status", [401, 402, 403, 404, 429, 500, 504])
def test_remote_error_preserves_status_but_redacts_key(monkeypatch, status):
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(status, json={"error": {"message": "private-key rejected"}})
        )) as client:
            monkeypatch.setattr(remote, "get_shared_http_client", lambda: client)
            with pytest.raises(AppError) as error:
                await remote.request_deepseek_web(action="fetch", payload={"url": "https://example.com"}, api_key="private-key")
            assert error.value.details["http_status"] == status
            assert "private-key" not in str(error.value)
    asyncio.run(exercise())


@pytest.mark.parametrize("response", [httpx.Response(200, text="bad JSON"), httpx.Response(200, json=[])])
def test_remote_invalid_response_fails_clearly(monkeypatch, response):
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
            monkeypatch.setattr(remote, "get_shared_http_client", lambda: client)
            with pytest.raises(AppError, match="JSON"):
                await remote.request_deepseek_web(action="search", payload={"query": "test"}, api_key="private-key")
    asyncio.run(exercise())
