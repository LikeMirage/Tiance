import asyncio

from fastapi import APIRouter

from app.schemas.project.conversation_exports import (
    ConversationExportRequest,
    ConversationExportResponse,
)
from app.services.conversation_export import get_conversation_export_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post(
    "/{project_id}/conversations/{session_id}/exports",
    response_model=ConversationExportResponse,
    summary="Export a project conversation",
)
async def export_project_conversation(
    project_id: str,
    session_id: str,
    payload: ConversationExportRequest,
) -> ConversationExportResponse:
    result = await asyncio.to_thread(
        get_conversation_export_service().export,
        project_id,
        session_id,
        export_format=payload.format,
        export_range=payload.range,
        message_id=payload.message_id,
        content_selection=payload.content.to_domain(),
        target_directory=payload.target_directory,
        base_name=payload.base_name,
        open_after_export=payload.open_after_export,
    )
    return ConversationExportResponse.from_domain(payload.format, result)
