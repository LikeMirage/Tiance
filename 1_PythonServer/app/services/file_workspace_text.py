from fastapi import status

from app.core.errors import AppError
from app.infra.file_workspace import FileWorkspaceStorage, TextFileReadLimitExceededError


MAX_EDITOR_TEXT_FILE_SIZE_BYTES = 20 * 1024 * 1024


def read_editor_text_file(
    storage: FileWorkspaceStorage,
    workspace_root: str,
    target_path: str,
) -> tuple[str, int]:
    """读取编辑器文本内容；超限时在读取正文前返回明确错误。"""

    try:
        return storage.read_text_file_limited(
            workspace_root,
            target_path,
            max_size_bytes=MAX_EDITOR_TEXT_FILE_SIZE_BYTES,
        )
    except TextFileReadLimitExceededError as exc:
        raise AppError(
            "文件过大，暂不支持在编辑器中打开。",
            code="editor_text_file_too_large",
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            details={
                "size_bytes": exc.size_bytes,
                "limit_bytes": exc.limit_bytes,
            },
        ) from exc
