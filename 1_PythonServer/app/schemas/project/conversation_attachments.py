from typing import Literal

from pydantic import BaseModel, Field

from app.domain.llm.chat import ChatImageRef


class ConversationImageAttachmentCreateRequest(BaseModel):
    filename: str | None = None
    mime_type: str
    data_base64: str = Field(min_length=1)
    source_kind: Literal["clipboard", "preview_reference"]
    source_path: str | None = None


class ConversationImageAttachmentResponse(BaseModel):
    project_id: str
    session_id: str
    attachment_id: str
    path: str
    name: str
    mime_type: str
    size_bytes: int
    source_kind: str
    source_path: str | None = None

    @classmethod
    def from_domain(
        cls,
        *,
        project_id: str,
        session_id: str,
        image_ref: ChatImageRef,
    ) -> "ConversationImageAttachmentResponse":
        return cls(
            project_id=project_id,
            session_id=session_id,
            attachment_id=image_ref.attachment_id or "",
            path=image_ref.path,
            name=image_ref.name or "image",
            mime_type=image_ref.mime_type or "application/octet-stream",
            size_bytes=image_ref.size_bytes or 0,
            source_kind=image_ref.source_kind or "",
            source_path=image_ref.source_path,
        )
