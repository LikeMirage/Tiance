import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from app.api.routes.llm import provider_capabilities as routes
from app.core.errors import register_exception_handlers
from app.domain.llm.provider_catalog import AuthScheme
from app.domain.tools.host_capabilities import declared_session_model_endpoints
from app.services.llm import tool_provider_requests as service
from app.services.tools.host_capability_access import HostCapabilityAccessService


@pytest.fixture
def model_host(monkeypatch):
    access = HostCapabilityAccessService()
    monkeypatch.setattr(routes, "get_host_capability_access_service", lambda: access)
    current = SimpleNamespace(protocol_family="openai_responses", auth_scheme=AuthScheme.BEARER_TOKEN,
                              provider_id="caller-provider", profile_id="generic")
    from app.domain.llm.provider_catalog import ProviderProtocolFamily
    current.protocol_family = ProviderProtocolFamily.OPENAI_RESPONSES
    config = SimpleNamespace(api_base_url="https://provider.example/v3/responses?version=one")
    def provider(provider_id):
        assert provider_id == "caller-provider"
        return current, config
    monkeypatch.setattr(service, "_provider", provider)
    key_calls = []
    def key(*args, **kwargs):
        key_calls.append(1)
        return "fake+key/secret"
    monkeypatch.setattr(service, "_key", key)
    monkeypatch.setattr(service, "resolve_provider_profile", lambda entry, model: SimpleNamespace(
        include_responses_web_search_sources=True))
    monkeypatch.setattr(service, "resolve_request_headers", lambda entry, **kwargs: {"X-Session": kwargs["session_id"]})
    seen, records = [], []
    def answer(req):
        seen.append(req)
        return httpx.Response(200, json={"usage":{"input_tokens":3, "output_tokens":2, "total_tokens":5}})
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    monkeypatch.setattr(service, "get_shared_http_client", lambda: upstream)
    monkeypatch.setattr(service, "get_llm_usage_service", lambda: SimpleNamespace(
        record_message_usage=lambda **record: records.append(record)))
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(routes.router)
    grant = access.issue_grant(tool_name="renamed", tool_call_id="call", provider_id="caller-provider",
                               model_id="background-model", session_id="background-chat", project_id="p",
                               capabilities=("session_model",), model_usage_feature="provider_web_search",
                               lifetime_seconds=30)
    with TestClient(app) as client:
        yield client, current, config, seen, records, grant, key_calls, access
    asyncio.run(upstream.aclose())


@pytest.mark.parametrize("scheme,header", [(AuthScheme.BEARER_TOKEN, "Authorization"),
    (AuthScheme.X_API_KEY, "x-api-key"), (AuthScheme.X_GOOG_API_KEY, "x-goog-api-key"), (AuthScheme.API_KEY_QUERY, None)])
def test_session_model_auth_context_and_usage(model_host, scheme, header):
    client, provider, _, seen, records, grant, key_calls, access = model_host
    provider.auth_scheme = scheme
    route = "/llm/provider-capabilities/session-model"
    auth = {"Authorization": "Bearer " + grant.token}
    source = client.post(route, headers=auth, json={"operation":"source"}).json()
    assert source["model_id"] == "background-model" and source["provider_id"] == "caller-provider"
    assert "secret" not in str(source)
    request = {"operation":"post", "protocol_family":"openai_responses",
               "body":{"model":"background-model","input":"Q"*10000}}
    for _ in range(2):
        reply = client.post(route, headers=auth, json=request)
        assert reply.status_code == 200 and reply.json()["usage"]["total_tokens"] == 5
    assert len(key_calls) == 1
    assert len(records) == 2 and records[0]["message_id"] != records[1]["message_id"]
    for req in seen:
        assert req.url.path == "/v3/responses" and req.url.params["version"] == "one"
        assert req.headers["X-Session"] == "background-chat"
        if header:
            assert "fake+key/secret" in req.headers[header]
        else:
            assert req.url.params["key"] == "fake+key/secret"
    assert records[0]["model_id"] == "background-model" and records[0]["usage_feature_key"] == "provider_web_search"
    assert client.post(route, headers=auth, json={**request,"body":{"model":"other"}}).status_code == 400
    assert client.post(route, headers=auth, json={**request,"provider_id":"other"}).status_code == 422
    access.revoke(grant.token)
    assert client.post(route, headers=auth, json=request).status_code == 401
    for path in ("web-search","deepseek-web"):
        assert client.post("/llm/provider-capabilities/" + path, json={}).status_code == 404


def test_gemini_uses_granted_model_in_generation_url(model_host):
    from app.domain.llm.provider_catalog import ProviderProtocolFamily
    client, provider, config, seen, _, grant, _, _ = model_host
    provider.protocol_family = ProviderProtocolFamily.GEMINI_GENERATE_CONTENT
    config.api_base_url = "https://provider.example/v1/models/{model}:{action}"
    response = client.post("/llm/provider-capabilities/session-model", headers={"Authorization": "Bearer "+grant.token},
                           json={"operation":"post","protocol_family":"gemini_generate_content","body":{"contents":[]}})
    assert response.status_code == 200
    assert seen[0].url.path == "/v1/models/background-model:generateContent"


def test_named_model_endpoints_are_scoped_to_session_origin_and_protocol(model_host):
    client, _, config, seen, _, _, key_calls, access = model_host
    config.api_base_url = "https://provider.example/team/v3/responses?api-version=one"
    runtime = {"host_capabilities": ["session_model"], "session_model_endpoints": {
        "same": {"protocol": "openai_responses", "url": "responses"},
        "different": {"protocol": "openai_responses", "url": "https://other.example/responses"},
    }}
    grant = access.issue_grant(tool_name="test", tool_call_id="diagnostic", project_id=None, session_id=None,
                               provider_id="caller-provider", model_id="bound", lifetime_seconds=30,
                               capabilities=("session_model",), session_model_endpoints=declared_session_model_endpoints(runtime))
    route = "/llm/provider-capabilities/session-model"
    auth = {"Authorization": "Bearer " + grant.token}
    source = client.post(route, headers=auth, json={"operation":"source"}).json()
    assert source["generation_url"] == "https://provider.example/team/v3/responses"
    request = {"operation":"post", "protocol_family":"openai_responses", "body":{"model":"bound"}}
    for extra in ({"endpoint":"different"}, {"endpoint":"unknown"}, {"endpoint":"same","protocol_family":"anthropic_messages"}):
        assert client.post(route, headers=auth, json={**request, **extra}).status_code == 403
    assert not seen and not key_calls
    assert client.post(route, headers=auth, json={**request, "endpoint":"same"}).status_code == 200
    assert str(seen[0].url) == config.api_base_url
