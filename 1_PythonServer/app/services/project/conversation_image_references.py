from dataclasses import replace
from functools import lru_cache
from mimetypes import guess_type
from typing import Protocol

from app.core.errors import BadRequestError, NotFoundError
from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatImageRef,
    ChatMessage,
    ChatMessageContentPartType,
)
from app.domain.llm.runtime_capabilities import DEFAULT_IMAGE_MAX_LONG_EDGE_PX, LlmRuntimeCapabilities
from app.services.llm.chat.prompt_images import prepare_request_images, request_image_count
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
        """Snapshot explicit model inputs at their original resolution for history."""
        if not request_image_count(request):
            return request
        if not self._supports_image_input(request):
            return _drop_image_parts(request)
        if self._attachment_service is None:
            return request
        if not request.project_id or not request.session_id:
            if not _request_has_image_ref(request):
                return request
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
        count = request_image_count(request)
        if not count:
            return request
        limit = DEFAULT_IMAGE_MAX_LONG_EDGE_PX
        if self._runtime_capabilities_service is not None:
            capabilities = self._runtime_capabilities_service.get_capabilities(
                provider_id=request.provider_id, model_id=request.model_id,
            )
            if "image" not in capabilities.input_modalities:
                return _drop_image_parts(request)
            limit = capabilities.image_limit_for_count(count)
        if not _request_has_image_ref(request):
            return prepare_request_images(request, limit)
        project_id, session_id = request.project_id, request.session_id
        if not project_id or not session_id:
            raise BadRequestError("图片引用需要有效的项目和会话 ID。")
        project = self._project_service.get_project(project_id)
        if project is None:
            raise NotFoundError(f"项目 '{project_id}' 不存在。")
        if self._attachment_service is not None:
            request = replace(request, messages=tuple(
                self._prepare_message(project_id, session_id, message) for message in request.messages
            ))
        return prepare_request_images(
            request, limit,
            read_ref=lambda ref: self._read_reference(project_id, session_id, project.root_path, ref),
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
        parts = []
        for part in message.content_parts:
            if part.type == ChatMessageContentPartType.IMAGE_REF and part.image_ref is not None:
                ref = self._attachment_service.snapshot_image_ref(
                    project_id, session_id, part.image_ref,
                    source_kind="external_file" if part.image_ref.path in external_file_paths else None,
                )
                part = replace(part, image_ref=ref)
            elif part.type == ChatMessageContentPartType.IMAGE_URL and part.image_url is not None:
                ref = self._attachment_service.snapshot_image_url(project_id, session_id, part.image_url)
                part = replace(part, type=ChatMessageContentPartType.IMAGE_REF, image_url=None, image_ref=ref)
            parts.append(part)
        return replace(message, content_parts=tuple(parts))

    def _read_reference(self, project_id: str, session_id: str, root: str, ref: ChatImageRef) -> bytes:
        if self._attachment_service is not None and is_attachment_uri(ref.path):
            content, _ = self._attachment_service.read_image(project_id, session_id, ref)
            return content
        path = local_absolute_path(ref.path) or self._file_storage.resolve_file_path(root, ref.path)
        if not path.is_file():
            raise NotFoundError("图片文件不存在。")
        content = path.read_bytes()
        mime = normalize_image_mime_type(ref.mime_type or guess_type(str(path))[0] or "")
        validate_image_signature(content, mime)
        return content

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


def _drop_image_parts(request: ChatCompletionRequest) -> ChatCompletionRequest:
    if not request_image_count(request):
        return request
    return replace(
        request,
        messages=tuple(
            replace(
                message,
                content_parts=tuple(
                    part
                    for part in message.content_parts
                    if part.type not in (ChatMessageContentPartType.IMAGE_REF, ChatMessageContentPartType.IMAGE_URL)
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
