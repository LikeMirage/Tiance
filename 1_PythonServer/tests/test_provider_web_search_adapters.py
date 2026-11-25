from copy import deepcopy
import runpy

import pytest

from tests.formal_tool_paths import resolve_formal_tool_root


@pytest.fixture
def execute(monkeypatch):
    program = resolve_formal_tool_root("network_search") / "program"
    monkeypatch.syspath_prepend(str(program))
    run = runpy.run_path(str(program / "main.py"))["run"]

    def invoke(protocol, respond, *, address=None, model="model-1", selected_protocol=None, endpoint=None):
        default_urls = {
            "openai_responses": "https://gateway.example/v1/responses",
            "anthropic_messages": "https://api.anthropic.com/v1/messages",
            "gemini_generate_content": "https://generativelanguage.googleapis.com/v1beta/models/{model}:{action}",
        }
        def capability(name, request, *, timeout_seconds):
            assert name == "session_model"
            if request == {"operation": "source"}:
                return {"provider_id": "provider-1", "model_id": model, "protocol_family": protocol,
                        "generation_url": address or default_urls[protocol]}
            assert request["protocol_family"] == (selected_protocol or protocol)
            if endpoint:
                assert request["endpoint"] == endpoint
            body = deepcopy(request["body"])
            if request["protocol_family"] != "gemini_generate_content":
                assert body["model"] == model
            payload = respond(body)
            usage = payload.get("usage", {})
            normalized = {"total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0)}
            return {"status": 200, "data": payload, "usage": normalized}

        monkeypatch.setitem(run.__globals__, "call_host_capability", capability)
        return run({"query": "latest information"})
    return invoke


def test_openai_responses_search_preserves_every_query_source_and_citation(execute):
    queries = [f"query-{index}" for index in range(150)]
    action_sources = [
        {"type": "url", "url": f"https://source.example/{index}", "title": f"S{index}"}
        for index in range(150)
    ]
    citations = [
        {"type": "url_citation", "url": f"https://citation.example/{index}", "title": f"C{index}"}
        for index in range(150)
    ]
    captured = {}

    def respond(body):
        captured["body"] = body
        return {
            "id": "resp-1",
            "status": "completed",
            "output": [
                {
                    "type": "web_search_call",
                    "id": "ws-1",
                    "status": "completed",
                    "action": {
                        "type": "search",
                        "queries": queries,
                        "sources": action_sources,
                    },
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Search answer",
                            "annotations": citations,
                        }
                    ],
                },
            ],
            "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
        }

    reply = execute("openai_responses", respond, address="https://api.openai.com/v1/responses")
    assert reply["ok"], reply
    result = reply["data"]

    assert captured["body"]["tools"] == [{"type": "web_search"}]
    assert captured["body"]["include"] == ["web_search_call.action.sources"]
    assert "latest information" in captured["body"]["input"]
    assert result["search_queries"] == tuple(queries)
    assert len(result["sources"]) == 300
    assert [source["url"] for source in result["sources"][:150]] == [
        source["url"] for source in action_sources
    ]
    assert result["provider_usage"] == {
        "input_tokens": 10,
        "output_tokens": 20,
        "total_tokens": 30,
    }


def test_openai_responses_search_fails_when_model_does_not_use_search(execute):
    def respond(body):
        return {
            "status": "completed",
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "No search"}]}
            ],
        }

    result = execute("openai_responses", respond)
    assert not result["ok"]
    assert result["error_info"]["code"] == "provider_web_search_not_used"


@pytest.mark.parametrize(("host", "model", "expected_tool", "endpoint"), [
    ("api.deepseek.com", "deepseek-flash", "deepseek_web_search", "deepseek"),
    ("api.deepseek.com:443", "deepseek-v4-flash", "deepseek_web_search", "deepseek"),
    ("API.DEEPSEEK.COM", "deepseek-v4-flash-vision-exp", "deepseek_web_search", "deepseek"),
    ("api.deepseek.com", "deepseek-v4-pro", "web_search", "deepseek"),
    ("api.deepseek.com.gateway.example", "deepseek-flash", "web_search", "responses_from_chat"),
    ("api.deepseek.com:8443", "deepseek-flash", "web_search", "responses_from_chat"),
])
def test_search_declaration_uses_session_address_and_model(execute, host, model, expected_tool, endpoint):
    def respond(body):
        assert body["tools"] == [{"type": expected_tool}]
        assert "tool_choice" not in body
        return {
            "output": [
                {"type": "web_search_call", "status": "completed", "kind": "search",
                 "action": {"type": "search", "queries": ["query"],
                            "sources": [{"type": "url", "url": "https://example.org", "title": "Official page"}]}},
                {"type": "message", "content": [{"type": "output_text", "text": "Found it"}]},
            ],
        }

    reply = execute("openai_compatible", respond, address=f"https://{host}/chat/completions", model=model,
                    selected_protocol="openai_responses", endpoint=endpoint)
    assert reply["ok"], reply
    assert reply["data"]["sources"][0]["title"] == "Official page"


def test_failed_search_item_with_assistant_text_does_not_count_as_search_success(execute):
    def respond(body):
        return {"status": "completed", "output": [
            {"type": "web_search_call", "status": "failed", "error": {"code": "unavailable"}},
            {"type": "message", "content": [{"type": "output_text", "text": "Search is unavailable"}]},
        ]}

    reply = execute("openai_responses", respond, address="https://api.deepseek.com/responses", model="deepseek-flash")
    assert not reply["ok"]
    assert reply["error_info"]["code"] == "provider_web_search_failed"
    assert "unavailable" in reply["error"]


def test_openai_responses_search_omits_openai_sources_include_for_volcengine_profile(execute):
    captured = {}

    def respond(body):
        captured.update(body)
        return {
            "status": "completed",
            "output": [
                {
                    "type": "web_search_call",
                    "action": {"type": "search", "queries": ["query"]},
                },
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "answer"}],
                },
            ],
        }

    reply = execute("openai_compatible", respond, address="https://ark.cn-beijing.volces.com/api/v3/chat/completions",
                    selected_protocol="openai_responses", endpoint="volcengine_beijing")
    assert reply["ok"], reply
    assert "include" not in captured


def test_gemini_search_preserves_all_grounding_metadata(execute):
    queries = [f"query-{index}" for index in range(140)]
    chunks = [
        {"web": {"uri": f"https://source.example/{index}", "title": f"S{index}"}}
        for index in range(140)
    ]
    supports = [
        {"segment": {"startIndex": index, "endIndex": index + 1}, "groundingChunkIndices": [index]}
        for index in range(140)
    ]
    captured = {}

    def respond(body):
        captured["body"] = body
        return {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Grounded answer"}]},
                    "finishReason": "STOP",
                    "groundingMetadata": {
                        "webSearchQueries": queries,
                        "groundingChunks": chunks,
                        "groundingSupports": supports,
                    },
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 11,
                "candidatesTokenCount": 22,
                "totalTokenCount": 33,
            },
        }

    reply = execute("gemini_generate_content", respond)
    assert reply["ok"], reply
    result = reply["data"]

    assert captured["body"]["tools"] == [{"googleSearch": {}}]
    assert result["search_queries"] == tuple(queries)
    assert len(result["sources"]) == 140
    assert len(result["actions"]) == 140
    assert result["provider_metadata"][0]["groundingChunks"] == chunks


def test_anthropic_search_continues_pause_turn_without_search_count_limit(execute):
    search_results = [
        {
            "type": "web_search_result",
            "url": f"https://source.example/{index}",
            "title": f"S{index}",
            "encrypted_content": f"encrypted-{index}",
        }
        for index in range(125)
    ]
    first_content = [
        {
            "type": "server_tool_use",
            "id": "search-1",
            "name": "web_search",
            "input": {"query": "actual query"},
        },
        {
            "type": "web_search_tool_result",
            "tool_use_id": "search-1",
            "content": search_results,
        },
    ]
    responses = [
        {
            "id": "msg-1",
            "stop_reason": "pause_turn",
            "content": first_content,
            "usage": {"input_tokens": 2, "output_tokens": 3},
        },
        {
            "id": "msg-2",
            "stop_reason": "end_turn",
            "content": [
                {
                    "type": "text",
                    "text": "Final answer",
                    "citations": [
                        {
                            "type": "web_search_result_location",
                            "url": "https://citation.example/final",
                            "title": "Final",
                            "cited_text": "evidence",
                        }
                    ],
                }
            ],
            "usage": {"input_tokens": 5, "output_tokens": 7},
        },
    ]
    bodies = []

    def respond(body):
        bodies.append(body)
        return responses[len(bodies) - 1]

    reply = execute("anthropic_messages", respond)
    assert reply["ok"], reply
    result = reply["data"]

    assert len(bodies) == 2
    assert bodies[0]["max_tokens"] == 4096
    assert "max_uses" not in bodies[0]["tools"][0]
    assert bodies[1]["messages"][1] == {"role": "assistant", "content": first_content}
    assert result["search_queries"] == ("actual query",)
    assert len(result["sources"]) == 126
    assert result["sources"][0]["metadata"]["encrypted_content"] == "encrypted-0"
    assert result["provider_usage"] == {
        "requests": [responses[0]["usage"], responses[1]["usage"]]
    }
    assert result["usage"] is not None
    assert result["usage"]["total_tokens"] == 17


def test_unsupported_protocol_never_issues_a_request(execute):
    result = execute("openai_compatible", lambda _: pytest.fail("unrecognized endpoint"),
                     address="https://other.example/nonstandard")
    assert not result["ok"] and result["error_info"]["code"] == "provider_search_endpoint_missing"


def test_shared_host_matches_longest_complete_source_path(monkeypatch):
    from urllib.parse import urlsplit
    monkeypatch.syspath_prepend(str(resolve_formal_tool_root("network_search") / "program"))
    from native_search.routing import _match_endpoint
    endpoints = {
        "host_default": {"url": "https://gateway.example/responses"},
        "team": {"url": "https://gateway.example/one/responses", "search": {"source_path_prefix": "/team"}},
        "team_special": {"url": "https://gateway.example/two/responses", "search": {"source_path_prefix": "/team/special"}},
    }
    for path, name in (("/team/special/chat/completions", "team_special"), ("/team", "team"), ("/teamwork", "host_default")):
        assert _match_endpoint(urlsplit("https://gateway.example" + path), endpoints) == name
