from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.domain.llm.provider_capabilities import (
    ProviderWebSearchResult,
    ProviderWebSearchSource,
)
from app.schemas.llm.chat import ChatUsageResponse


class ProviderWebSearchRequestBody(BaseModel):
    query: str = Field(min_length=1)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("query 不能为空")
        return normalized


class ProviderWebSearchSourceResponse(BaseModel):
    url: str
    title: str | None = None
    source_kind: str
    cited_text: str | None = None
    page_age: str | None = None
    metadata: dict[str, Any]

    @classmethod
    def from_domain(
        cls,
        source: ProviderWebSearchSource,
    ) -> "ProviderWebSearchSourceResponse":
        return cls(
            url=source.url,
            title=source.title,
            source_kind=source.source_kind,
            cited_text=source.cited_text,
            page_age=source.page_age,
            metadata=source.metadata,
        )


class ProviderWebSearchResponse(BaseModel):
    provider_id: str
    model_id: str
    answer: str
    search_queries: list[str]
    sources: list[ProviderWebSearchSourceResponse]
    actions: list[dict[str, Any]]
    provider_metadata: list[dict[str, Any]]
    provider_usage: dict[str, Any]
    usage: ChatUsageResponse | None = None
    response_id: str | None = None
    status: str | None = None

    @classmethod
    def from_domain(
        cls,
        result: ProviderWebSearchResult,
    ) -> "ProviderWebSearchResponse":
        return cls(
            provider_id=result.provider_id,
            model_id=result.model_id,
            answer=result.answer,
            search_queries=list(result.search_queries),
            sources=[
                ProviderWebSearchSourceResponse.from_domain(source)
                for source in result.sources
            ],
            actions=list(result.actions),
            provider_metadata=list(result.provider_metadata),
            provider_usage=result.provider_usage,
            usage=(
                ChatUsageResponse.from_domain(result.usage)
                if result.usage is not None
                else None
            ),
            response_id=result.response_id,
            status=result.status,
        )
