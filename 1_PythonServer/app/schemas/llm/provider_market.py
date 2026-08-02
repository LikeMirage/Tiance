from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ProviderMarketInstallationStatus = Literal[
    "not-installed",
    "installed",
    "update-available",
    "local-conflict",
]


class ProviderMarketContract(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ProviderMarketFilterSettings(ProviderMarketContract):
    authors: list[str] = Field(default_factory=list)
    protocols: list[str] = Field(default_factory=list)
    statuses: list[ProviderMarketInstallationStatus] = Field(default_factory=list)


class ProviderMarketSettingsResponse(ProviderMarketContract):
    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    source: str
    filters: ProviderMarketFilterSettings = Field(default_factory=ProviderMarketFilterSettings)


class ProviderMarketSettingsUpdateRequest(ProviderMarketContract):
    filters: ProviderMarketFilterSettings


class ProviderMarketConnectRequest(ProviderMarketContract):
    source: str


class ProviderMarketCompatibility(ProviderMarketContract):
    min_tiance_version: str = Field(alias="minTianceVersion")


class ProviderMarketEntry(ProviderMarketContract):
    id: str
    name: str
    version: str
    author: str
    summary: str
    license: str
    protocol: str
    model_count: int = Field(alias="modelCount")
    package_url: str = Field(alias="packageUrl")
    sha256: str
    size: int
    compatibility: ProviderMarketCompatibility


class ProviderMarketRemoteIndex(ProviderMarketContract):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    kind: Literal["tiance-provider-market"]
    name: str
    updated_at: datetime = Field(alias="updatedAt")
    providers: list[ProviderMarketEntry]


class ProviderMarketProviderResponse(ProviderMarketEntry):
    installation_status: ProviderMarketInstallationStatus = Field(alias="installationStatus")
    local_version: str | None = Field(default=None, alias="localVersion")
    local_project_id: str | None = Field(default=None, alias="localProjectId")


class ProviderMarketIndexResponse(ProviderMarketContract):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    kind: Literal["tiance-provider-market"]
    name: str
    updated_at: datetime = Field(alias="updatedAt")
    source: str
    cached: bool
    providers: list[ProviderMarketProviderResponse]


class ProviderMarketInstallRequest(ProviderMarketContract):
    category_id: str | None = Field(default=None, alias="categoryId")
    replace_existing: bool = Field(default=False, alias="replaceExisting")


class ProviderMarketInstallResponse(ProviderMarketContract):
    provider_id: str = Field(alias="providerId")
    project_id: str = Field(alias="projectId")
    category_id: str = Field(alias="categoryId")
    version: str
    updated: bool


class ProviderPackageAuthor(ProviderMarketContract):
    name: str


class ProviderPackageManifest(ProviderMarketContract):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    kind: Literal["tiance-provider-package"]
    id: str
    name: str
    version: str
    author: ProviderPackageAuthor
    summary: str
    license: str
    compatibility: ProviderMarketCompatibility
    managed_model_ids: list[str] = Field(alias="managedModelIds")
