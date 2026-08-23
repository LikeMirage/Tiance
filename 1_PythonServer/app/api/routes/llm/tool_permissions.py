from fastapi import APIRouter

from app.schemas.llm.tool_permissions import (
    ToolPermissionDecisionAck,
    ToolPermissionDecisionRequestBody,
)
from app.services.tools.tool_permission_bridge import (
    get_tool_permission_bridge_service,
)


router = APIRouter(prefix="/llm/tool-permissions", tags=["llm"])


@router.post(
    "/{request_id}/decision",
    response_model=ToolPermissionDecisionAck,
    summary="Submit a one-time tool permission decision",
)
async def submit_tool_permission_decision(
    request_id: str,
    payload: ToolPermissionDecisionRequestBody,
) -> ToolPermissionDecisionAck:
    accepted = await get_tool_permission_bridge_service().submit_decision(
        request_id,
        payload.decision,
    )
    return ToolPermissionDecisionAck(accepted=accepted)
