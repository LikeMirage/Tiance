from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _AnnouncementModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class AnnouncementYearReference(_AnnouncementModel):
    year: int
    index_path: str = Field(alias="indexPath")


class AnnouncementRootIndex(_AnnouncementModel):
    schema_version: int = Field(alias="schemaVersion")
    updated_at: str = Field(alias="updatedAt")
    latest_announcement_id: str = Field(alias="latestAnnouncementId")
    latest_announcement_year: int = Field(alias="latestAnnouncementYear")
    years: list[AnnouncementYearReference]


class AnnouncementItem(_AnnouncementModel):
    id: str
    revision: int
    title: str
    summary: str
    published_at: str = Field(alias="publishedAt")
    importance: Literal["normal", "important", "critical"]
    status: Literal["published", "withdrawn"]
    content_path: str = Field(alias="contentPath")
    read: bool = False


class AnnouncementYearIndex(_AnnouncementModel):
    schema_version: int = Field(alias="schemaVersion")
    year: int
    updated_at: str = Field(alias="updatedAt")
    announcements: list[AnnouncementItem]
    cached: bool = False


class AnnouncementSettings(_AnnouncementModel):
    source: str
    check_on_startup: bool = Field(default=True, alias="checkOnStartup")


class AnnouncementSettingsUpdate(_AnnouncementModel):
    check_on_startup: bool = Field(alias="checkOnStartup")


class AnnouncementCheckResponse(_AnnouncementModel):
    root: AnnouncementRootIndex
    latest_year: AnnouncementYearIndex = Field(alias="latestYear")
    latest: AnnouncementItem
    latest_unread: bool = Field(alias="latestUnread")
    cached: bool
    last_successful_check_at: str | None = Field(alias="lastSuccessfulCheckAt")


class AnnouncementContentResponse(_AnnouncementModel):
    announcement: AnnouncementItem
    content: str
    cached: bool


class AnnouncementReadRequest(_AnnouncementModel):
    revision: int


class AnnouncementReadResponse(_AnnouncementModel):
    announcement_id: str = Field(alias="announcementId")
    revision: int
    read_at: str = Field(alias="readAt")


class AnnouncementAssetReference(_AnnouncementModel):
    path: str
    media_type: str | None = Field(default=None, alias="mediaType")
