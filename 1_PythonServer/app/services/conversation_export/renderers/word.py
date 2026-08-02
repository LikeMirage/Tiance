from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from app.domain.project.conversation_export import (
    ConversationExportContentSelection,
    PreparedConversationExport,
    RenderedConversationExport,
)
from app.services.document_conversion import MarkdownDocxService

from .markdown import build_conversation_markdown


class WordConversationExportRenderer:
    def __init__(self, markdown_docx: MarkdownDocxService) -> None:
        self._markdown_docx = markdown_docx

    def render(
        self,
        prepared: PreparedConversationExport,
        selection: ConversationExportContentSelection,
    ) -> RenderedConversationExport:
        markdown = build_conversation_markdown(prepared, selection)
        with TemporaryDirectory(prefix="tiance-conversation-word-") as temp_dir:
            base_path = Path(temp_dir)
            assets_dir = base_path / "assets"
            unique_assets = {
                image.asset_name: image.content
                for image in prepared.images
            }
            if unique_assets:
                assets_dir.mkdir()
                for asset_name, content in unique_assets.items():
                    (assets_dir / asset_name).write_bytes(content)
            result = self._markdown_docx.convert(markdown, base_path=base_path)
        return RenderedConversationExport(
            content=result.content,
            extension=".docx",
            warnings=result.warnings,
        )
