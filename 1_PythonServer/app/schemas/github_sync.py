from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.github_sync import GithubSyncBinding, GithubSyncChange, GithubSyncPlan
from app.domain.project import ProjectKind


class GithubSyncContract(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class GithubSyncBindingResponse(GithubSyncContract):
    collection: ProjectKind
    repository: str
    branch: str
    remote_path: str = Field(alias="remotePath")
    updated_at: str = Field(alias="updatedAt")

    @classmethod
    def from_domain(cls, binding: GithubSyncBinding) -> "GithubSyncBindingResponse":
        return cls(
            collection=binding.collection,
            repository=binding.repository,
            branch=binding.branch,
            remote_path=binding.remote_path,
            updated_at=binding.updated_at,
        )


class GithubSyncBindingRequest(GithubSyncContract):
    repository: str = Field(min_length=1, max_length=220)
    branch: str = Field(default="main", min_length=1, max_length=250)
    remote_path: str = Field(default="", alias="remotePath", max_length=500)


class GithubSyncRepositoryResponse(GithubSyncContract):
    id: int
    full_name: str = Field(alias="fullName")
    private: bool
    default_branch: str = Field(alias="defaultBranch")
    can_push: bool = Field(alias="canPush")


class GithubSyncOverviewResponse(GithubSyncContract):
    collection: ProjectKind
    connected: bool
    binding: GithubSyncBindingResponse | None = None
    repositories: list[GithubSyncRepositoryResponse] = Field(default_factory=list)
    authorization_url: str = Field(alias="authorizationUrl")


class GithubSyncPlanRequest(GithubSyncContract):
    collection: ProjectKind | None = None
    direction: Literal["push", "pull"]


class GithubSyncChangeResponse(GithubSyncContract):
    path: str
    kind: Literal["add", "update", "delete"]
    size: int

    @classmethod
    def from_domain(cls, change: GithubSyncChange) -> "GithubSyncChangeResponse":
        return cls(path=change.path, kind=change.kind.value, size=change.size)


class GithubSyncPlanResponse(GithubSyncContract):
    plan_id: str = Field(alias="planId")
    collection: ProjectKind
    direction: Literal["push", "pull"]
    repository: str
    branch: str
    remote_path: str = Field(alias="remotePath")
    remote_head_sha: str | None = Field(alias="remoteHeadSha")
    changes: list[GithubSyncChangeResponse]
    additions: int
    updates: int
    deletions: int
    created_at: str = Field(alias="createdAt")

    @classmethod
    def from_domain(cls, plan: GithubSyncPlan) -> "GithubSyncPlanResponse":
        return cls(
            plan_id=plan.plan_id,
            collection=plan.collection,
            direction=plan.direction.value,
            repository=plan.binding.repository,
            branch=plan.binding.branch,
            remote_path=plan.binding.remote_path,
            remote_head_sha=plan.remote_head_sha,
            changes=[GithubSyncChangeResponse.from_domain(item) for item in plan.changes],
            additions=sum(item.kind.value == "add" for item in plan.changes),
            updates=sum(item.kind.value == "update" for item in plan.changes),
            deletions=sum(item.kind.value == "delete" for item in plan.changes),
            created_at=plan.created_at,
        )


class GithubSyncApplyRequest(GithubSyncContract):
    commit_message: str | None = Field(default=None, alias="commitMessage", max_length=200)


class GithubSyncApplyResponse(GithubSyncContract):
    ok: Literal[True] = True
    collection: ProjectKind
    direction: Literal["push", "pull"]
    repository: str
    branch: str
    commit_sha: str | None = Field(alias="commitSha")
    changed_files: int = Field(alias="changedFiles")
    message: str


class GithubSyncToolRequest(GithubSyncContract):
    action: Literal[
        "overview", "list_repositories", "get_binding", "bind", "unbind",
        "plan_push", "push", "plan_pull", "pull",
    ]
    collection: ProjectKind | None = None
    repository: str | None = Field(default=None, max_length=220)
    branch: str | None = Field(default=None, max_length=250)
    remote_path: str | None = Field(default=None, alias="remotePath", max_length=500)
    plan_id: str | None = Field(default=None, alias="planId", max_length=80)
    commit_message: str | None = Field(default=None, alias="commitMessage", max_length=200)
