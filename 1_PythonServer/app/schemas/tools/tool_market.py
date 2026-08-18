from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ToolMarketInstallationStatus = Literal[
    "not-installed",
    "installed",
    "update-available",
    "call-name-conflict",
]


class ToolMarketContract(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ToolMarketFilterSettings(ToolMarketContract):
    authors: list[str] = Field(default_factory=list)
    runtimes: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    statuses: list[ToolMarketInstallationStatus] = Field(default_factory=list)


class ToolMarketSettingsResponse(ToolMarketContract):
    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    source: str
    filters: ToolMarketFilterSettings = Field(default_factory=ToolMarketFilterSettings)


class ToolMarketSettingsUpdateRequest(ToolMarketContract):
    filters: ToolMarketFilterSettings


class ToolMarketConnectRequest(ToolMarketContract):
    source: str


class ToolMarketCompatibility(ToolMarketContract):
    min_tiance_version: str = Field(alias="minTianceVersion")
    platforms: list[str]


class ToolMarketEntry(ToolMarketContract):
    id: str
    version: str
    author: str
    license: str
    call_name: str = Field(alias="callName")
    display_name: str = Field(alias="displayName")
    summary: str
    runtime: str
    package_url: str = Field(alias="packageUrl")
    sha256: str
    size: int
    compatibility: ToolMarketCompatibility


class ToolMarketRemoteIndex(ToolMarketContract):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    kind: Literal["tiance-tool-market"]
    name: str
    updated_at: datetime = Field(alias="updatedAt")
    tools: list[ToolMarketEntry]


class ToolMarketToolResponse(ToolMarketEntry):
    installation_status: ToolMarketInstallationStatus = Field(alias="installationStatus")
    local_project_id: str | None = Field(default=None, alias="localProjectId")
    local_version: str | None = Field(default=None, alias="localVersion")
    local_call_name: str | None = Field(default=None, alias="localCallName")
    suggested_call_name: str | None = Field(default=None, alias="suggestedCallName")


class ToolMarketIndexResponse(ToolMarketContract):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    kind: Literal["tiance-tool-market"]
    name: str
    updated_at: datetime = Field(alias="updatedAt")
    source: str
    cached: bool
    tools: list[ToolMarketToolResponse]


class ToolMarketInstallRequest(ToolMarketContract):
    category_id: str | None = Field(default=None, alias="categoryId")
    call_name: str | None = Field(
        default=None,
        alias="callName",
        pattern=r"^[a-z][a-z0-9_]*$",
    )


class ToolMarketInstallResponse(ToolMarketContract):
    tool_id: str = Field(alias="toolId")
    project_id: str = Field(alias="projectId")
    category_id: str = Field(alias="categoryId")
    call_name: str = Field(alias="callName")
    version: str
    updated: bool
    has_dependencies: bool = Field(alias="hasDependencies")


class ToolPackageAuthor(ToolMarketContract):
    name: str


class ToolPackageManifest(ToolMarketContract):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    kind: Literal["tiance-tool-package"]
    id: str
    version: str
    author: ToolPackageAuthor
    license: str
    compatibility: ToolMarketCompatibility
