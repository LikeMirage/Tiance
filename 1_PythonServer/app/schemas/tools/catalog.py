from typing import Any

from pydantic import BaseModel, Field

from app.domain.tools import (
    ToolExampleDetail,
    ToolExampleSummary,
    ToolParameterDetail,
    ToolSummary,
)


class ToolSummaryResponse(BaseModel):
    name: str
    display_name: str
    description: str
    keywords: list[str] = Field(default_factory=list)
    category: str
    dynamic: bool
    parallel: bool = False
    parameter_names: list[str] = Field(default_factory=list)
    example_titles: list[str] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, summary: ToolSummary) -> "ToolSummaryResponse":
        return cls(
            name=summary.name,
            display_name=summary.display_name,
            description=summary.description,
            keywords=list(summary.keywords),
            category=summary.category,
            dynamic=summary.dynamic,
            parallel=summary.parallel,
            parameter_names=list(summary.parameter_names),
            example_titles=list(summary.example_titles),
        )


class ToolSummaryListResponse(BaseModel):
    count: int
    items: list[ToolSummaryResponse] = Field(default_factory=list)


class ToolParameterDetailResponse(BaseModel):
    name: str
    input_schema: dict[str, Any]

    @classmethod
    def from_domain(
        cls,
        detail: ToolParameterDetail,
    ) -> "ToolParameterDetailResponse":
        return cls(
            name=detail.name,
            input_schema=detail.input_schema,
        )


class ToolExampleSummaryResponse(BaseModel):
    index: int
    title: str

    @classmethod
    def from_domain(
        cls,
        summary: ToolExampleSummary,
    ) -> "ToolExampleSummaryResponse":
        return cls(
            index=summary.index,
            title=summary.title,
        )


class ToolExampleSummaryListResponse(BaseModel):
    name: str
    count: int
    items: list[ToolExampleSummaryResponse] = Field(default_factory=list)


class ToolExampleQueryRequest(BaseModel):
    titles: list[str] = Field(default_factory=list)
    indexes: list[int] = Field(default_factory=list)
    include_all: bool = False


class ToolExampleDetailResponse(BaseModel):
    index: int
    title: str
    content: str

    @classmethod
    def from_domain(cls, detail: ToolExampleDetail) -> "ToolExampleDetailResponse":
        return cls(
            index=detail.index,
            title=detail.title,
            content=detail.content,
        )


class ToolExampleDetailListResponse(BaseModel):
    name: str
    count: int
    items: list[ToolExampleDetailResponse] = Field(default_factory=list)
