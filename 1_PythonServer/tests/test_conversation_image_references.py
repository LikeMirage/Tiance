from app.domain.llm.chat import (
    ChatImageRef,
    ChatCompletionRequest,
    ChatMessage,
    ChatMessageContentPart,
    ChatMessageContentPartType,
    ChatMessageRole,
)
from app.domain.project import Project
from app.infra.file_workspace import FileWorkspaceStorage
from app.services.project.conversation_image_references import ConversationImageReferenceResolver


def test_resolve_image_ref_to_temporary_data_url(tmp_path):
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nimage")
    resolver = ConversationImageReferenceResolver(
        _ProjectServiceStub(str(tmp_path)),
        FileWorkspaceStorage(),
    )
    request = ChatCompletionRequest(
        provider_id="provider",
        model_id="vision",
        project_id="project-1",
        session_id="session-1",
        messages=(
            ChatMessage(
                role=ChatMessageRole.USER,
                content="来源说明保持在文本里",
                content_parts=(
                    ChatMessageContentPart(
                        type=ChatMessageContentPartType.IMAGE_REF,
                        image_ref=ChatImageRef(
                            path="image.png",
                            mime_type="image/png",
                            detail="auto",
                            name="image.png",
                            size_bytes=image_path.stat().st_size,
                        ),
                    ),
                ),
            ),
        ),
    )

    resolved = resolver.resolve(request)

    assert request.messages[0].content_parts[0].type == ChatMessageContentPartType.IMAGE_REF
    resolved_part = resolved.messages[0].content_parts[0]
    assert resolved_part.type == ChatMessageContentPartType.IMAGE_URL
    assert resolved_part.image_url is not None
    assert resolved_part.image_url.detail == "auto"
    assert resolved_part.image_url.url.startswith("data:image/png;base64,")


def test_prepare_does_not_infer_image_reference_from_user_text(tmp_path):
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nimage")
    resolver = ConversationImageReferenceResolver(
        _ProjectServiceStub(str(tmp_path)),
        FileWorkspaceStorage(),
        _RuntimeCapabilitiesServiceStub(("text", "image")),
    )
    request = ChatCompletionRequest(
        provider_id="provider",
        model_id="vision",
        project_id="project-1",
        session_id="session-1",
        messages=(
            ChatMessage(
                role=ChatMessageRole.USER,
                content=(
                    "【用户引用内容】\n"
                    "1. 【图片引用】\n"
                    "- 名称：image.png\n"
                    "- 图片路径：image.png\n\n"
                    "【用户消息】\n这是什么"
                ),
            ),
        ),
    )

    prepared = resolver.prepare(request)

    assert prepared.messages[0].content == request.messages[0].content
    assert prepared.messages[0].content_parts == ()


def test_prepare_and_resolve_image_reference_has_no_legacy_25mb_limit(tmp_path):
    image_path = tmp_path / "large.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * (25 * 1024 * 1024 + 1))
    resolver = ConversationImageReferenceResolver(
        _ProjectServiceStub(str(tmp_path)),
        FileWorkspaceStorage(),
        _RuntimeCapabilitiesServiceStub(("text", "image")),
    )
    request = ChatCompletionRequest(
        provider_id="provider",
        model_id="vision",
        project_id="project-1",
        session_id="session-1",
        messages=(
            ChatMessage(
                role=ChatMessageRole.USER,
                content="- 图片路径：large.png\n\n这是什么",
                content_parts=(
                    ChatMessageContentPart(
                        type=ChatMessageContentPartType.IMAGE_REF,
                        image_ref=ChatImageRef(
                            path="large.png",
                            mime_type="image/png",
                            size_bytes=image_path.stat().st_size,
                        ),
                    ),
                ),
            ),
        ),
    )

    prepared = resolver.prepare(request)
    resolved = resolver.resolve(prepared)

    prepared_part = prepared.messages[0].content_parts[0]
    assert prepared_part.image_ref is not None
    assert prepared_part.image_ref.size_bytes == image_path.stat().st_size
    resolved_part = resolved.messages[0].content_parts[0]
    assert resolved_part.type == ChatMessageContentPartType.IMAGE_URL
    assert resolved_part.image_url is not None
    assert resolved_part.image_url.url.startswith("data:image/png;base64,")


def test_prepare_keeps_text_only_for_non_vision_model(tmp_path):
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nimage")
    resolver = ConversationImageReferenceResolver(
        _ProjectServiceStub(str(tmp_path)),
        FileWorkspaceStorage(),
        _RuntimeCapabilitiesServiceStub(("text",)),
    )
    request = ChatCompletionRequest(
        provider_id="provider",
        model_id="text-only",
        project_id="project-1",
        session_id="session-1",
        messages=(
            ChatMessage(
                role=ChatMessageRole.USER,
                content="- 图片路径：image.png\n\n这是什么",
                content_parts=(
                    ChatMessageContentPart(
                        type=ChatMessageContentPartType.IMAGE_REF,
                        image_ref=ChatImageRef(path="image.png", mime_type="image/png"),
                    ),
                ),
            ),
        ),
    )

    prepared = resolver.prepare(request)

    assert prepared.messages[0].content == request.messages[0].content
    assert prepared.messages[0].content_parts == ()


def test_resolve_local_image_resource_outside_project(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    image_path = tmp_path / "outside.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nimage")
    local_uri = f"tiance-local:{image_path.as_uri().removeprefix('file:')}"
    resolver = ConversationImageReferenceResolver(
        _ProjectServiceStub(str(project_root)),
        FileWorkspaceStorage(),
    )
    request = ChatCompletionRequest(
        provider_id="provider",
        model_id="vision",
        project_id="project-1",
        session_id="session-1",
        messages=(
            ChatMessage(
                role=ChatMessageRole.USER,
                content="读取外部图片",
                content_parts=(
                    ChatMessageContentPart(
                        type=ChatMessageContentPartType.IMAGE_REF,
                        image_ref=ChatImageRef(path=local_uri, mime_type="image/png"),
                    ),
                ),
            ),
        ),
    )

    resolved = resolver.resolve(request)

    resolved_part = resolved.messages[0].content_parts[0]
    assert resolved_part.type == ChatMessageContentPartType.IMAGE_URL
    assert resolved_part.image_url is not None
    assert resolved_part.image_url.url.startswith("data:image/png;base64,")


class _ProjectServiceStub:
    def __init__(self, root_path: str) -> None:
        self._root_path = root_path

    def get_project(self, project_id: str):
        return Project(
            project_id=project_id,
            name="Test",
            root_path=self._root_path,
            is_default=False,
            sort_order=0,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )


class _RuntimeCapabilitiesServiceStub:
    def __init__(self, input_modalities: tuple[str, ...]) -> None:
        self._input_modalities = input_modalities

    def get_capabilities(self, *, provider_id: str, model_id: str | None = None):
        return _RuntimeCapabilitiesStub(self._input_modalities)


class _RuntimeCapabilitiesStub:
    def __init__(self, input_modalities: tuple[str, ...]) -> None:
        self.input_modalities = input_modalities
