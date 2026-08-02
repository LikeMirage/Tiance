from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from json import loads
from pathlib import Path
from zipfile import is_zipfile

from PIL import Image
from docx import Document

from app.domain.llm.chat import (
    ChatImageRef,
    ChatMessageContentPart,
    ChatMessageContentPartType,
    ChatToolCall,
)
from app.domain.project import Project
from app.domain.project.project_conversation import (
    ProjectConversationMessage,
    ProjectConversationSession,
)
from app.infra.file_workspace import FileWorkspaceStorage
from app.services.conversation_export.assembler import (
    ConversationExportAssembler,
    select_conversation_export_messages,
)
from app.services.conversation_export.assets import ConversationExportAssetCollector
from app.domain.project.conversation_export import (
    ConversationExportContentSelection,
    ConversationExportDocument,
    ConversationExportFormat,
    ConversationExportRange,
)
from app.services.conversation_export.renderers import ConversationExportRendererRegistry
from app.services.conversation_export.service import ConversationExportService
from app.services.conversation_export.storage import ConversationExportStorage
from app.services.document_conversion import MarkdownDocxService


def test_message_ranges_use_the_exact_anchor_as_the_boundary() -> None:
    messages = (
        _message("system", "system-1", "system"),
        _message("user", "user-1", "question one"),
        _message(
            "assistant",
            "assistant-tool",
            "I will check.",
            tool_calls=(ChatToolCall("call-1", "lookup", '{"id": 1}'),),
        ),
        _message("tool", "tool-1", '{"tool":"lookup","ok":true,"result":"done"}'),
        _message("assistant", "assistant-1", "answer one"),
        _message("user", "user-2", "question two"),
        _message("assistant", "assistant-2", "answer two"),
    )

    current = select_conversation_export_messages(
        messages,
        export_range=ConversationExportRange.MESSAGE,
        message_id="assistant-1",
    )
    through = select_conversation_export_messages(
        messages,
        export_range=ConversationExportRange.THROUGH_MESSAGE,
        message_id="user-1",
    )
    onward = select_conversation_export_messages(
        messages,
        export_range=ConversationExportRange.FROM_MESSAGE,
        message_id="assistant-1",
    )

    assert [message.message_id for message in current] == ["assistant-1"]
    assert [message.message_id for message in through] == [
        "system-1",
        "user-1",
    ]
    assert [message.message_id for message in onward] == [
        "assistant-1",
        "user-2",
        "assistant-2",
    ]


def test_assembler_reads_complete_conversation_without_ui_or_page_limit(tmp_path: Path) -> None:
    messages = tuple(
        _message("user" if index % 2 == 0 else "assistant", f"message-{index}", str(index))
        for index in range(260)
    )
    session = _session(message_count=len(messages))
    conversation_service = _FakeConversationService(session, messages)
    assembler = ConversationExportAssembler(
        conversation_service,  # type: ignore[arg-type]
        _FakeProjectService(tmp_path),  # type: ignore[arg-type]
    )

    document = assembler.assemble(
        "project-1",
        session.session_id,
        export_range=ConversationExportRange.CONVERSATION,
        message_id=None,
    )

    assert len(document.messages) == 260
    assert document.messages[0].message_id == "message-0"
    assert document.messages[-1].message_id == "message-259"
    assert conversation_service.list_messages_calls == 1


def test_all_formats_export_real_files_and_markdown_uses_own_folder(tmp_path: Path) -> None:
    document = _document(
        tmp_path,
        (
            _message("user", "user-1", "Question"),
            _message("assistant", "assistant-1", "**Answer**", thinking_content="Reasoning"),
        ),
    )
    service = _export_service(document)

    for export_format in ConversationExportFormat:
        result = service.export(
            "project-1",
            document.session.session_id,
            export_format=export_format,
            export_range=ConversationExportRange.CONVERSATION,
            message_id=None,
            content_selection=_selection(thinking=True),
            target_directory=str(tmp_path),
            base_name=f"export-{export_format.value}",
            open_after_export=False,
        )
        assert result.output_path.is_file()
        assert result.message_count == 2
        if export_format == ConversationExportFormat.MARKDOWN:
            assert result.container_path.is_dir()
            assert result.output_path == result.container_path / "export-markdown.md"
            assert not (result.container_path / "assets").exists()
        else:
            assert result.container_path == result.output_path

    assert is_zipfile(tmp_path / "export-docx.docx")
    assert "Answer" in (tmp_path / "export-txt.txt").read_text(encoding="utf-8-sig")
    assert "<strong>Answer</strong>" in (tmp_path / "export-html.html").read_text(encoding="utf-8")
    assert loads((tmp_path / "export-json.json").read_text(encoding="utf-8"))["schema_version"] == 1


def test_markdown_exports_images_as_relative_assets(tmp_path: Path) -> None:
    image_path = tmp_path / "source.png"
    image_path.write_bytes(_png_bytes())
    message = _message(
        "user",
        "user-image",
        "See image",
        content_parts=(
            ChatMessageContentPart(
                type=ChatMessageContentPartType.IMAGE_REF,
                image_ref=ChatImageRef(
                    path="source.png",
                    mime_type="image/png",
                    name="source.png",
                ),
            ),
        ),
    )
    document = _document(tmp_path, (message,))

    result = _export_service(document).export(
        "project-1",
        document.session.session_id,
        export_format=ConversationExportFormat.MARKDOWN,
        export_range=ConversationExportRange.CONVERSATION,
        message_id=None,
        content_selection=_selection(),
        target_directory=str(tmp_path),
        base_name="portable",
        open_after_export=False,
    )

    markdown = result.output_path.read_text(encoding="utf-8")
    exported_assets = list((result.container_path / "assets").iterdir())
    assert len(exported_assets) == 1
    assert "(assets/image-001-source.png)" in markdown
    assert exported_assets[0].read_bytes() == image_path.read_bytes()


def test_markdown_rewrites_inline_images_to_portable_assets(tmp_path: Path) -> None:
    image_path = tmp_path / "inline.png"
    image_path.write_bytes(_png_bytes())
    document = _document(
        tmp_path,
        (_message("assistant", "assistant-image", "Before ![chart](inline.png) after"),),
    )

    result = _export_service(document).export(
        "project-1",
        document.session.session_id,
        export_format=ConversationExportFormat.MARKDOWN,
        export_range=ConversationExportRange.CONVERSATION,
        message_id=None,
        content_selection=_selection(),
        target_directory=str(tmp_path),
        base_name="inline-portable",
        open_after_export=False,
    )

    markdown = result.output_path.read_text(encoding="utf-8")
    assert "![chart](assets/image-001-inline.png)" in markdown
    assert markdown.count("![chart]") == 1
    assert (result.container_path / "assets" / "image-001-inline.png").is_file()


def test_word_embeds_conversation_image_assets(tmp_path: Path) -> None:
    image_path = tmp_path / "word-source.png"
    image_path.write_bytes(_png_bytes())
    document = _document(
        tmp_path,
        (
            _message(
                "user",
                "user-word-image",
                "Image attachment",
                content_parts=(
                    ChatMessageContentPart(
                        type=ChatMessageContentPartType.IMAGE_REF,
                        image_ref=ChatImageRef(path="word-source.png", name="word-source.png"),
                    ),
                ),
            ),
        ),
    )

    result = _export_service(document).export(
        "project-1",
        document.session.session_id,
        export_format=ConversationExportFormat.DOCX,
        export_range=ConversationExportRange.CONVERSATION,
        message_id=None,
        content_selection=_selection(),
        target_directory=str(tmp_path),
        base_name="word-image",
        open_after_export=False,
    )

    assert len(Document(result.output_path).inline_shapes) == 1


def test_json_respects_content_and_metadata_selection(tmp_path: Path) -> None:
    document = _document(
        tmp_path,
        (
            _message("user", "user-1", "Question"),
            _message("assistant", "assistant-1", "Answer", thinking_content="Secret reasoning"),
        ),
    )
    selection = replace(
        _selection(),
        assistant_content=False,
        thinking=False,
        message_metadata=False,
    )

    result = _export_service(document).export(
        "project-1",
        document.session.session_id,
        export_format=ConversationExportFormat.JSON,
        export_range=ConversationExportRange.CONVERSATION,
        message_id=None,
        content_selection=selection,
        target_directory=str(tmp_path),
        base_name="filtered",
        open_after_export=False,
    )
    payload = loads(result.output_path.read_text(encoding="utf-8"))

    assert payload["messages"] == [{"role": "user", "content": "Question"}]
    assert "Secret reasoning" not in result.output_path.read_text(encoding="utf-8")


def test_session_information_is_not_leaked_when_disabled(tmp_path: Path) -> None:
    document = _document(tmp_path, (_message("user", "user-1", "Question"),))
    result = _export_service(document).export(
        "project-1",
        document.session.session_id,
        export_format=ConversationExportFormat.MARKDOWN,
        export_range=ConversationExportRange.CONVERSATION,
        message_id=None,
        content_selection=replace(_selection(), session_info=False),
        target_directory=str(tmp_path),
        base_name="no-session-info",
        open_after_export=False,
    )

    markdown = result.output_path.read_text(encoding="utf-8")
    assert "Export Test" not in markdown
    assert "session-1" not in markdown
    assert "Question" in markdown


def test_export_never_overwrites_existing_file_or_bundle(tmp_path: Path) -> None:
    document = _document(tmp_path, (_message("user", "user-1", "Question"),))
    service = _export_service(document)
    first_txt = service.export(
        "project-1",
        document.session.session_id,
        export_format=ConversationExportFormat.TXT,
        export_range=ConversationExportRange.CONVERSATION,
        message_id=None,
        content_selection=_selection(),
        target_directory=str(tmp_path),
        base_name="same",
        open_after_export=False,
    )
    second_txt = service.export(
        "project-1",
        document.session.session_id,
        export_format=ConversationExportFormat.TXT,
        export_range=ConversationExportRange.CONVERSATION,
        message_id=None,
        content_selection=_selection(),
        target_directory=str(tmp_path),
        base_name="same",
        open_after_export=False,
    )
    first_markdown = service.export(
        "project-1",
        document.session.session_id,
        export_format=ConversationExportFormat.MARKDOWN,
        export_range=ConversationExportRange.CONVERSATION,
        message_id=None,
        content_selection=_selection(),
        target_directory=str(tmp_path),
        base_name="bundle",
        open_after_export=False,
    )
    second_markdown = service.export(
        "project-1",
        document.session.session_id,
        export_format=ConversationExportFormat.MARKDOWN,
        export_range=ConversationExportRange.CONVERSATION,
        message_id=None,
        content_selection=_selection(),
        target_directory=str(tmp_path),
        base_name="bundle",
        open_after_export=False,
    )

    assert first_txt.output_path.name == "same.txt"
    assert second_txt.output_path.name == "same (2).txt"
    assert first_markdown.container_path.name == "bundle"
    assert second_markdown.container_path.name == "bundle (2)"
    assert second_markdown.output_path.name == "bundle (2).md"


class _StaticAssembler:
    def __init__(self, document: ConversationExportDocument) -> None:
        self._document = document

    def assemble(self, *_args, **_kwargs) -> ConversationExportDocument:
        return self._document


class _FakeConversationService:
    def __init__(
        self,
        session: ProjectConversationSession,
        messages: tuple[ProjectConversationMessage, ...],
    ) -> None:
        self._session = session
        self._messages = messages
        self.list_messages_calls = 0

    def get_session(self, _project_id: str, _session_id: str) -> ProjectConversationSession:
        return self._session

    def list_messages(
        self,
        _project_id: str,
        _session_id: str,
    ) -> tuple[ProjectConversationMessage, ...]:
        self.list_messages_calls += 1
        return self._messages


class _FakeProjectService:
    def __init__(self, root_path: Path) -> None:
        self._project = Project(
            project_id="project-1",
            name="Project",
            root_path=str(root_path),
            is_default=False,
            sort_order=0,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )

    def get_project(self, _project_id: str) -> Project:
        return self._project


def _export_service(document: ConversationExportDocument) -> ConversationExportService:
    file_storage = FileWorkspaceStorage()
    return ConversationExportService(
        _StaticAssembler(document),  # type: ignore[arg-type]
        ConversationExportAssetCollector(file_storage),
        ConversationExportRendererRegistry(MarkdownDocxService()),
        ConversationExportStorage(file_storage),
    )


def _document(
    project_root: Path,
    messages: tuple[ProjectConversationMessage, ...],
) -> ConversationExportDocument:
    return ConversationExportDocument(
        project_root=project_root,
        session=_session(message_count=len(messages)),
        messages=messages,
        export_range=ConversationExportRange.CONVERSATION,
        exported_at=datetime(2026, 7, 17, 3, 0, tzinfo=UTC),
    )


def _session(*, message_count: int) -> ProjectConversationSession:
    return ProjectConversationSession(
        session_id="session-1",
        sequence_number=1,
        title="Export Test",
        provider_id="provider",
        model_id="model",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        message_count=message_count,
    )


def _message(
    role: str,
    message_id: str,
    content: str,
    *,
    thinking_content: str = "",
    tool_calls: tuple[ChatToolCall, ...] = (),
    content_parts: tuple[ChatMessageContentPart, ...] = (),
) -> ProjectConversationMessage:
    return ProjectConversationMessage(
        message_id=message_id,
        session_id="session-1",
        role=role,
        content=content,
        thinking_content=thinking_content,
        usage={"total_tokens": 12} if role == "assistant" else None,
        provider_id="provider" if role != "user" else None,
        model_id="model" if role != "user" else None,
        status="done",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        tool_calls=tool_calls,
        content_parts=content_parts,
    )


def _selection(**updates: bool) -> ConversationExportContentSelection:
    selection = ConversationExportContentSelection(
        session_info=True,
        assistant_content=True,
        user_messages=True,
        thinking=False,
        tool_calls=False,
        tool_results=False,
        error_messages=True,
        system_messages=False,
        timestamps=False,
        images=True,
        model_info=False,
        token_usage=False,
        message_metadata=False,
    )
    return replace(selection, **updates)


def _png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (2, 2), (255, 120, 0)).save(output, format="PNG")
    return output.getvalue()
