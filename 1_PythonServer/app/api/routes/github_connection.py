from fastapi import APIRouter

from app.schemas.github_connection import (
    GithubConnectionStatusResponse,
    GithubDeviceFlowPollRequest,
    GithubDeviceFlowPollResponse,
    GithubDeviceFlowStartResponse,
    GithubLogoutResponse,
)
from app.services.application.github_connection import get_github_connection_service


router = APIRouter(prefix="/github", tags=["github"])


@router.get("/connection", response_model=GithubConnectionStatusResponse)
async def get_github_connection() -> GithubConnectionStatusResponse:
    return await get_github_connection_service().get_status()


@router.post("/device-flow", response_model=GithubDeviceFlowStartResponse)
async def start_github_device_flow() -> GithubDeviceFlowStartResponse:
    return await get_github_connection_service().start_device_flow()


@router.post("/device-flow/poll", response_model=GithubDeviceFlowPollResponse)
async def poll_github_device_flow(
    payload: GithubDeviceFlowPollRequest,
) -> GithubDeviceFlowPollResponse:
    return await get_github_connection_service().poll_device_flow(payload.flow_id)


@router.delete("/connection", response_model=GithubLogoutResponse)
async def logout_github() -> GithubLogoutResponse:
    await get_github_connection_service().logout()
    return GithubLogoutResponse()
