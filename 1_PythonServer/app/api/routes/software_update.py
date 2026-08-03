from fastapi import APIRouter

from app.schemas.software_update import (
    SoftwareUpdateCheckResponse,
    SoftwareUpdateDownloadResponse,
)
from app.services.application.software_update import get_software_update_service


router = APIRouter(prefix="/software-update", tags=["software-update"])


@router.get("/check", response_model=SoftwareUpdateCheckResponse)
async def check_software_update() -> SoftwareUpdateCheckResponse:
    return await get_software_update_service().check()


@router.post("/download", response_model=SoftwareUpdateDownloadResponse)
async def download_software_update() -> SoftwareUpdateDownloadResponse:
    return await get_software_update_service().download()
