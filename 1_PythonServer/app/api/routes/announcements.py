from fastapi import APIRouter, Query, Response

from app.schemas.announcements import (
    AnnouncementCheckResponse,
    AnnouncementContentResponse,
    AnnouncementReadRequest,
    AnnouncementReadResponse,
    AnnouncementSettings,
    AnnouncementSettingsUpdate,
    AnnouncementYearIndex,
)
from app.services.application.announcements import get_announcement_application_service


router = APIRouter(prefix="/announcements", tags=["announcements"])


@router.get("/settings", response_model=AnnouncementSettings)
async def get_announcement_settings() -> AnnouncementSettings:
    return await get_announcement_application_service().get_settings()


@router.put("/settings", response_model=AnnouncementSettings)
async def update_announcement_settings(
    payload: AnnouncementSettingsUpdate,
) -> AnnouncementSettings:
    return await get_announcement_application_service().update_settings(
        payload.check_on_startup
    )


@router.post("/check", response_model=AnnouncementCheckResponse)
async def check_announcements() -> AnnouncementCheckResponse:
    return await get_announcement_application_service().check()


@router.get("/years/{year}", response_model=AnnouncementYearIndex)
async def get_announcement_year(year: int) -> AnnouncementYearIndex:
    return await get_announcement_application_service().get_year(year)


@router.get(
    "/{announcement_id}/content",
    response_model=AnnouncementContentResponse,
)
async def get_announcement_content(
    announcement_id: str,
    revision: int = Query(ge=1),
) -> AnnouncementContentResponse:
    return await get_announcement_application_service().get_content(
        announcement_id,
        revision,
    )


@router.post("/{announcement_id}/read", response_model=AnnouncementReadResponse)
async def mark_announcement_read(
    announcement_id: str,
    payload: AnnouncementReadRequest,
) -> AnnouncementReadResponse:
    return await get_announcement_application_service().mark_read(
        announcement_id,
        payload.revision,
    )


@router.get("/{announcement_id}/assets/{asset_path:path}")
async def get_announcement_asset(
    announcement_id: str,
    asset_path: str,
    revision: int = Query(ge=1),
) -> Response:
    payload, media_type = await get_announcement_application_service().get_asset(
        announcement_id,
        revision,
        f"assets/{asset_path}",
    )
    return Response(
        content=payload,
        media_type=media_type or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )
