from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ProviderWebSearchSource:
    url: str
    title: str | None = None
    source_kind: str = "web"
    cited_text: str | None = None
    page_age: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderWebSearchResult:
    provider_id: str
    model_id: str
    answer: str
    search_queries: tuple[str, ...] = ()
    sources: tuple[ProviderWebSearchSource, ...] = ()
    actions: tuple[dict[str, Any], ...] = ()
    provider_metadata: tuple[dict[str, Any], ...] = ()
    provider_usage: dict[str, Any] = field(default_factory=dict)
    response_id: str | None = None
    status: str | None = None


@dataclass(frozen=True, slots=True)
class SearchTarget:
    provider_id: str
    model_id: str
    protocol_family: str
    endpoint: str
    responses_tool: str
    include_sources: bool


class SearchError(Exception):
    def __init__(self, message, *, code="provider_web_search_failed", details=None):
        super().__init__(message)
        self.code = code
        self.details = details


def build_web_search_prompt(query: str) -> str:
    return f"Search the web for the following request and answer using the retrieved sources:\n\n{query}"


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None
