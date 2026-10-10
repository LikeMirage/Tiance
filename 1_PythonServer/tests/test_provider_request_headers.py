import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace

import httpx
import pytest

from app.core.errors import AppError
from app.domain.llm.chat import ChatCompletionRequest, ChatMessage, ChatMessageRole, ChatStreamEventKind
from app.domain.llm.provider_catalog import (
    AuthScheme, ProviderCatalogEntry, ProviderEndpointTemplate, ProviderProtocolFamily,
    default_model_discovery_strategy,
)
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.infra.llm import chat_remote_client, provider_remote_client, request_headers
from app.infra.llm.provider_capabilities import remote_client as capability_remote_client
from app.infra.llm.provider_profiles import registry
from app.repositories.llm.provider_adaptation_rules_repository import ProviderAdaptationRulesRepository
from app.repositories.llm.provider_file_store import ProviderFileStore, ProviderFileStoreError


@pytest.fixture
def rules_store(tmp_path, monkeypatch):
    store = ProviderFileStore(tmp_path / "providers")
    store.write_provider_file("provider-a", "provider.json", {
        "schemaVersion": 1, "id": "provider-a", "profileId": "generic",
    })
    store.write_provider_file("provider-a", "provider-rules.json", {
        "schemaVersion": 1,
        "request": {"headers": {
            "X-Test-Session": {"source": "session_id"},
            "User-Agent": {"source": "client_user_agent"},
            "X-Static": {"value": "configured"},
        }},
    })
    repository = ProviderAdaptationRulesRepository(store)
    monkeypatch.setattr(request_headers, "get_provider_adaptation_rules_repository", lambda: repository)
    monkeypatch.setattr(registry, "get_provider_adaptation_rules_repository", lambda: repository)
    monkeypatch.setattr(request_headers, "get_settings", lambda: SimpleNamespace(app_version="test-version"))
    monkeypatch.setattr(chat_remote_client, "get_http_timeout", lambda **_kwargs: httpx.Timeout(30))
    return store


def _provider(protocol=ProviderProtocolFamily.OPENAI_COMPATIBLE):
    auth = {
        ProviderProtocolFamily.ANTHROPIC_MESSAGES: AuthScheme.X_API_KEY,
        ProviderProtocolFamily.GEMINI_GENERATE_CONTENT: AuthScheme.X_GOOG_API_KEY,
    }.get(protocol, AuthScheme.BEARER_TOKEN)
    return ProviderCatalogEntry(
        provider_id="provider-a", display_name="Provider", profile_id="generic",
        protocol_family=protocol, generation_auth_schemes={protocol: auth},
        model_discovery_strategy=default_model_discovery_strategy(protocol),
        model_discovery_auth_scheme=auth,
        endpoints=ProviderEndpointTemplate(
            api_base_url="https://provider.invalid/v1", text_generation_url_template="",
            model_discovery_url="https://provider.invalid/v1/models",
        ),
    )


def _runtime(protocol=ProviderProtocolFamily.OPENAI_COMPATIBLE):
    url = "https://provider.invalid/v1/generate"
    if protocol == ProviderProtocolFamily.GEMINI_GENERATE_CONTENT:
        url = "https://provider.invalid/v1/models/{model}:{action}"
    return ProviderRuntimeConfig(
        provider_id="provider-a", display_name="Provider", api_base_url=url,
        model_discovery_url="https://provider.invalid/v1/models",
    )


def _request(session_id="conversation-1"):
    return ChatCompletionRequest(
        provider_id="provider-a", model_id="model-a", session_id=session_id,
        messages=(ChatMessage(role=ChatMessageRole.USER, content="test"),),
    )


def _complete_payload(protocol):
    if protocol == ProviderProtocolFamily.OPENAI_COMPATIBLE:
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}
    if protocol == ProviderProtocolFamily.OPENAI_RESPONSES:
        return {"id": "response-1", "status": "completed", "output": [{
            "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "ok"}],
        }]}
    if protocol == ProviderProtocolFamily.ANTHROPIC_MESSAGES:
        return {"type": "message", "content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"}
    return {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}


def _stream_payload(protocol):
    if protocol == ProviderProtocolFamily.OPENAI_COMPATIBLE:
        payloads = [{"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}]
    elif protocol == ProviderProtocolFamily.OPENAI_RESPONSES:
        payloads = [{"type": "response.completed", "response": _complete_payload(protocol)}]
    elif protocol == ProviderProtocolFamily.ANTHROPIC_MESSAGES:
        payloads = [
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ok"}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
            {"type": "message_stop"},
        ]
    else:
        payloads = [_complete_payload(protocol)]
    return ("".join(f"data: {json.dumps(payload)}\n\n" for payload in payloads) + "data: [DONE]\n\n").encode()


@pytest.mark.parametrize("protocol", list(ProviderProtocolFamily))
@pytest.mark.parametrize("stream", [False, True])
def test_all_chat_protocols_send_declared_headers_and_audit_actual_headers(rules_store, monkeypatch, protocol, stream):
    sent = []
    audits = []

    def respond(request):
        sent.append(request)
        if stream:
            return httpx.Response(200, content=_stream_payload(protocol), headers={"Content-Type": "text/event-stream"})
        return httpx.Response(200, json=_complete_payload(protocol))

    async def record(_request, exchange):
        audits.append(exchange)

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            monkeypatch.setattr(chat_remote_client, "get_shared_http_client", lambda: client)
            remote = chat_remote_client.ChatRemoteClient()
            kwargs = dict(provider_template=_provider(protocol), runtime_config=_runtime(protocol),
                          api_key="secret-key", request=_request(), on_exchange=record)
            if stream:
                events = [event async for event in remote.stream(**kwargs)]
                assert any(event.kind == ChatStreamEventKind.DONE for event in events)
                assert not any(event.kind == ChatStreamEventKind.ERROR for event in events)
            else:
                assert (await remote.complete(**kwargs)).message.content == "ok"

    asyncio.run(execute())
    assert len(sent) == len(audits) == 1
    headers = sent[0].headers
    assert headers["X-Test-Session"] == "conversation-1"
    assert headers["User-Agent"] == "Tiance/test-version"
    assert headers["X-Static"] == "configured"
    assert len([name for name, _value in headers.multi_items() if name == "user-agent"]) == 1
    auth_name = {ProviderProtocolFamily.ANTHROPIC_MESSAGES: "x-api-key",
                 ProviderProtocolFamily.GEMINI_GENERATE_CONTENT: "x-goog-api-key"}.get(protocol, "Authorization")
    assert "secret-key" in headers[auth_name]
    assert audits[0].request_headers["X-Test-Session"] == "conversation-1"
    assert audits[0].request_headers[auth_name] == "[REDACTED]"


@pytest.mark.parametrize("session_id", ["saved-session", None])
def test_retry_and_tool_round_keep_session_but_independent_conversation_changes_it(rules_store, monkeypatch, session_id):
    sessions = []

    def respond(request):
        sessions.append(request.headers["X-Test-Session"])
        return httpx.Response(200, json=_complete_payload(ProviderProtocolFamily.OPENAI_COMPATIBLE))

    initial = _request(session_id)
    retry = replace(initial, upstream_attempt_index=2, usage_request_id="new-attempt")
    tool_round = replace(retry, messages=initial.messages + (ChatMessage(role=ChatMessageRole.USER, content="tool result"),))
    another = _request("other-session" if session_id else None)

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            monkeypatch.setattr(chat_remote_client, "get_shared_http_client", lambda: client)
            remote = chat_remote_client.ChatRemoteClient()
            for request in (initial, retry, tool_round, another):
                await remote.complete(provider_template=_provider(), runtime_config=_runtime(), api_key="key", request=request)

    asyncio.run(execute())
    assert sessions[0] == sessions[1] == sessions[2]
    assert sessions[3] != sessions[0]
    assert initial.session_id == session_id


def test_headers_merge_by_case_insensitive_name_without_losing_inherited_headers(rules_store):
    rules_store.write_provider_file("provider-a", "models.json", {
        "schemaVersion": 1, "items": [{"modelId": "model-a", "familyGroup": "family-a"}],
    })
    rules_store.write_provider_file("provider-a", "model-rules.json", {
        "schemaVersion": 1,
        "families": {"family-a": {"request": {"headers": {
            "x-static": {"value": "family"}, "X-Family": {"value": "inherited"},
        }}}},
        "models": {"model-a": {"request": {"headers": {"X-STATIC": {"value": "exact"}}}}},
    })
    headers = request_headers.resolve_request_headers(_provider(), model_id="MODEL-A", session_id="s1")
    assert headers["X-STATIC"] == "exact"
    assert headers["X-Family"] == "inherited"
    assert headers["X-Test-Session"] == "s1"
    assert headers["User-Agent"] == "Tiance/test-version"
    assert len([name for name in headers if name.lower() == "x-static"]) == 1
    merged = request_headers.merge_request_headers({"user-agent": "sdk/1", "Authorization": "Bearer key"}, headers)
    assert "user-agent" not in merged
    assert merged["Authorization"] == "Bearer key"


@pytest.mark.parametrize("session_id", ["saved-session", None])
@pytest.mark.parametrize("stream", [False, True])
def test_service_http_retry_keeps_header_session(rules_store, monkeypatch, session_id, stream):
    from app.domain.llm.provider_config import ProviderConfig
    from app.domain.llm.token_estimation_settings import DEFAULT_TOKEN_ESTIMATION_SETTINGS
    from app.services.llm.chat.service import ChatCompletionService

    sent = []

    def respond(request):
        sent.append(request)
        if len(sent) == 1:
            return httpx.Response(500, json={"error": {"message": "retry"}})
        if stream:
            return httpx.Response(200, content=_stream_payload(ProviderProtocolFamily.OPENAI_COMPATIBLE),
                                  headers={"Content-Type": "text/event-stream"})
        return httpx.Response(200, json=_complete_payload(ProviderProtocolFamily.OPENAI_COMPATIBLE))

    config = ProviderConfig(provider_id="provider-a", api_base_url=_runtime().api_base_url,
                            enabled=True, api_keys=(), created_at="now", updated_at="now")

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            monkeypatch.setattr(chat_remote_client, "get_shared_http_client", lambda: client)
            service = ChatCompletionService(
                SimpleNamespace(get_entry=lambda _id: _provider()),
                SimpleNamespace(get_config=lambda _id: config),
                chat_remote_client.ChatRemoteClient(), SimpleNamespace(), SimpleNamespace(),
                SimpleNamespace(get_settings=lambda: DEFAULT_TOKEN_ESTIMATION_SETTINGS),
            )
            request = replace(_request(session_id), record_usage=False)
            if stream:
                events = [event async for event in service.stream(request)]
                assert events[-1].kind == ChatStreamEventKind.DONE
            else:
                assert (await service.complete(request)).message.content == "ok"

    asyncio.run(execute())
    assert len(sent) == 2
    assert sent[0].headers["X-Test-Session"] == sent[1].headers["X-Test-Session"]


@pytest.mark.parametrize("headers", [
    None, [],
    {"X-Test": "raw"}, {"X Test": {"value": "bad"}}, {"X-Test\n": {"value": "bad"}},
    {"X-Test": {}}, {"X-Test": {"value": "x", "source": "session_id"}},
    {"X-Test": {"value": None}}, {"X-Test": {"value": 1}}, {"X-Test": {"value": ""}},
    {"X-Test": {"value": "a\r\nb"}}, {"X-Test": {"value": "a\x00b"}}, {"X-Test": {"value": "中文"}},
    {"X-Test": {"source": "environment"}}, {"X-Test": {"source": None}},
    {"X-Test": {"source": "session_id", "execute": "hook"}},
    {"X-Test": {"value": "a"}, "x-test": {"value": "b"}},
    *[{name: {"value": "override"}} for name in (
        "Authorization", "proxy-authorization", "X-API-Key", "x-goog-api-key", "Cookie", "Host",
        "Content-Length", "Transfer-Encoding", "Connection", "Content-Type", "Accept",
    )],
])
def test_invalid_or_reserved_header_declarations_are_rejected(rules_store, headers):
    rules_store.write_provider_file("provider-a", "provider-rules.json", {
        "schemaVersion": 1, "request": {"headers": headers},
    })
    with pytest.raises(ProviderFileStoreError):
        request_headers.resolve_request_headers(_provider(), session_id="s1")


@pytest.mark.parametrize("session_id", ["", "s1\r\nInjected: value", "中文"])
def test_invalid_dynamic_value_fails_before_http(rules_store, session_id):
    with pytest.raises(AppError) as error:
        request_headers.resolve_request_headers(_provider(), session_id=session_id)
    assert error.value.code == "provider_request_header_value_invalid"


def test_old_rules_do_not_add_headers(rules_store):
    rules_store.write_provider_file("provider-a", "provider-rules.json", {"schemaVersion": 1, "request": {}})
    assert request_headers.resolve_request_headers(_provider(), session_id="s1") == {}


@pytest.mark.parametrize("protocol", list(ProviderProtocolFamily))
def test_discovery_and_model_probe_use_headers_with_separate_operation_sessions(rules_store, monkeypatch, protocol):
    sent = []

    def respond(request):
        sent.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "model-a"}], "models": [{"name": "models/model-a"}]})
        return httpx.Response(200, json={})

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            monkeypatch.setattr(provider_remote_client, "get_shared_http_client", lambda: client)
            remote = provider_remote_client.ProviderRemoteClient()
            assert len(await remote.discover_models(_provider(protocol), _runtime(protocol), "key")) == 1
            assert (await remote.check_model(_provider(protocol), _runtime(protocol), "key", "model-a"))["ok"] is True

    asyncio.run(execute())
    assert len(sent) == 2
    for request in sent:
        assert request.headers["User-Agent"] == "Tiance/test-version"
        assert request.headers["X-Test-Session"]
    assert sent[0].headers["X-Test-Session"] != sent[1].headers["X-Test-Session"]


def test_builtin_search_inherits_caller_session(rules_store, monkeypatch):
    sent = []

    def respond(request):
        sent.append(request)
        payload = _complete_payload(ProviderProtocolFamily.OPENAI_RESPONSES)
        payload["output"].insert(0, {"type": "web_search_call", "action": {"type": "search", "query": "test", "sources": []}})
        return httpx.Response(200, json=payload)

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            monkeypatch.setattr(capability_remote_client, "get_shared_http_client", lambda: client)
            remote = capability_remote_client.ProviderCapabilityRemoteClient()
            await remote.web_search(provider_template=_provider(ProviderProtocolFamily.OPENAI_RESPONSES),
                                    runtime_config=_runtime(), api_key="key", model_id="model-a",
                                    query="test", session_id="caller-session")

    asyncio.run(execute())
    assert sent[0].headers["X-Test-Session"] == "caller-session"


def test_opencode_package_declares_headers_without_changing_profile():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "Data" / "providers"
    rules = ProviderAdaptationRulesRepository(ProviderFileStore(root)).resolve(
        provider_id="opencode", model_id="deepseek-v4-flash", expected_profile_id="generic",
    )
    assert rules is not None
    assert {header.name: header.source for header in rules.request.headers} == {
        "x-opencode-session": "session_id", "User-Agent": "client_user_agent",
    }
