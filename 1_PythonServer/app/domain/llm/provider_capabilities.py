from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.llm.chat import ChatUsage


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
    usage: ChatUsage | None = None
    response_id: str | None = None
    status: str | None = None
