from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ProjectMarketInstallationStatus = Literal["not-installed", "installed"]
ProjectMarketInstallPhase = Literal[
    "queued",
    "downloading",
    "extracting",
    "importing",
    "completed",
    "failed",
]


class ProjectMarketContract(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ProjectMarketFilterSettings(ProjectMarketContract):
    authors: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    statuses: list[ProjectMarketInstallationStatus] = Field(default_factory=list)


class ProjectMarketSettingsResponse(ProjectMarketContract):
    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    source: str
    filters: ProjectMarketFilterSettings = Field(default_factory=ProjectMarketFilterSettings)


class ProjectMarketSettingsUpdateRequest(ProjectMarketContract):
    filters: ProjectMarketFilterSettings


class ProjectMarketConnectRequest(ProjectMarketContract):
    source: str


class ProjectMarketSourceUpdateRequest(ProjectMarketContract):
    source: str


class ProjectMarketStats(ProjectMarketContract):
    file_count: int | None = Field(default=None, ge=0, alias="fileCount")
    conversation_count: int | None = Field(default=None, ge=0, alias="conversationCount")
    branch_count: int | None = Field(default=None, ge=0, alias="branchCount")


class ProjectMarketDownload(ProjectMarketContract):
    kind: Literal["archive", "github-directory"]
    url: str | None = None
    path: str | None = None
    ref: str | None = None
    size: int | None = Field(default=None, ge=1)
    sha256: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "ProjectMarketDownload":
        if self.kind == "archive" and not (self.url or "").strip():
            raise ValueError("archive download requires url")
        if self.kind == "github-directory" and not (self.path or "").strip():
            raise ValueError("github-directory download requires path")
        if self.sha256 is not None:
            digest = self.sha256.strip().lower()
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("sha256 must be a lowercase hexadecimal digest")
            self.sha256 = digest
        if self.ref is not None and not self.ref.strip():
            raise ValueError("download ref cannot be empty")
        return self


class ProjectMarketProjectEntry(ProjectMarketContract):
    id: str
    name: str
    summary: str
    author: str
    version: str
    updated_at: str = Field(alias="updatedAt")
    download: ProjectMarketDownload
    preview_url: str | None = Field(default=None, alias="previewUrl")
    tags: list[str] = Field(default_factory=list)
    stats: ProjectMarketStats | None = None


class ProjectMarketRemoteIndex(ProjectMarketContract):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    kind: Literal[
        "tiance-project-market",
        "tiance-knowledge-market",
        "tiance-experience-market",
    ]
    name: str
    updated_at: str = Field(alias="updatedAt")
    default_ref: str = Field(default="main", alias="defaultRef")
    projects: list[ProjectMarketProjectEntry]


class ProjectMarketProjectResponse(ProjectMarketProjectEntry):
    installation_status: ProjectMarketInstallationStatus = Field(alias="installationStatus")
    local_project_id: str | None = Field(default=None, alias="localProjectId")
    preview_path: str | None = Field(default=None, alias="previewPath")


class ProjectMarketIndexResponse(ProjectMarketContract):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    kind: Literal[
        "tiance-project-market",
        "tiance-knowledge-market",
        "tiance-experience-market",
    ]
    name: str
    updated_at: str = Field(alias="updatedAt")
    source: str
    cached: bool
    projects: list[ProjectMarketProjectResponse]


class ProjectMarketInstallRequest(ProjectMarketContract):
    category_id: str = Field(alias="categoryId")


class ProjectMarketInstallResult(ProjectMarketContract):
    market_project_id: str = Field(alias="marketProjectId")
    project_id: str = Field(alias="projectId")
    category_id: str = Field(alias="categoryId")
    version: str


class ProjectMarketInstallOperation(ProjectMarketContract):
    operation_id: str = Field(alias="operationId")
    market_project_id: str = Field(alias="marketProjectId")
    phase: ProjectMarketInstallPhase
    error: str | None = None
    result: ProjectMarketInstallResult | None = None
