from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GlobalMemoryValueResponse(BaseModel):
    content: str
    keywords: list[str] = Field(default_factory=list)


class GlobalMemoryEventResponse(BaseModel):
    event_index: int
    operation: Literal["add", "update", "delete"]
    memory_id: str
    source: str
    created_at: str
    reason: str
    before: GlobalMemoryValueResponse | None = None
    after: GlobalMemoryValueResponse | None = None


class GlobalMemoryRecordResponse(BaseModel):
    id: str
    scope: Literal["global"]
    status: Literal["active", "deleted"]
    content: str
    keywords: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    deleted_at: str = ""
    source: str
    last_operation: Literal["add", "update", "delete"]
    event_count: int
    events: list[GlobalMemoryEventResponse] = Field(default_factory=list)


class GlobalMemoryRecordListResponse(BaseModel):
    scope: Literal["global"]
    status: Literal["active", "deleted", "all"]
    count: int
    total_count: int
    page: int
    page_size: int
    total_pages: int
    has_previous: bool = False
    has_next: bool = False
    items: list[GlobalMemoryRecordResponse] = Field(default_factory=list)


class GlobalMemoryEventListResponse(BaseModel):
    scope: Literal["global"]
    count: int
    total_count: int
    page: int
    page_size: int
    total_pages: int
    has_previous: bool = False
    has_next: bool = False
    items: list[GlobalMemoryEventResponse] = Field(default_factory=list)


class GlobalMemoryOperationRequest(BaseModel):
    operation: Literal["add", "update", "delete"]
    memory_id: str | None = None
    content: str | None = None
    keywords: list[str] | None = None
    reason: str = Field(min_length=1)


class GlobalMemoryOperationResponse(BaseModel):
    operation: Literal["add", "update", "delete"]
    memory_id: str
    memory: GlobalMemoryRecordResponse
