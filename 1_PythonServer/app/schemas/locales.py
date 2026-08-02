from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LocaleContract(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class LocaleDefinitionResponse(LocaleContract):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    locale: str
    display_name: str = Field(alias="displayName")
    direction: Literal["ltr", "rtl"]
    messages: dict[str, Any]


class LocaleSummaryResponse(LocaleContract):
    locale: str
    display_name: str = Field(alias="displayName")
    direction: Literal["ltr", "rtl"]


class LocaleListResponse(LocaleContract):
    active_locale: str = Field(alias="activeLocale")
    locales: list[LocaleSummaryResponse]


class LocaleSettingsResponse(LocaleContract):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    mode: Literal["system", "manual"]
    active_locale: str = Field(alias="activeLocale")


class LocaleSettingsUpdateRequest(LocaleContract):
    mode: Literal["system", "manual"]
    active_locale: str = Field(alias="activeLocale", min_length=2, max_length=64)
