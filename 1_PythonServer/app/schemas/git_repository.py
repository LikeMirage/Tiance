from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


GitRepositoryAction = Literal[
    "overview", "status", "diff", "log", "show_commit",
    "fetch", "init", "connect_remote", "disconnect_remote",
    "create_branch", "switch_branch",
    "plan_commit", "commit", "plan_push", "push", "plan_pull", "pull",
    "plan_restore", "restore", "plan_revert", "revert",
]


class GitRepositoryToolRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    action: GitRepositoryAction
    remote: str = Field(default="origin", min_length=1, max_length=80)
    repository: str | None = Field(default=None, max_length=300)
    branch: str | None = Field(default=None, max_length=250)
    revision: str | None = Field(default=None, max_length=100)
    paths: list[str] | None = Field(default=None, max_length=5_000)
    staged: bool = False
    limit: int = Field(default=30, ge=1, le=100)
    message: str | None = Field(default=None, max_length=500)
    plan_id: str | None = Field(default=None, alias="planId", max_length=80)
