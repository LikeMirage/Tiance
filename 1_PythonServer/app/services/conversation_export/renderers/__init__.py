from __future__ import annotations

from app.core.errors import BadRequestError
from app.domain.project.conversation_export import (
    ConversationExportContentSelection,
    ConversationExportFormat,
    PreparedConversationExport,
    RenderedConversationExport,
)
from app.services.document_conversion import MarkdownDocxService

from .html import HtmlConversationExportRenderer
from .json import JsonConversationExportRenderer
from .markdown import MarkdownConversationExportRenderer
from .text import TextConversationExportRenderer
from .word import WordConversationExportRenderer


class ConversationExportRendererRegistry:
    def __init__(self, markdown_docx: MarkdownDocxService) -> None:
        self._renderers = {
            ConversationExportFormat.DOCX: WordConversationExportRenderer(markdown_docx),
            ConversationExportFormat.MARKDOWN: MarkdownConversationExportRenderer(),
            ConversationExportFormat.TXT: TextConversationExportRenderer(),
            ConversationExportFormat.HTML: HtmlConversationExportRenderer(),
            ConversationExportFormat.JSON: JsonConversationExportRenderer(),
        }

    def render(
        self,
        export_format: ConversationExportFormat,
        prepared: PreparedConversationExport,
        selection: ConversationExportContentSelection,
    ) -> RenderedConversationExport:
        renderer = self._renderers.get(export_format)
        if renderer is None:
            raise BadRequestError("不支持的会话导出格式。")
        return renderer.render(prepared, selection)


__all__ = ["ConversationExportRendererRegistry"]
