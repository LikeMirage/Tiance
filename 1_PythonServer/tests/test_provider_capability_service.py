from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.domain.llm.chat import ChatUsage
from app.domain.llm.provider_capabilities import ProviderWebSearchResult
from app.domain.llm.provider_catalog import (
    AuthScheme,
    ProviderCatalogEntry,
    ProviderEndpointTemplate,
    ProviderProtocolFamily,
    default_model_discovery_strategy,
)
from app.domain.llm.provider_config import ProviderConfig
from app.schemas.llm.provider_capabilities import ProviderWebSearchRequestBody
from app.api.routes.llm.provider_capabilities import run_provider_web_search
from app.services.llm.provider_capabilities.service import ProviderCapabilityService
from app.services.tools.host_capability_access import (
    HostCapability,
    HostCapabilityGrant,
)


class FakeCatalogRepository:
    def __init__(self, entry):
        self.entry = entry

    def get_entry(self, provider_id):
        return self.entry if provider_id == self.entry.provider_id else None


class FakeConfigRepository:
    def __init__(self, config):
        self.config = config

    def get_config(self, provider_id):
        return self.config if provider_id == self.config.provider_id else None


class FakeApiKeyScheduler:
    def select_next(self, *_args):
        raise AssertionError("anonymous provider must not invoke API key rotation")


class FakeRemoteClient:
    def __init__(self):
        self.calls = []

    async def web_search(self, **kwargs):
        self.calls.append(kwargs)
        return ProviderWebSearchResult(
            provider_id=kwargs["provider_template"].provider_id,
            model_id=kwargs["model_id"],
            answer="answer",
            usage=ChatUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


class FakeUsageService:
    def __init__(self):
        self.records = []

    def record_message_usage(self, **kwargs):
        self.records.append(kwargs)


def _provider() -> ProviderCatalogEntry:
    return ProviderCatalogEntry(
        provider_id="provider-1",
        display_name="Provider",
        profile_id="generic",
        protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE,
        generation_auth_schemes={
            ProviderProtocolFamily.OPENAI_COMPATIBLE: AuthScheme.BEARER_TOKEN
        },
        model_discovery_strategy=default_model_discovery_strategy(
            ProviderProtocolFamily.OPENAI_COMPATIBLE
        ),
        model_discovery_auth_scheme=AuthScheme.BEARER_TOKEN,
        endpoints=ProviderEndpointTemplate(
            api_base_url="http://127.0.0.1:8317/v1",
            text_generation_url_template="",
            model_discovery_url=None,
        ),
    )


def _grant() -> HostCapabilityGrant:
    return HostCapabilityGrant(
        grant_id="grant-1",
        token="token",
        capability=HostCapability.WEB_SEARCH,
        tool_name="network_search",
        tool_call_id="call-1",
        provider_id="provider-1",
        model_id="model-1",
        project_id="project-1",
        session_id="session-1",
        expires_at=999999999.0,
    )


def test_provider_capability_service_uses_grant_context_and_records_separate_usage():
    provider = _provider()
    config = ProviderConfig(
        provider_id=provider.provider_id,
        api_base_url=provider.endpoints.api_base_url,
        enabled=True,
        api_keys=(),
        created_at="now",
        updated_at="now",
    )
    remote = FakeRemoteClient()
    usage = FakeUsageService()
    service = ProviderCapabilityService(
        FakeCatalogRepository(provider),
        FakeConfigRepository(config),
        remote,
        FakeApiKeyScheduler(),
        usage,
    )

    result = asyncio.run(
        service.web_search(grant=_grant(), query="latest information")
    )

    assert result.answer == "answer"
    assert len(remote.calls) == 1
    call = remote.calls[0]
    assert call["model_id"] == "model-1"
    assert call["query"] == "latest information"
    assert call["api_key"] == ""
    assert len(usage.records) == 1
    assert usage.records[0]["project_id"] == "project-1"
    assert usage.records[0]["session_id"] == "session-1"
    assert usage.records[0]["provider_id"] == "provider-1"
    assert usage.records[0]["model_id"] == "model-1"
    assert usage.records[0]["usage_feature_key"] == "provider_web_search"
    assert usage.records[0]["message_id"] == "provider_web_search:grant-1"


def test_provider_web_search_api_body_cannot_override_bound_context():
    assert set(ProviderWebSearchRequestBody.model_fields) == {"query"}


def test_provider_web_search_query_has_no_hidden_length_ceiling():
    query = "Q" * 50000

    payload = ProviderWebSearchRequestBody(query=query)

    assert payload.query == query


def test_provider_web_search_route_rejects_missing_scoped_grant():
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            run_provider_web_search(
                ProviderWebSearchRequestBody(query="test"),
                authorization=None,
            )
        )

    assert exc_info.value.status_code == 401
