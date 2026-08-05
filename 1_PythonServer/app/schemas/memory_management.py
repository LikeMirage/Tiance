from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MemoryManagementToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["list", "search", "add", "update", "delete"]
    scope: Literal["global", "project"] | None = None
    query: str = Field(default="", max_length=1000)
    memory_id: str | None = Field(default=None, max_length=200)
    content: str | None = Field(default=None, max_length=200000)
    keywords: list[str] | None = Field(default=None, max_length=100)
    reason: str = Field(default="", max_length=2000)
