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
from app.services.project.conversation_attachments import (
    ConversationAttachmentService,
    get_conversation_attachment_service,
    normalize_image_mime_type,
    validate_image_signature,
)
from app.repositories.project.conversation_attachment_repository import is_attachment_uri
from app.services.tools.tool_resource_uris import local_absolute_path

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
        attachment_service: ConversationAttachmentService | None = None,
    ) -> None:
        self._project_service = project_service
        self._file_storage = file_storage
        self._runtime_capabilities_service = runtime_capabilities_service
        self._attachment_service = attachment_service

    def prepare(self, request: ChatCompletionRequest) -> ChatCompletionRequest:
        """Keep only explicit image refs supported by the selected model."""
        if not self._supports_image_input(request):
            return _drop_image_ref_parts(request)
        if not _request_has_image_ref(request) or self._attachment_service is None:
            return request
        if not request.project_id or not request.session_id:
            raise BadRequestError("图片引用需要有效的项目和会话 ID。")
        return replace(
            request,
            messages=tuple(
                self._prepare_message(
                    request.project_id,
                    request.session_id,
                    message,
                )
                for message in request.messages
            ),
        )

    def resolve(self, request: ChatCompletionRequest) -> ChatCompletionRequest:
        if not _request_has_image_ref(request):
            return request
        if not request.project_id or not request.session_id:
            raise BadRequestError("图片引用需要有效的项目和会话 ID。")
        if self._attachment_service is not None:
            request = self.prepare(request)
        project = self._project_service.get_project(request.project_id)
        if project is None:
            raise NotFoundError(f"项目 '{request.project_id}' 不存在。")

        return replace(
            request,
            messages=tuple(
                self._resolve_message(
                    request.project_id,
                    request.session_id,
                    project.root_path,
                    message,
                )
                for message in request.messages
            ),
        )

    def _prepare_message(
        self,
        project_id: str,
        session_id: str,
        message: ChatMessage,
    ) -> ChatMessage:
        if not message.content_parts:
            return message
        assert self._attachment_service is not None
        external_file_paths = _external_file_reference_paths(message)
        return replace(
            message,
            content_parts=tuple(
                replace(
                    part,
                    image_ref=self._attachment_service.snapshot_image_ref(
                        project_id,
                        session_id,
                        part.image_ref,
                        source_kind=(
                            "external_file"
                            if part.image_ref.path in external_file_paths
                            else None
                        ),
                    ),
                )
                if part.type == ChatMessageContentPartType.IMAGE_REF
                and part.image_ref is not None
                else part
                for part in message.content_parts
            ),
        )

    def _resolve_message(
        self,
        project_id: str,
        session_id: str,
        project_root: str,
        message: ChatMessage,
    ) -> ChatMessage:
        if not message.content_parts:
            return message
        return replace(
            message,
            content_parts=tuple(
                self._resolve_part(project_id, session_id, project_root, part)
                for part in message.content_parts
            ),
        )

    def _resolve_part(
        self,
        project_id: str,
        session_id: str,
        project_root: str,
        part: ChatMessageContentPart,
    ) -> ChatMessageContentPart:
        if part.type != ChatMessageContentPartType.IMAGE_REF or part.image_ref is None:
            return part

        if self._attachment_service is not None and is_attachment_uri(part.image_ref.path):
            content, mime_type = self._attachment_service.read_image(
                project_id,
                session_id,
                part.image_ref,
            )
        else:
            image_path = (
                local_absolute_path(part.image_ref.path)
                or self._file_storage.resolve_file_path(project_root, part.image_ref.path)
            )
            if not image_path.is_file():
                raise NotFoundError("图片文件不存在。")
            content = image_path.read_bytes()
            if not content:
                raise BadRequestError("图片内容为空。")
            mime_type = normalize_image_mime_type(
                part.image_ref.mime_type or guess_type(str(image_path))[0] or ""
            )
            validate_image_signature(content, mime_type)
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


def _external_file_reference_paths(message: ChatMessage) -> set[str]:
    references = message.internal_metadata.get("conversation_references")
    if not isinstance(references, list):
        return set()
    paths: set[str] = set()
    for item in references:
        if not isinstance(item, dict) or item.get("type") != "file":
            continue
        reference = item.get("reference")
        if not isinstance(reference, dict):
            continue
        if reference.get("source") != "external_path" or reference.get("kind") != "file":
            continue
        file_path = reference.get("filePath")
        if isinstance(file_path, str) and file_path:
            paths.add(file_path)
    return paths


@lru_cache
def get_conversation_image_reference_resolver() -> ConversationImageReferenceResolver:
    return ConversationImageReferenceResolver(
        get_project_service(),
        get_file_workspace_storage(),
        get_llm_runtime_capabilities_service(),
        get_conversation_attachment_service(),
    )
