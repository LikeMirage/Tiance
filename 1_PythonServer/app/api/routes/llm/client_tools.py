from fastapi import APIRouter

from app.schemas.llm.client_tools import (
    ClientToolClaimAck,
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
async def claim_client_tool_request(request_id: str) -> ClientToolClaimAck:
    acquired = await get_client_tool_bridge_service().claim_request(request_id)
    return ClientToolClaimAck(acquired=acquired)


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
    )
    return ClientToolResultAck(accepted=accepted)
