from __future__ import annotations

from datetime import UTC, datetime
from base64 import b64decode
from binascii import Error as Base64Error
from mimetypes import guess_type
from pathlib import Path

from app.core.errors import BadRequestError, NotFoundError
from app.domain.llm.chat import ChatImageRef
from app.infra.file_workspace import FileWorkspaceStorage, get_file_workspace_storage
from app.repositories.project.conversation_attachment_repository import (
    ConversationAttachmentRepository,
    get_conversation_attachment_repository,
    is_attachment_uri,
)
from app.services.project.projects import ProjectService, get_project_service
from app.services.tools.tool_resource_uris import local_absolute_path

_SUPPORTED_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "image/bmp",
}


class ConversationAttachmentService:
    def __init__(
        self,
        repository: ConversationAttachmentRepository,
        project_service: ProjectService,
        file_storage: FileWorkspaceStorage,
    ) -> None:
        self._repository = repository
        self._project_service = project_service
        self._file_storage = file_storage

    def snapshot_image_ref(
        self,
        project_id: str,
        session_id: str,
        image_ref: ChatImageRef,
        *,
        source_kind: str | None = None,
    ) -> ChatImageRef:
        if is_attachment_uri(image_ref.path):
            attachment, _ = self._repository.read(
                project_id,
                session_id,
                image_ref.path,
            )
            return ChatImageRef(
                path=attachment.uri,
                mime_type=attachment.mime_type,
                detail=image_ref.detail,
                name=attachment.display_name,
                size_bytes=attachment.size_bytes,
                attachment_id=attachment.attachment_id,
                source_path=attachment.source_path,
                source_kind=attachment.source_kind,
            )

        project = self._project_service.get_project(project_id)
        if project is None:
            raise NotFoundError(f"项目 '{project_id}' 不存在。")
        source_file = (
            local_absolute_path(image_ref.path)
            or self._file_storage.resolve_file_path(project.root_path, image_ref.path)
        )
        if not source_file.is_file():
            raise NotFoundError("图片文件不存在。")
        content = source_file.read_bytes()
        if not content:
            raise BadRequestError("图片内容为空。")
        mime_type = normalize_image_mime_type(
            image_ref.mime_type or guess_type(str(source_file))[0] or ""
        )
        validate_image_signature(content, mime_type)
        attachment = self._repository.save_bytes(
            project_id,
            session_id,
            content=content,
            suffix=source_file.suffix,
            display_name=image_ref.name or source_file.name,
            mime_type=mime_type,
            source_kind=source_kind or _source_kind(image_ref.path),
            source_path=image_ref.source_path or image_ref.path,
            created_at=datetime.now(UTC).isoformat(),
        )
        return ChatImageRef(
            path=attachment.uri,
            mime_type=attachment.mime_type,
            detail=image_ref.detail,
            name=attachment.display_name,
            size_bytes=attachment.size_bytes,
            attachment_id=attachment.attachment_id,
            source_path=attachment.source_path,
            source_kind=attachment.source_kind,
        )

    def read_image(
        self,
        project_id: str,
        session_id: str,
        image_ref: ChatImageRef,
    ) -> tuple[bytes, str]:
        attachment, path = self._repository.read(
            project_id,
            session_id,
            image_ref.path,
        )
        content = path.read_bytes()
        if not content:
            raise BadRequestError("图片内容为空。")
        mime_type = normalize_image_mime_type(attachment.mime_type)
        validate_image_signature(content, mime_type)
        return content, mime_type

    def save_uploaded_image(
        self,
        project_id: str,
        session_id: str,
        *,
        filename: str | None,
        mime_type: str,
        data_base64: str,
        source_kind: str,
        source_path: str | None = None,
    ) -> ChatImageRef:
        normalized_mime_type = normalize_image_mime_type(mime_type)
        try:
            content = b64decode(data_base64, validate=True)
        except (Base64Error, ValueError) as exc:
            raise BadRequestError("图片数据不是有效的 Base64 内容。") from exc
        if not content:
            raise BadRequestError("图片内容为空。")
        validate_image_signature(content, normalized_mime_type)
        display_name = Path(filename or "image").name or "image"
        attachment = self._repository.save_bytes(
            project_id,
            session_id,
            content=content,
            suffix=Path(display_name).suffix,
            display_name=display_name,
            mime_type=normalized_mime_type,
            source_kind=source_kind,
            source_path=source_path,
            created_at=datetime.now(UTC).isoformat(),
        )
        return ChatImageRef(
            path=attachment.uri,
            mime_type=attachment.mime_type,
            detail="auto",
            name=attachment.display_name,
            size_bytes=attachment.size_bytes,
            attachment_id=attachment.attachment_id,
            source_path=attachment.source_path,
            source_kind=attachment.source_kind,
        )


def normalize_image_mime_type(value: str) -> str:
    mime_type = value.split(";", 1)[0].strip().lower()
    if mime_type not in _SUPPORTED_IMAGE_MIME_TYPES:
        raise BadRequestError("仅支持 PNG、JPEG、WebP、GIF 或 BMP 图片。")
    return mime_type


def validate_image_signature(content: bytes, mime_type: str) -> None:
    is_valid = (
        (mime_type == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n"))
        or (mime_type == "image/jpeg" and content.startswith(b"\xff\xd8\xff"))
        or (mime_type == "image/gif" and content.startswith((b"GIF87a", b"GIF89a")))
        or (
            mime_type == "image/webp"
            and len(content) >= 12
            and content[:4] == b"RIFF"
            and content[8:12] == b"WEBP"
        )
        or (mime_type == "image/bmp" and content.startswith(b"BM"))
    )
    if not is_valid:
        raise BadRequestError("图片内容和图片类型不匹配。")


def get_conversation_attachment_service() -> ConversationAttachmentService:
    return ConversationAttachmentService(
        get_conversation_attachment_repository(),
        get_project_service(),
        get_file_workspace_storage(),
    )


def _source_kind(path: str) -> str:
    return "external_file" if local_absolute_path(path) is not None else "workspace_file"
