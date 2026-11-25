"""A tool owns the operation. The host can only use the granted provider and destination."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.core.errors import AppError
from app.domain.llm.provider_catalog import AuthScheme
from app.domain.llm.provider_config import ProviderApiKeyConfig, ProviderConfig
from app.domain.tools.host_capabilities import declared_provider_endpoints
from app.services.llm import tool_provider_requests as service
from app.services.llm.provider import config_runtime
from app.services.llm.provider.api_key_scheduler import ProviderApiKeyScheduler
from app.services.tools.host_capability_access import HostCapabilityAccessService


URL = "https://api.deepseek.com/v1/tools/search"


def make_key(name, weight=1):
    return ProviderApiKeyConfig(key_id=name, provider_id="deepseek", api_key_hint=None,
        poll_weight=weight, sort_order=0, created_at="now", updated_at="now", api_key_ciphertext=name)


@pytest.fixture
def endpoint(monkeypatch):
    provider = SimpleNamespace(provider_id="deepseek", display_name="DeepSeek", auth_scheme=AuthScheme.X_API_KEY,
        endpoints=SimpleNamespace(generation_urls={}, model_discovery_url="https://api.deepseek.com/v1/models"))
    config = ProviderConfig(provider_id="deepseek", api_base_url="https://chat.example/v1/responses",
        enabled=True, api_keys=(make_key("first-secret"),make_key("second-secret")), created_at="now", updated_at="now")
    catalog = {"deepseek": provider}
    configs = {"deepseek": config}
    monkeypatch.setattr(service, "get_provider_catalog_repository", lambda: SimpleNamespace(get_entry=catalog.get))
    monkeypatch.setattr(service, "get_provider_config_repository", lambda: SimpleNamespace(get_config=configs.get))
    scheduler = ProviderApiKeyScheduler()
    monkeypatch.setattr(service, "get_provider_api_key_scheduler", lambda: scheduler)
    monkeypatch.setattr(config_runtime, "resolve_api_key_secret", lambda item: item.api_key_ciphertext or "")
    declared = declared_provider_endpoints({"host_capabilities":["provider_auth"],"provider_endpoints":{"lookup":
        {"provider_id":"deepseek","url":URL,"auth_scheme":"bearer_token"}}})
    grant = HostCapabilityAccessService().issue_grant(tool_name="custom", tool_call_id="one", provider_id=None,
        model_id=None, project_id=None, session_id=None, capabilities=("provider_auth",),
        provider_endpoints=declared, lifetime_seconds=60)
    assert grant
    return grant, configs, config, catalog


def test_named_endpoint_uses_only_declared_url_and_provider_and_rotates_keys(endpoint, monkeypatch):
    grant, _, _, _ = endpoint
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"results":[]})
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as upstream:
            monkeypatch.setattr(service,"get_shared_http_client",lambda:upstream)
            for _ in range(3):
                assert (await service.post_to_endpoint(grant, "lookup", {"new_field":123}))["data"] == {"results":[]}
            for ungranted in ("other", URL+"/different"):
                with pytest.raises(AppError):
                    await service.post_to_endpoint(grant, ungranted, {})
    asyncio.run(check())
    assert [req.headers["Authorization"] for req in seen] == ["Bearer first-secret","Bearer second-secret","Bearer first-secret"]
    assert all(str(req.url) == URL and b"new_field" in req.content for req in seen)


@pytest.mark.parametrize("failure", ["missing","disabled","empty","weight","foreign-origin"])
def test_no_upstream_request_without_trusted_credential(endpoint, failure, monkeypatch):
    from dataclasses import replace
    grant, configs, config, catalog = endpoint
    if failure == "missing":
        catalog.clear()
    elif failure == "foreign-origin":
        catalog["deepseek"].endpoints.model_discovery_url = None
    else:
        configs["deepseek"] = replace(config, enabled=failure != "disabled",
            api_keys=(make_key("disabled",0),) if failure=="weight" else ())
    monkeypatch.setattr(service,"get_shared_http_client",lambda:pytest.fail("no outbound request allowed"))
    with pytest.raises(AppError):
        asyncio.run(service.post_to_endpoint(grant,"lookup",{}))


@pytest.mark.parametrize("status", [302,401,402,429,500])
def test_no_redirect_or_key_reflection(endpoint, monkeypatch, status):
    grant, _, _, _ = endpoint
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(status, headers={"Location":"https://foreign.example/"},
                              json={"error":{"message":request.headers["Authorization"]}})
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond), follow_redirects=True) as upstream:
            monkeypatch.setattr(service,"get_shared_http_client",lambda:upstream)
            return await service.post_to_endpoint(grant, "lookup",{})
    reply = asyncio.run(check())
    assert reply["status"] == status and "first-secret" not in str(reply)
    assert len(seen) == 1


@pytest.mark.parametrize("payload,code", [(b"broken","upstream_response_invalid_json"),(b"[]","upstream_response_invalid_shape")])
def test_invalid_upstream_response(endpoint,monkeypatch,payload,code):
    grant, _, _, _ = endpoint
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,content=payload))) as client:
            monkeypatch.setattr(service,"get_shared_http_client",lambda:client)
            with pytest.raises(AppError) as exc:
                await service.post_to_endpoint(grant,"lookup",{})
            assert exc.value.code == code
    asyncio.run(check())
