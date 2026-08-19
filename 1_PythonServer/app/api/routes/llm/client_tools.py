from fastapi import APIRouter

from app.schemas.llm.client_tools import (
    ClientToolClaimAck,
    ClientToolClaimRequestBody,
    ClientToolLeaseRenewAck,
    ClientToolLeaseRenewRequestBody,
    ClientToolResultAck,
    ClientToolResultRequestBody,
)
from app.services.tools.client_tool_bridge import get_client_tool_bridge_service

router = APIRouter(prefix="/llm/client-tools", tags=["llm"])


@router.post(
    "/{request_id}/claim",
    response_model=ClientToolClaimAck,
    summary="Claim a frontend client tool request",
)
async def claim_client_tool_request(
    request_id: str,
    payload: ClientToolClaimRequestBody,
) -> ClientToolClaimAck:
    lease = await get_client_tool_bridge_service().claim_request(
        request_id,
        executor_id=payload.executor_id,
    )
    return ClientToolClaimAck(
        acquired=lease.acquired,
        claim_id=lease.claim_id,
        lease_duration_seconds=lease.lease_duration_seconds,
        resumed=lease.resumed,
    )


@router.post(
    "/{request_id}/lease",
    response_model=ClientToolLeaseRenewAck,
    summary="Renew ownership of a frontend client tool request",
)
async def renew_client_tool_request_lease(
    request_id: str,
    payload: ClientToolLeaseRenewRequestBody,
) -> ClientToolLeaseRenewAck:
    renewed = await get_client_tool_bridge_service().renew_claim(
        request_id,
        executor_id=payload.executor_id,
        claim_id=payload.claim_id,
    )
    return ClientToolLeaseRenewAck(renewed=renewed)


@router.post(
    "/{request_id}/result",
    response_model=ClientToolResultAck,
    summary="Submit a frontend client tool result",
)
async def submit_client_tool_result(
    request_id: str,
    payload: ClientToolResultRequestBody,
) -> ClientToolResultAck:
    accepted = await get_client_tool_bridge_service().submit_result(
        request_id,
        payload.to_domain(),
        executor_id=payload.executor_id,
        claim_id=payload.claim_id,
    )
    return ClientToolResultAck(accepted=accepted)
