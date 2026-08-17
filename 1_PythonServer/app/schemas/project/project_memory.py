from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ProjectMemoryScope = Literal["global", "project"]
ProjectMemoryOperation = Literal["add", "update", "delete"]


class ProjectMemoryEventResponse(BaseModel):
    operation: str
    memory_id: str
    source: str
    created_at: str
    reason: str


class ProjectMemoryItemResponse(BaseModel):
    id: str
    scope: str
    content: str
    keywords: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    source: str
    last_operation: str
    event_count: int
    events: list[ProjectMemoryEventResponse] = Field(default_factory=list)


class ProjectMemoryListResponse(BaseModel):
    project_id: str
    scope: str
    count: int
    total_count: int
    page: int
    page_size: int
    total_pages: int
    has_previous: bool = False
    has_next: bool = False
    items: list[ProjectMemoryItemResponse] = Field(default_factory=list)


class ProjectMemoryOperationRequest(BaseModel):
    scope: ProjectMemoryScope
    operation: ProjectMemoryOperation
    memory_id: str | None = None
    content: str | None = None
    keywords: list[str] | None = None
    reason: str = Field(min_length=1)


class ProjectMemoryOperationResponse(BaseModel):
    project_id: str
    scope: str
    operation: str
    memory_id: str
    memory: ProjectMemoryItemResponse | None = None
    items: list[ProjectMemoryItemResponse] = Field(default_factory=list)
