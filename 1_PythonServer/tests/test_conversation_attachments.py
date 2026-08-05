from datetime import UTC, datetime

from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatImageRef,
    ChatMessage,
    ChatMessageContentPart,
    ChatMessageContentPartType,
    ChatMessageRole,
)
from app.domain.project import Project
from app.infra.file_workspace import FileWorkspaceStorage
from app.repositories.project.conversation_attachment_repository import (
    ATTACHMENTS_DIR,
    ConversationAttachmentRepository,
)
from app.repositories.project.conversation_repository import ProjectConversationRepository
from app.services.project.conversation_attachments import ConversationAttachmentService
from app.services.project.conversation_image_references import ConversationImageReferenceResolver

PROJECT_ID = "project-attachment-test"


def test_image_is_copied_to_session_and_remains_readable_after_source_delete(tmp_path):
    repository = ProjectConversationRepository(_ProjectRepository(str(tmp_path)))
    session = repository.create_session(
        PROJECT_ID,
        title="附件测试",
        provider_id="provider",
        model_id="model",
        reasoning_mode="balanced",
    )
    source = tmp_path / "source.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\nsource")

    attachment_service = ConversationAttachmentService(
        ConversationAttachmentRepository(_ProjectRepository(str(tmp_path))),
        _ProjectService(str(tmp_path)),
        FileWorkspaceStorage(),
    )
    resolver = ConversationImageReferenceResolver(
        _ProjectService(str(tmp_path)),
        FileWorkspaceStorage(),
        attachment_service=attachment_service,
    )
    request = ChatCompletionRequest(
        provider_id="provider",
        model_id="vision",
        project_id=PROJECT_ID,
        session_id=session.session_id,
        messages=(
            ChatMessage(
                role=ChatMessageRole.USER,
                content="看图",
                content_parts=(
                    ChatMessageContentPart(
                        type=ChatMessageContentPartType.IMAGE_REF,
                        image_ref=ChatImageRef(
                            path="source.png",
                            mime_type="image/png",
                            source_path=str(source),
                        ),
                    ),
                ),
            ),
        ),
    )

    prepared = resolver.prepare(request)
    attachment_uri = prepared.messages[0].content_parts[0].image_ref.path
    source.unlink()
    resolved = resolver.resolve(prepared)

    assert attachment_uri.startswith("tiance-attachment://att_")
    assert resolved.messages[0].content_parts[0].type == ChatMessageContentPartType.IMAGE_URL
    assert (tmp_path / ".Tiance" / "conversations" / "sessions" / session.session_id / ATTACHMENTS_DIR).is_dir()


def test_fork_copies_inherited_session_attachment(tmp_path):
    project_repository = _ProjectRepository(str(tmp_path))
    conversation_repository = ProjectConversationRepository(project_repository)
    session = conversation_repository.create_session(
        PROJECT_ID,
        title="源会话",
        provider_id="provider",
        model_id="model",
        reasoning_mode="balanced",
    )
    attachment_repository = ConversationAttachmentRepository(project_repository)
    attachment = attachment_repository.save_bytes(
        PROJECT_ID,
        session.session_id,
        content=b"\x89PNG\r\n\x1a\nsource",
        suffix=".png",
        display_name="source.png",
        mime_type="image/png",
        source_kind="external_file",
        source_path="C:/source.png",
        created_at=datetime.now(UTC).isoformat(),
    )
    part = ChatMessageContentPart(
        type=ChatMessageContentPartType.IMAGE_REF,
        image_ref=ChatImageRef(
            path=attachment.uri,
            mime_type="image/png",
            attachment_id=attachment.attachment_id,
        ),
    )
    conversation_repository.append_message(
        PROJECT_ID,
        session.session_id,
        role="user",
        content="第一条",
        content_parts=(part,),
    )
    conversation_repository.append_message(
        PROJECT_ID,
        session.session_id,
        role="assistant",
        content="已看到",
    )
    source_message = conversation_repository.append_message(
        PROJECT_ID,
        session.session_id,
        role="user",
        content="从这里分支",
    )
    conversation_repository.save_session_runtime_status(
        PROJECT_ID,
        session.session_id,
        "idle",
    )

    fork = conversation_repository.fork_session(
        PROJECT_ID,
        session.session_id,
        source_message_id=source_message.message_id,
        draft="",
        references=[],
    )
    target_attachment = (
        tmp_path
        / ".Tiance"
        / "conversations"
        / "sessions"
        / fork.session.session_id
        / ATTACHMENTS_DIR
        / attachment.stored_name
    )
    assert target_attachment.is_file()
    assert target_attachment.read_bytes() == b"\x89PNG\r\n\x1a\nsource"


class _ProjectRepository:
    def __init__(self, root_path: str):
        now = datetime.now(UTC).isoformat()
        self.project = Project(
            project_id=PROJECT_ID,
            name="attachment-test",
            root_path=root_path,
            is_default=False,
            sort_order=0,
            created_at=now,
            updated_at=now,
        )

    def get_project(self, project_id: str):
        return self.project if project_id == PROJECT_ID else None


class _ProjectService:
    def __init__(self, root_path: str):
        self._project = _ProjectRepository(root_path).project

    def get_project(self, project_id: str):
        return self._project if project_id == PROJECT_ID else None
