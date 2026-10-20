"""Budgets for disposable editor projections, never limits on source files/tools."""
from pathlib import Path

MIB = 1024 * 1024
MAX_EDITOR_TEXT_FILE_SIZE_BYTES = 20 * MIB
MAX_PACKAGE_BYTES = 64 * MIB
MAX_EXPANDED_BYTES = 256 * MIB
MAX_PACKAGE_ENTRIES = 4096
MAX_XML_NODES = 2_000_000
MAX_IMAGE_PIXELS = 24_000_000
MAX_IMAGE_BYTES = 32 * MIB
MAX_RENDER_XML_BYTES = 4 * MIB
MAX_RENDER_NODES = 20_000
MAX_RENDER_PACKAGE_BYTES = 32 * MIB
MAX_WORD_PARAGRAPHS = 1500
MAX_WORD_TABLE_CELLS = 2000
MAX_PRESENTATION_SLIDES = 40
MAX_SVG_BYTES = MIB
MAX_INLINE_CELLS = 20_000
MAX_INLINE_MERGES = 128
MAX_DELIMITED_BYTES = 256 * MIB
MAX_DELIMITED_RECORD_CHARS = MIB
MAX_DELIMITED_ROWS = 1_048_576
MAX_DELIMITED_COLUMNS = 16_384
PAGE_ROWS = 50
PAGE_COLUMNS = 20
MAX_RESULT_BYTES = 4 * MIB
PROCESS_SECONDS = 30
QUEUE_SECONDS = 30
MAX_PROCESSES = 2
MAX_XML_TOKEN_BYTES = MIB
DATABASE_QUERY_SECONDS = 10.0
DATABASE_RESULT_BYTES = 4 * MIB
DATABASE_OBJECTS = 2000


class PreviewLimit(ValueError):
    pass


def version(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_dev:x}-{stat.st_ino:x}-{stat.st_mtime_ns:x}-{stat.st_size:x}"


def require_version(path: Path, expected: str | None) -> str:
    current = version(path)
    if expected is not None and current != expected:
        raise ValueError("文件已变化，请重新加载预览。")
    return current
