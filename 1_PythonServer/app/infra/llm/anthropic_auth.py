from __future__ import annotations

from app.domain.llm.provider_catalog import AuthScheme
from app.infra.llm.request_auth import build_auth_headers


def build_anthropic_auth_headers(
    auth_scheme: AuthScheme,
    api_key: str,
) -> dict[str, str]:
    """Build authentication headers for Anthropic-compatible endpoints."""
    headers = {"anthropic-version": "2023-06-01"}
    headers.update(build_auth_headers(auth_scheme, api_key))
    return headers


def build_anthropic_request_headers(
    auth_scheme: AuthScheme,
    api_key: str,
    *,
    stream: bool,
) -> dict[str, str]:
    headers = build_anthropic_auth_headers(auth_scheme, api_key)
    headers["Content-Type"] = "application/json"
    if stream:
        headers["Accept"] = "text/event-stream"
    return headers
