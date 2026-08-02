from __future__ import annotations

from functools import lru_cache

from app.core.errors import BadRequestError
from app.domain.project.conversation_export import (
    ConversationExportContentSelection,
    ConversationExportFormat,
    ConversationExportRange,
    ConversationExportResult,
)
from app.infra.file_workspace import get_file_workspace_storage
from app.services.document_conversion import get_markdown_docx_service
from app.services.project import get_project_conversation_service, get_project_service

from .assembler import ConversationExportAssembler
from .assets import ConversationExportAssetCollector
from .renderers import ConversationExportRendererRegistry
from .storage import ConversationExportStorage


class ConversationExportService:
    def __init__(
        self,
        assembler: ConversationExportAssembler,
        asset_collector: ConversationExportAssetCollector,
        renderers: ConversationExportRendererRegistry,
        storage: ConversationExportStorage,
    ) -> None:
        self._assembler = assembler
        self._asset_collector = asset_collector
        self._renderers = renderers
        self._storage = storage

    def export(
        self,
        project_id: str,
        session_id: str,
        *,
        export_format: ConversationExportFormat,
        export_range: ConversationExportRange,
        message_id: str | None,
        content_selection: ConversationExportContentSelection,
        target_directory: str,
        base_name: str,
        open_after_export: bool,
    ) -> ConversationExportResult:
        if not content_selection.has_supported_content(export_format):
            raise BadRequestError("至少选择一项当前格式支持的导出内容。")

        document = self._assembler.assemble(
            project_id,
            session_id,
            export_range=export_range,
            message_id=message_id,
        )
        supports_images = export_format not in {
            ConversationExportFormat.TXT,
            ConversationExportFormat.JSON,
        }
        prepared, asset_warnings = self._asset_collector.prepare(
            document,
            include_images=content_selection.images and supports_images,
        )
        rendered = self._renderers.render(
            export_format,
            prepared,
            content_selection,
        )
        stored = self._storage.store(
            rendered,
            target_directory=target_directory,
            base_name=base_name,
        )
        warnings = (*asset_warnings, *rendered.warnings)
        if open_after_export:
            try:
                self._storage.open_export(stored.output_path)
            except BadRequestError as exc:
                warnings = (*warnings, f"文件已导出，但无法自动打开：{exc.message}")
        return ConversationExportResult(
            container_path=stored.container_path,
            output_path=stored.output_path,
            message_count=len(document.messages),
            warnings=warnings,
        )


@lru_cache
def get_conversation_export_service() -> ConversationExportService:
    file_storage = get_file_workspace_storage()
    return ConversationExportService(
        ConversationExportAssembler(
            get_project_conversation_service(),
            get_project_service(),
        ),
        ConversationExportAssetCollector(file_storage),
        ConversationExportRendererRegistry(get_markdown_docx_service()),
        ConversationExportStorage(file_storage),
    )
