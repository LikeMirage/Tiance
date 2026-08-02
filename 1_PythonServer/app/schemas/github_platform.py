from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GithubPlatformToolRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    action: str = Field(min_length=1, max_length=80)
    dry_run: bool = Field(default=False, alias="dryRun")
    parameters: dict[str, Any] = Field(default_factory=dict)
