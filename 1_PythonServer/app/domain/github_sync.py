from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.domain.project import ProjectKind


class GithubSyncDirection(StrEnum):
    PUSH = "push"
    PULL = "pull"


class GithubSyncChangeKind(StrEnum):
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class GithubSyncBinding:
    collection: ProjectKind
    repository: str
    branch: str
    remote_path: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class GithubSyncFile:
    path: str
    sha: str
    size: int


@dataclass(frozen=True, slots=True)
class GithubSyncChange:
    path: str
    kind: GithubSyncChangeKind
    size: int


@dataclass(frozen=True, slots=True)
class GithubSyncPlan:
    plan_id: str
    collection: ProjectKind
    direction: GithubSyncDirection
    binding: GithubSyncBinding
    local_fingerprint: str
    remote_head_sha: str | None
    changes: tuple[GithubSyncChange, ...]
    selected_paths: tuple[str, ...] | None
    selected_project_ids: tuple[str, ...] | None
    catalog_content: bytes | None
    created_at: str
    expires_at: float
