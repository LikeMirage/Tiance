from base64 import b64decode, b64encode
from dataclasses import replace
from io import BytesIO

from PIL import Image
from app.domain.llm.chat import (
    ChatImageRef,
    ChatImageUrl,
    ChatCompletionRequest,
    ChatMessage,
    ChatMessageContentPart,
    ChatMessageContentPartType,
    ChatMessageRole,
)
from app.domain.project import Project
from app.infra.file_workspace import FileWorkspaceStorage
from app.services.project.conversation_image_references import ConversationImageReferenceResolver


PNG = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


def test_resolve_image_ref_to_temporary_data_url(tmp_path):
    image_path = tmp_path / "image.png"
    image_path.write_bytes(PNG)
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
    image_path.write_bytes(PNG + b"x" * (25 * 1024 * 1024 + 1))
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
    image_path.write_bytes(PNG)
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


def test_history_is_prepared_for_each_models_limit_and_logged(tmp_path):
    from app.domain.llm.runtime_capabilities import MultiImageLimit, LlmRuntimeCapabilities
    from app.services.project.conversation_model_exchange import build_model_exchange_record

    class Capabilities:
        input_modalities = ("text", "image")
        image_limit_for_count = LlmRuntimeCapabilities.image_limit_for_count
        multi_image_limit = MultiImageLimit(2, 24)

        def get_capabilities(self, *, provider_id, model_id):
            self.image_max_long_edge_px = {"first": 40, "second": 120}[model_id]
            return self

    path = tmp_path / "original.png"
    Image.new("RGB", (100, 50), (8, 5, 3)).save(path)
    source = path.read_bytes()
    part = ChatMessageContentPart(type=ChatMessageContentPartType.IMAGE_REF, image_ref=ChatImageRef(path=path.name))
    user = ChatMessage(role=ChatMessageRole.USER, content="查看图片", content_parts=(part,))
    original = ChatCompletionRequest("provider", "first", (user,), project_id="project", session_id="session")
    resolver = ConversationImageReferenceResolver(_ProjectServiceStub(str(tmp_path)), FileWorkspaceStorage(), Capabilities())
    inline = ChatMessageContentPart(type=ChatMessageContentPartType.IMAGE_URL, image_url=ChatImageUrl(
        "data:image/png;base64," + b64encode(source).decode("ascii")))
    for request, expected in (
        (original, (40, 20)),
        (replace(original, model_id="second"), (100, 50)),
        (replace(original, messages=(user, replace(user, content_parts=(inline,)))), (24, 12)),
    ):
        resolved = resolver.resolve(request)
        log = build_model_exchange_record(resolved, None, round_index=1, usage=None)["request"]["image_deliveries"]
        for msg, entry in zip(resolved.messages, log, strict=True):
            image_url = msg.content_parts[-1].image_url.url
            with Image.open(BytesIO(b64decode(image_url.split(",", 1)[1]))) as output:
                assert output.size == expected
            assert (entry["sent_width"], entry["sent_height"]) == expected
            assert (entry["source_width"], entry["source_height"]) == (100, 50)
    assert path.read_bytes() == source
    assert user.content_parts == (part,)


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

    def image_limit_for_count(self, count: int) -> int:
        return 8192
