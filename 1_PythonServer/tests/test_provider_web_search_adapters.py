from __future__ import annotations

import asyncio

import pytest

from app.core.errors import BadRequestError, UpstreamProviderError
from app.domain.llm.provider_catalog import (
    AuthScheme,
    ProviderCatalogEntry,
    ProviderEndpointTemplate,
    ProviderProtocolFamily,
    default_model_discovery_strategy,
)
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.infra.llm.provider_capabilities.anthropic import (
    ANTHROPIC_WEB_SEARCH_MAX_OUTPUT_TOKENS,
    AnthropicWebSearchAdapter,
)
from app.infra.llm.provider_capabilities.gemini import GeminiWebSearchAdapter
from app.infra.llm.provider_capabilities.openai_responses import (
    OpenAIResponsesWebSearchAdapter,
)
from app.infra.llm.provider_capabilities.remote_client import (
    ProviderCapabilityRemoteClient,
)


def _provider(
    protocol_family: ProviderProtocolFamily,
    *,
    profile_id: str = "generic",
) -> ProviderCatalogEntry:
    return ProviderCatalogEntry(
        provider_id="provider-1",
        display_name="Provider",
        profile_id=profile_id,
        protocol_family=protocol_family,
        generation_auth_schemes={protocol_family: AuthScheme.BEARER_TOKEN},
        model_discovery_strategy=default_model_discovery_strategy(protocol_family),
        model_discovery_auth_scheme=AuthScheme.BEARER_TOKEN,
        endpoints=ProviderEndpointTemplate(
            api_base_url="https://provider.example/v1",
            text_generation_url_template="",
            model_discovery_url=None,
        ),
    )


def _runtime(
    api_base_url: str = "https://provider.example/v1",
) -> ProviderRuntimeConfig:
    return ProviderRuntimeConfig(
        provider_id="provider-1",
        display_name="Provider",
        api_base_url=api_base_url,
    )


def test_openai_responses_search_preserves_every_query_source_and_citation():
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

    async def post_json(url, headers, body):
        captured.update(url=url, headers=headers, body=body)
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

    result = asyncio.run(
        OpenAIResponsesWebSearchAdapter().search(
            provider_template=_provider(
                ProviderProtocolFamily.OPENAI_RESPONSES,
                profile_id="openai",
            ),
            runtime_config=_runtime("https://provider.example/v1/responses"),
            api_key="key",
            model_id="model-1",
            query="latest information",
            post_json=post_json,
        )
    )

    assert captured["url"] == "https://provider.example/v1/responses"
    assert captured["body"]["tools"] == [{"type": "web_search"}]
    assert captured["body"]["include"] == ["web_search_call.action.sources"]
    assert "latest information" in captured["body"]["input"]
    assert result.search_queries == tuple(queries)
    assert len(result.sources) == 300
    assert [source.url for source in result.sources[:150]] == [
        source["url"] for source in action_sources
    ]
    assert result.provider_usage == {
        "input_tokens": 10,
        "output_tokens": 20,
        "total_tokens": 30,
    }


def test_openai_responses_search_fails_when_model_does_not_use_search():
    async def post_json(_url, _headers, _body):
        return {
            "status": "completed",
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "No search"}]}
            ],
        }

    with pytest.raises(UpstreamProviderError) as exc_info:
        asyncio.run(
            OpenAIResponsesWebSearchAdapter().search(
                provider_template=_provider(ProviderProtocolFamily.OPENAI_RESPONSES),
                runtime_config=_runtime("https://provider.example/v1/responses"),
                api_key="key",
                model_id="model-1",
                query="test",
                post_json=post_json,
            )
        )

    assert exc_info.value.code == "provider_web_search_not_used"


def test_openai_responses_search_keeps_volcengine_api_v3_base_path():
    captured = {}

    async def post_json(url, _headers, body):
        captured.update(url=url, body=body)
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

    asyncio.run(
        OpenAIResponsesWebSearchAdapter().search(
            provider_template=_provider(ProviderProtocolFamily.OPENAI_COMPATIBLE),
            runtime_config=_runtime(
                "https://ark.cn-beijing.volces.com/api/v3/responses"
            ),
            api_key="key",
            model_id="doubao-seed-2-0-pro",
            query="latest information",
            post_json=post_json,
        )
    )

    assert captured["url"] == "https://ark.cn-beijing.volces.com/api/v3/responses"
    assert "include" not in captured["body"]


def test_openai_responses_search_omits_openai_sources_include_for_volcengine_profile():
    captured = {}

    async def post_json(_url, _headers, body):
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

    asyncio.run(
        OpenAIResponsesWebSearchAdapter().search(
            provider_template=_provider(
                ProviderProtocolFamily.OPENAI_RESPONSES,
                profile_id="volcengine",
            ),
            runtime_config=_runtime(
                "https://ark.cn-beijing.volces.com/api/v3/responses"
            ),
            api_key="key",
            model_id="doubao-seed-2-0-pro",
            query="latest information",
            post_json=post_json,
        )
    )

    assert "include" not in captured


@pytest.mark.parametrize(
    ("response_payload", "expected_code"),
    [
        (ValueError("invalid json"), "upstream_response_invalid_json"),
        (["unexpected"], "upstream_response_invalid_shape"),
    ],
)
def test_provider_capability_remote_client_rejects_invalid_response_shape(
    monkeypatch,
    response_payload,
    expected_code,
):
    class FakeResponse:
        content = b"response"

        def raise_for_status(self):
            return None

        def json(self):
            if isinstance(response_payload, Exception):
                raise response_payload
            return response_payload

    class FakeHttpClient:
        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(
        "app.infra.llm.provider_capabilities.remote_client.get_shared_http_client",
        lambda: FakeHttpClient(),
    )

    with pytest.raises(UpstreamProviderError) as exc_info:
        asyncio.run(
            ProviderCapabilityRemoteClient()._post_json(
                "https://provider.example/responses",
                {},
                {},
            )
        )

    assert exc_info.value.code == expected_code


def test_provider_capability_remote_client_rejects_openai_compatible_search():
    with pytest.raises(BadRequestError, match="尚未适配内置网络搜索"):
        asyncio.run(
            ProviderCapabilityRemoteClient().web_search(
                provider_template=_provider(ProviderProtocolFamily.OPENAI_COMPATIBLE),
                runtime_config=_runtime("https://provider.example/v1/chat/completions"),
                api_key="key",
                model_id="model-1",
                query="latest information",
            )
        )


def test_gemini_search_preserves_all_grounding_metadata():
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

    async def post_json(url, headers, body):
        captured.update(url=url, headers=headers, body=body)
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

    result = asyncio.run(
        GeminiWebSearchAdapter().search(
            provider_template=_provider(ProviderProtocolFamily.GEMINI_GENERATE_CONTENT),
            runtime_config=_runtime(
                "https://generativelanguage.googleapis.com/"
                "v1beta/models/{model}:{action}"
            ),
            api_key="key",
            model_id="gemini-test",
            query="latest information",
            post_json=post_json,
        )
    )

    assert captured["url"].endswith("/models/gemini-test:generateContent")
    assert captured["body"]["tools"] == [{"googleSearch": {}}]
    assert result.search_queries == tuple(queries)
    assert len(result.sources) == 140
    assert len(result.actions) == 140
    assert result.provider_metadata[0]["groundingChunks"] == chunks


def test_anthropic_search_continues_pause_turn_without_search_count_limit():
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

    async def post_json(_url, _headers, body):
        bodies.append(body)
        return responses[len(bodies) - 1]

    result = asyncio.run(
        AnthropicWebSearchAdapter().search(
            provider_template=_provider(ProviderProtocolFamily.ANTHROPIC_MESSAGES),
            runtime_config=_runtime("https://provider.example/v1/messages"),
            api_key="key",
            model_id="claude-test",
            query="latest information",
            post_json=post_json,
        )
    )

    assert len(bodies) == 2
    assert bodies[0]["max_tokens"] == ANTHROPIC_WEB_SEARCH_MAX_OUTPUT_TOKENS
    assert "max_uses" not in bodies[0]["tools"][0]
    assert bodies[1]["messages"][1] == {"role": "assistant", "content": first_content}
    assert result.search_queries == ("actual query",)
    assert len(result.sources) == 126
    assert result.sources[0].metadata["encrypted_content"] == "encrypted-0"
    assert result.provider_usage == {
        "requests": [responses[0]["usage"], responses[1]["usage"]]
    }
    assert result.usage is not None
    assert result.usage.total_tokens == 17
