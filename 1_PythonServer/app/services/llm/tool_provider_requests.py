"""Bound model metadata and credentialed JSON transport for authorized tools."""
from __future__ import annotations

import asyncio
from dataclasses import asdict, fields, replace
import json
import logging
from urllib.parse import quote, quote_plus, urljoin, urlsplit
from uuid import uuid4

import httpx

from app.core.errors import AppError
from app.domain.llm.provider_adaptation import LlmProtocolBehaviorRules
from app.domain.llm.provider_catalog import ProviderProtocolFamily
from app.infra.http_client import get_shared_http_client, lease_http_client
from app.infra.llm.anthropic_auth import build_anthropic_request_headers
from app.infra.llm.chat_adapters.anthropic import _parse_anthropic_usage
from app.infra.llm.chat_adapters.gemini import _parse_gemini_usage
from app.infra.llm.chat_adapters.openai_responses_parsing import _parse_responses_usage
from app.infra.llm.provider_profiles import resolve_provider_profile
from app.infra.llm.request_auth import apply_auth_to_url, build_auth_headers
from app.infra.llm.request_headers import merge_request_headers, resolve_request_headers
from app.infra.llm.url_utils import render_generation_url
from app.repositories.llm.provider_catalog_repository import get_provider_catalog_repository
from app.repositories.llm.provider_config_repository import get_provider_config_repository
from app.services.llm.provider.api_key_scheduler import get_provider_api_key_scheduler
from app.services.llm.provider.config_runtime import ProviderConfigRuntimeResolver
from app.services.llm.usage import get_llm_usage_service
from app.services.tools.host_capability_access import HostCapabilityGrant

logger = logging.getLogger(__name__)


def _provider(provider_id):
    entry = get_provider_catalog_repository().get_entry(provider_id)
    config = get_provider_config_repository().get_config(provider_id)
    if entry is None or config is None or not config.enabled:
        raise AppError("供应商未配置或未启用。", code="provider_unavailable")
    return entry, config


def _key(entry, config, *, required):
    credentials = ProviderConfigRuntimeResolver(get_provider_api_key_scheduler()).resolve_runtime_credentials(entry, config)
    if credentials is None or (required and not credentials[1].api_key):
        raise AppError("模型集中没有可用的供应商 API Key。", code="provider_key_missing")
    return credentials[1].api_key


def model_source(grant: HostCapabilityGrant) -> dict:
    entry, config = grant.bindings.resolve("model", lambda: _provider(grant.provider_id))
    profile = resolve_provider_profile(entry, grant.model_id)
    address = urlsplit(config.api_base_url)
    return {
        "provider_id": entry.provider_id, "model_id": grant.model_id,
        "protocol_family": entry.protocol_family.value, "profile_id": entry.profile_id,
        "generation_url": address._replace(netloc=address.netloc.rsplit("@", 1)[-1], query="", fragment="").geturl(),
        "protocol_options": {field.name: getattr(profile, field.name)
                             for field in fields(LlmProtocolBehaviorRules) if hasattr(profile, field.name)},
    }


async def _post(url, scheme, key, headers, body):
    # Credentials are attached only after the trusted destination has been selected.
    try:
        async with asyncio.timeout(150), lease_http_client(get_shared_http_client()) as client:
            response = await client.post(apply_auth_to_url(url, scheme, key), headers=headers,
                                         json=body, timeout=httpx.Timeout(120, connect=15), follow_redirects=False)
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise AppError("供应商请求超时。", code="provider_timeout") from exc
    except httpx.RequestError as exc:
        raise AppError("无法连接供应商。", code="provider_connection_failed") from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise AppError(f"供应商返回无效 JSON（HTTP {response.status_code}）。", code="upstream_response_invalid_json") from exc
    if not isinstance(data, dict):
        raise AppError("供应商响应须为 JSON 对象。", code="upstream_response_invalid_shape")
    if key:
        # Avoid exposing reflected authentication in upstream error messages or echoed URLs.
        secrets = {key, quote(key, safe=""), quote_plus(key)}
        serialized = json.dumps(data, ensure_ascii=False)
        if any(json.dumps(secret, ensure_ascii=False)[1:-1] in serialized for secret in secrets):
            data = _redact(data, secrets)
    return {"status": response.status_code, "data": data}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
    elif isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    elif isinstance(value, dict):
        return {_redact(name, secrets): _redact(item, secrets) for name, item in value.items()}
    return value


def _origin(url: str):
    parsed = httpx.URL(url)
    return parsed.scheme, parsed.raw_host, parsed.port


async def post_to_endpoint(grant: HostCapabilityGrant, name: str, body: dict):
    endpoint = next((item for item in grant.provider_endpoints if item.name == name), None)
    if endpoint is None:
        raise AppError("本次工具调用未获授权使用该供应商接口。", status_code=403)
    url = endpoint.url
    entry, config = _provider(endpoint.provider_id)
    endpoints = entry.endpoints
    configured_urls = (config.api_base_url, endpoints.model_discovery_url, *endpoints.generation_urls.values())
    if not any(_origin(url) == _origin(known) for known in configured_urls if known):
        raise AppError("接口与凭据配置的供应商地址不同源。", status_code=403)
    key = _key(entry, config, required=True)
    scheme = endpoint.auth_scheme or entry.auth_scheme
    return await _post(url, scheme, key, build_auth_headers(scheme, key), body)


def _model_request_url(grant, endpoint, protocol, entry, config):
    if endpoint is None:
        if protocol != entry.protocol_family:
            raise AppError("跨协议调用需要指定工具声明的端点。")
        return config.api_base_url
    declaration = next((item for item in grant.session_model_endpoints if item.name == endpoint), None)
    if declaration is None or declaration.protocol != protocol:
        raise AppError("该端点或协议未获本次工具调用授权。", status_code=403)
    source = urlsplit(config.api_base_url)
    base = source._replace(path=source.path.rstrip("/"), query="", fragment="").geturl()
    url = urljoin(base, declaration.url)
    if not source.hostname or _origin(url) != _origin(config.api_base_url):
        raise AppError("工具声明的端点与调用会话的生成地址不同源。", status_code=403)
    # Relative routes keep deployment parameters such as api-version within the same origin.
    if not urlsplit(declaration.url).scheme and source.query:
        url = urlsplit(url)._replace(query=source.query).geturl()
    return url


async def post_to_model(grant, protocol: ProviderProtocolFamily, body, *, endpoint=None):
    entry, config = grant.bindings.resolve("model", lambda: _provider(grant.provider_id))
    url = _model_request_url(grant, endpoint, protocol, entry, config)
    if protocol != entry.protocol_family:
        entry = replace(entry, protocol_family=protocol)
    if protocol == ProviderProtocolFamily.GEMINI_GENERATE_CONTENT:
        url = render_generation_url(url, model_id=grant.model_id, action="generateContent")
        if "model" in body:
            raise AppError("模型由当前会话授权绑定。")
    else:
        if body.get("model") != grant.model_id:
            raise AppError("模型由当前会话授权绑定。")
    key = grant.bindings.resolve("model_key", lambda: _key(entry, config, required=False))
    headers = (build_anthropic_request_headers(entry.auth_scheme, key, stream=False)
               if protocol == ProviderProtocolFamily.ANTHROPIC_MESSAGES else build_auth_headers(entry.auth_scheme, key))
    declared = resolve_request_headers(entry, model_id=grant.model_id, session_id=grant.session_id or grant.grant_id)
    reply = await _post(url, entry.auth_scheme, key, merge_request_headers(headers, declared), body)
    usage = None
    if 200 <= reply["status"] < 300:
        data = reply["data"]
        if protocol == ProviderProtocolFamily.OPENAI_RESPONSES:
            usage = _parse_responses_usage(data.get("usage"))
        elif protocol == ProviderProtocolFamily.ANTHROPIC_MESSAGES:
            usage = _parse_anthropic_usage(data.get("usage"))
        elif protocol == ProviderProtocolFamily.GEMINI_GENERATE_CONTENT:
            usage = _parse_gemini_usage(data.get("usageMetadata"))
        elif protocol == ProviderProtocolFamily.OPENAI_COMPATIBLE:
            usage = resolve_provider_profile(entry, grant.model_id).parse_usage(data.get("usage"))
    if usage is not None:
        try:
            get_llm_usage_service().record_message_usage(
                project_id=grant.project_id, session_id=grant.session_id,
                provider_id=grant.provider_id, model_id=grant.model_id, usage=usage,
                message_id=f"tool:{grant.grant_id}:{uuid4().hex}", usage_feature_key=grant.model_usage_feature,
            )
        except Exception:
            logger.exception("Could not record tool model request usage")
    return {**reply, "usage": asdict(usage) if usage else None}
