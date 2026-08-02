from base64 import b64encode
from dataclasses import replace
from functools import lru_cache
from mimetypes import guess_type
from typing import Protocol

from app.core.errors import BadRequestError, NotFoundError
from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatImageUrl,
    ChatMessage,
    ChatMessageContentPart,
    ChatMessageContentPartType,
)
from app.domain.llm.runtime_capabilities import LlmRuntimeCapabilities
from app.infra.file_workspace import FileWorkspaceStorage, get_file_workspace_storage
from app.services.llm.runtime import get_llm_runtime_capabilities_service
from app.services.project.projects import ProjectService, get_project_service
from app.services.tools.tool_resource_uris import local_absolute_path

_SUPPORTED_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "image/bmp",
}
class _RuntimeCapabilitiesProvider(Protocol):
    def get_capabilities(
        self,
        *,
        provider_id: str,
        model_id: str | None = None,
    ) -> LlmRuntimeCapabilities:
        ...


class ConversationImageReferenceResolver:
    def __init__(
        self,
        project_service: ProjectService,
        file_storage: FileWorkspaceStorage,
        runtime_capabilities_service: _RuntimeCapabilitiesProvider | None = None,
    ) -> None:
        self._project_service = project_service
        self._file_storage = file_storage
        self._runtime_capabilities_service = runtime_capabilities_service

    def prepare(self, request: ChatCompletionRequest) -> ChatCompletionRequest:
        """Keep only explicit image refs supported by the selected model."""
        if not self._supports_image_input(request):
            return _drop_image_ref_parts(request)
        return request

    def resolve(self, request: ChatCompletionRequest) -> ChatCompletionRequest:
        if not _request_has_image_ref(request):
            return request
        if not request.project_id:
            raise BadRequestError("图片引用需要有效的项目 ID。")
        project = self._project_service.get_project(request.project_id)
        if project is None:
            raise NotFoundError(f"项目 '{request.project_id}' 不存在。")

        return replace(
            request,
            messages=tuple(
                self._resolve_message(project.root_path, message)
                for message in request.messages
            ),
        )

    def _resolve_message(self, project_root: str, message: ChatMessage) -> ChatMessage:
        if not message.content_parts:
            return message
        return replace(
            message,
            content_parts=tuple(
                self._resolve_part(project_root, part)
                for part in message.content_parts
            ),
        )

    def _resolve_part(
        self,
        project_root: str,
        part: ChatMessageContentPart,
    ) -> ChatMessageContentPart:
        if part.type != ChatMessageContentPartType.IMAGE_REF or part.image_ref is None:
            return part

        image_path = (
            local_absolute_path(part.image_ref.path)
            or self._file_storage.resolve_file_path(project_root, part.image_ref.path)
        )
        if not image_path.is_file():
            raise NotFoundError("图片文件不存在。")
        size = image_path.stat().st_size
        if size <= 0:
            raise BadRequestError("图片内容为空。")

        content = image_path.read_bytes()
        mime_type = _normalize_image_mime_type(
            part.image_ref.mime_type
            or guess_type(str(image_path))[0]
            or ""
        )
        _validate_image_signature(content, mime_type)
        data_url = f"data:{mime_type};base64,{b64encode(content).decode('ascii')}"
        return ChatMessageContentPart(
            type=ChatMessageContentPartType.IMAGE_URL,
            image_url=ChatImageUrl(
                url=data_url,
                detail=part.image_ref.detail,
            ),
        )

    def _supports_image_input(self, request: ChatCompletionRequest) -> bool:
        if self._runtime_capabilities_service is None:
            return True
        capabilities = self._runtime_capabilities_service.get_capabilities(
            provider_id=request.provider_id,
            model_id=request.model_id,
        )
        return "image" in capabilities.input_modalities


def _request_has_image_ref(request: ChatCompletionRequest) -> bool:
    return any(
        part.type == ChatMessageContentPartType.IMAGE_REF and part.image_ref is not None
        for message in request.messages
        for part in message.content_parts
    )


def _drop_image_ref_parts(request: ChatCompletionRequest) -> ChatCompletionRequest:
    if not _request_has_image_ref(request):
        return request
    return replace(
        request,
        messages=tuple(
            replace(
                message,
                content_parts=tuple(
                    part
                    for part in message.content_parts
                    if part.type != ChatMessageContentPartType.IMAGE_REF
                ),
            )
            for message in request.messages
        ),
    )


def _normalize_image_mime_type(value: str) -> str:
    mime_type = value.split(";", 1)[0].strip().lower()
    if mime_type not in _SUPPORTED_IMAGE_MIME_TYPES:
        raise BadRequestError("仅支持 PNG、JPEG、WebP、GIF 或 BMP 图片。")
    return mime_type


def _validate_image_signature(content: bytes, mime_type: str) -> None:
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


@lru_cache
def get_conversation_image_reference_resolver() -> ConversationImageReferenceResolver:
    return ConversationImageReferenceResolver(
        get_project_service(),
        get_file_workspace_storage(),
        get_llm_runtime_capabilities_service(),
    )
