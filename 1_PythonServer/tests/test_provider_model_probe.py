import asyncio
from urllib.parse import parse_qsl, urlsplit

import pytest

from app.domain.llm.provider_catalog import (
    AuthScheme,
    ProviderCatalogEntry,
    ProviderEndpointTemplate,
    ProviderProtocolFamily,
    default_model_discovery_strategy,
)
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.infra.llm.provider_model_probe_client import ProviderModelProbeClient, _redact_url


@pytest.mark.parametrize("protocol", list(ProviderProtocolFamily))
def test_probe_redacts_query_key_without_changing_upstream_auth(protocol):
    secret = "test-secret+/=&中文"
    url = "https://provider.invalid/v1/models/{model}:{action}?region=cn"
    provider = ProviderCatalogEntry(
        provider_id="test", display_name="Test", profile_id="generic",
        protocol_family=protocol,
        generation_auth_schemes={protocol: AuthScheme.API_KEY_QUERY},
        model_discovery_strategy=default_model_discovery_strategy(protocol),
        model_discovery_auth_scheme=AuthScheme.API_KEY_QUERY,
        endpoints=ProviderEndpointTemplate(
            api_base_url=url, text_generation_url_template=url,
            model_discovery_url=None,
        ),
    )
    captured = {}

    async def post_json(request_url, headers, body):
        captured["url"] = request_url
        return {}

    result = asyncio.run(ProviderModelProbeClient().probe_model(
        provider,
        ProviderRuntimeConfig(provider_id="test", display_name="Test", api_base_url=url),
        secret, "test-model", post_json,
    ))

    sent = urlsplit(captured["url"])
    returned = urlsplit(result["checked_url"])
    assert dict(parse_qsl(sent.query)) == {"region": "cn", "key": secret}
    assert dict(parse_qsl(returned.query)) == {"region": "cn", "key": "[REDACTED]"}
    assert (returned.scheme, returned.netloc, returned.path) == (sent.scheme, sent.netloc, sent.path)
    assert result["ok"] is True
    assert result["model_id"] == "test-model"


@pytest.mark.parametrize("query,expected", [
    ("key=first&key=second", [("key", "[REDACTED]"), ("key", "[REDACTED]")]),
    ("KEY=secret&%6bey=encoded", [("KEY", "[REDACTED]"), ("key", "[REDACTED]")]),
    ("api_key=one&access_token=two&token=three", [
        ("api_key", "[REDACTED]"), ("access_token", "[REDACTED]"), ("token", "[REDACTED]"),
    ]),
    ("region=cn&empty=&tag=a&tag=b", [("region", "cn"), ("empty", ""), ("tag", "a"), ("tag", "b")]),
])
def test_probe_url_redacts_all_sensitive_values_and_preserves_other_parameters(query, expected):
    result = urlsplit(_redact_url(f"https://provider.invalid/v1/check?{query}#section"))
    assert parse_qsl(result.query, keep_blank_values=True) == expected
    assert result.fragment == "section"


def test_probe_url_omits_embedded_credentials():
    result = urlsplit(_redact_url("https://test-user:test-password@provider.invalid:8443/v1/check"))
    assert result.netloc == "provider.invalid:8443"
    assert result.path == "/v1/check"
