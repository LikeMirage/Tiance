from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


GitRepositoryAction = Literal[
    "overview", "status", "diff", "log", "show_commit",
    "fetch", "init", "connect_remote", "disconnect_remote",
    "create_branch", "switch_branch", "delete_branch",
    "list_tags", "create_tag", "delete_tag",
    "list_submodules", "add_submodule", "update_submodules",
    "commit", "push", "pull", "restore", "revert", "reset",
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
    dry_run: bool = Field(default=False, alias="dryRun")
    force: bool = False
    limit: int = Field(default=30, ge=1, le=100)
    message: str | None = Field(default=None, max_length=500)
    tag: str | None = Field(default=None, max_length=250)
    submodule_path: str | None = Field(default=None, alias="submodulePath", max_length=500)
