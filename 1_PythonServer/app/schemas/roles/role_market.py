from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


RoleMarketInstallationStatus = Literal[
    "not-installed",
    "installed",
    "update-available",
]


class RoleMarketContract(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class RoleMarketFilterSettings(RoleMarketContract):
    authors: list[str] = Field(default_factory=list)
    statuses: list[RoleMarketInstallationStatus] = Field(default_factory=list)


class RoleMarketSettingsResponse(RoleMarketContract):
    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    source: str
    filters: RoleMarketFilterSettings = Field(default_factory=RoleMarketFilterSettings)


class RoleMarketSettingsUpdateRequest(RoleMarketContract):
    filters: RoleMarketFilterSettings


class RoleMarketConnectRequest(RoleMarketContract):
    source: str


class RoleMarketCompatibility(RoleMarketContract):
    min_tiance_version: str = Field(alias="minTianceVersion")


class RoleMarketRoleEntry(RoleMarketContract):
    id: str
    name: str
    version: str
    author: str
    summary: str
    license: str
    package_url: str = Field(alias="packageUrl")
    sha256: str
    size: int
    compatibility: RoleMarketCompatibility


class RoleMarketRemoteIndex(RoleMarketContract):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    kind: Literal["tiance-role-market"]
    name: str
    updated_at: datetime = Field(alias="updatedAt")
    roles: list[RoleMarketRoleEntry]


class RoleMarketRoleResponse(RoleMarketRoleEntry):
    installation_status: RoleMarketInstallationStatus = Field(alias="installationStatus")
    local_version: str | None = Field(default=None, alias="localVersion")
    local_project_id: str | None = Field(default=None, alias="localProjectId")


class RoleMarketIndexResponse(RoleMarketContract):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    kind: Literal["tiance-role-market"]
    name: str
    updated_at: datetime = Field(alias="updatedAt")
    source: str
    cached: bool
    roles: list[RoleMarketRoleResponse]


class RoleMarketInstallRequest(RoleMarketContract):
    category_id: str | None = Field(default=None, alias="categoryId")
    replace_existing: bool = Field(default=False, alias="replaceExisting")


class RoleMarketInstallResponse(RoleMarketContract):
    role_id: str = Field(alias="roleId")
    project_id: str = Field(alias="projectId")
    category_id: str = Field(alias="categoryId")
    version: str
    updated: bool


class RolePackageAuthor(RoleMarketContract):
    name: str


class RolePackageManifest(RoleMarketContract):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    kind: Literal["tiance-role-package"]
    id: str
    name: str
    version: str
    author: RolePackageAuthor
    summary: str
    license: str
    compatibility: RoleMarketCompatibility
