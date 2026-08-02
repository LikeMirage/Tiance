from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory

from .converter import convert_markdown_to_docx
from .word_formatting import FontSettings
from .word_page_layout import DEFAULT_PAGE_ORIENTATION, DEFAULT_PAGE_SIZE


@dataclass(frozen=True, slots=True)
class MarkdownDocxResult:
    content: bytes
    warnings: tuple[str, ...]


class MarkdownDocxService:
    """将 Markdown 内容转换为 DOCX，不负责业务路径、命名或持久化。"""

    def convert(
        self,
        markdown: str,
        *,
        base_path: Path,
        fonts: FontSettings | None = None,
        page_orientation: str = DEFAULT_PAGE_ORIENTATION,
        page_size: str = DEFAULT_PAGE_SIZE,
    ) -> MarkdownDocxResult:
        with TemporaryDirectory(prefix="tiance-markdown-docx-") as temp_dir:
            output_path = Path(temp_dir) / "document.docx"
            warnings = convert_markdown_to_docx(
                markdown,
                output_path,
                base_path=base_path,
                fonts=fonts,
                page_orientation=page_orientation,
                page_size=page_size,
            )
            content = output_path.read_bytes()
        return MarkdownDocxResult(
            content=content,
            warnings=tuple(warnings),
        )


@lru_cache
def get_markdown_docx_service() -> MarkdownDocxService:
    return MarkdownDocxService()
