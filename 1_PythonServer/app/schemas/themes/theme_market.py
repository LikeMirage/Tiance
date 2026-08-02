from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ThemeMarketInstallationStatus = Literal[
    "not-installed",
    "installed",
    "update-available",
]


class ThemeMarketContract(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ThemeMarketFilterSettings(ThemeMarketContract):
    modes: list[Literal["dark", "light"]] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    base_colors: list[str] = Field(default_factory=list, alias="baseColors")
    statuses: list[ThemeMarketInstallationStatus] = Field(default_factory=list)


class ThemeMarketSettingsResponse(ThemeMarketContract):
    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    source: str
    filters: ThemeMarketFilterSettings = Field(default_factory=ThemeMarketFilterSettings)


class ThemeMarketSettingsUpdateRequest(ThemeMarketContract):
    filters: ThemeMarketFilterSettings


class ThemeMarketConnectRequest(ThemeMarketContract):
    source: str


class ThemeMarketCompatibility(ThemeMarketContract):
    theme_schema_version: Literal[2] = Field(alias="themeSchemaVersion")
    min_tiance_version: str = Field(alias="minTianceVersion")


class ThemeMarketThemeEntry(ThemeMarketContract):
    id: str
    name: str
    mode: Literal["dark", "light"]
    version: str
    author: str
    summary: str
    license: str
    base_colors: list[str] = Field(default_factory=list, alias="baseColors")
    preview_url: str = Field(alias="previewUrl")
    package_url: str = Field(alias="packageUrl")
    sha256: str
    size: int
    compatibility: ThemeMarketCompatibility


class ThemeMarketRemoteIndex(ThemeMarketContract):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    kind: Literal["tiance-theme-market"]
    name: str
    updated_at: str = Field(alias="updatedAt")
    themes: list[ThemeMarketThemeEntry]


class ThemeMarketThemeResponse(ThemeMarketThemeEntry):
    installation_status: ThemeMarketInstallationStatus = Field(alias="installationStatus")
    local_version: str | None = Field(default=None, alias="localVersion")
    preview_path: str = Field(alias="previewPath")


class ThemeMarketIndexResponse(ThemeMarketContract):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    kind: Literal["tiance-theme-market"]
    name: str
    updated_at: str = Field(alias="updatedAt")
    source: str
    cached: bool
    themes: list[ThemeMarketThemeResponse]


class ThemeMarketInstallRequest(ThemeMarketContract):
    category_id: str | None = Field(default=None, alias="categoryId")
    replace_existing: bool = Field(default=False, alias="replaceExisting")


class ThemeMarketInstallResponse(ThemeMarketContract):
    theme_id: str = Field(alias="themeId")
    project_id: str = Field(alias="projectId")
    category_id: str = Field(alias="categoryId")
    version: str
