from __future__ import annotations

from app.domain.llm.provider_catalog import AuthScheme
from app.infra.llm.url_utils import append_query_param


def build_auth_headers(auth_scheme: AuthScheme, api_key: str) -> dict[str, str]:
    if not api_key:
        return {}
    if auth_scheme == AuthScheme.BEARER_TOKEN:
        return {"Authorization": f"Bearer {api_key}"}
    if auth_scheme == AuthScheme.X_API_KEY:
        return {"x-api-key": api_key}
    if auth_scheme == AuthScheme.X_GOOG_API_KEY:
        return {"x-goog-api-key": api_key}
    return {}


def apply_auth_to_url(url: str, auth_scheme: AuthScheme, api_key: str) -> str:
    if auth_scheme == AuthScheme.API_KEY_QUERY and api_key:
        return append_query_param(url, "key", api_key)
    return url
