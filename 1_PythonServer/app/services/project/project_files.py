# 项目文件操作服务
# 验证项目存在后委托给 ProjectFileStorage 执行文件系统操作

import base64
import binascii
from datetime import datetime
from functools import lru_cache
from pathlib import PurePosixPath
from secrets import token_hex

from app.core.errors import BadRequestError, NotFoundError
from app.domain.file_workspace import FileEntryTree
from app.domain.project.project_file import ProjectFileKind, ProjectFileNode
from app.infra.file_workspace import FileWorkspaceStorage, get_file_workspace_storage
from app.infra.projects import require_existing_project_root, watch_project_file_changes
from app.repositories.project import ProjectRepository, get_project_repository
from app.services.document_conversion import (
    DEFAULT_PAGE_ORIENTATION,
    DEFAULT_PAGE_SIZE,
    MarkdownDocxService,
    get_markdown_docx_service,
)
from app.services.file_workspace_text import read_editor_text_file
from app.services.project.project_ids import normalize_project_id

_UPLOAD_ROOT_DIR = ".Tiance/conversation_references"
_UPLOAD_IMAGE_DIR = f"{_UPLOAD_ROOT_DIR}/images"
_UPLOAD_FILE_DIR = f"{_UPLOAD_ROOT_DIR}/files"
_IMAGE_MIME_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}
_GENERIC_UPLOAD_IMAGE_NAMES = {
    "blob",
    "clipboard",
    "image",
    "pasted_image",
}


class ProjectFileService:
    def __init__(
        self,
        repository: ProjectRepository,
        storage: FileWorkspaceStorage,
        markdown_docx: MarkdownDocxService,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._markdown_docx = markdown_docx

    def list_tree(
        self,
        project_id: str,
        *,
        query: str | None = None,
        parent_path: str | None = None,
    ) -> tuple[ProjectFileNode, ...]:
        """列出项目文件树；query 非空时递归搜索，否则只返回 parent_path 下一层"""
        return self.list_tree_result(project_id, query=query, parent_path=parent_path).items

    def list_tree_result(
        self,
        project_id: str,
        *,
        query: str | None = None,
        parent_path: str | None = None,
    ) -> FileEntryTree:
        """列出项目文件树。"""
        project_root = self._require_project_root(project_id)
        try:
            return self._storage.list_tree_result(
                project_root,
                query=query,
                parent_path=parent_path,
            )
        except FileNotFoundError as exc:
            raise BadRequestError(str(exc)) from exc
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc

    def get_project_root(self, project_id: str) -> str:
        """返回项目根目录，用于文件监听等跨请求能力。"""
        return self._require_project_root(project_id)

    def watch_file_changes(self, project_id: str):
        """监听项目文件变化，返回隔离后的状态与项目相对路径事件。"""
        project_root = self._require_project_root(project_id)
        return watch_project_file_changes(project_root, project_id=project_id)

    def create_entry(
        self,
        project_id: str,
        *,
        parent_path: str | None,
        kind: ProjectFileKind,
        name: str | None,
    ) -> ProjectFileNode:
        """在项目内创建文件或文件夹"""
        project_root = self._require_project_root(project_id)
        try:
            return self._storage.create_entry(
                project_root,
                parent_path=parent_path,
                kind=kind,
                name=name,
            )
        except FileExistsError as exc:
            raise BadRequestError("同名文件或文件夹已存在。") from exc
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc

    def rename_entry(
        self,
        project_id: str,
        *,
        target_path: str,
        name: str,
    ) -> ProjectFileNode:
        """重命名项目内的文件或文件夹"""
        project_root = self._require_project_root(project_id)
        try:
            return self._storage.rename_entry(
                project_root,
                target_path=target_path,
                name=name,
            )
        except FileNotFoundError as exc:
            raise BadRequestError(str(exc)) from exc
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc

    def read_text_file(self, project_id: str, target_path: str) -> tuple[str, int]:
        """读取项目内文本文件的内容和修改时间"""
        project_root = self._require_project_root(project_id)
        try:
            return self._storage.read_text_file(project_root, target_path)
        except FileNotFoundError as exc:
            raise NotFoundError(str(exc)) from exc
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc

    def read_editor_text_file(self, project_id: str, target_path: str) -> tuple[str, int]:
        """读取供编辑器展示的文本文件，并执行编辑器体积限制。"""
        project_root = self._require_project_root(project_id)
        try:
            return read_editor_text_file(self._storage, project_root, target_path)
        except FileNotFoundError as exc:
            raise NotFoundError(str(exc)) from exc
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc

    def get_file_path(self, project_id: str, target_path: str):
        """返回项目内受控文件路径，用于只读资源响应。"""
        project_root = self._require_project_root(project_id)
        try:
            return self._storage.resolve_file_path(project_root, target_path)
        except FileNotFoundError as exc:
            raise NotFoundError(str(exc)) from exc
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc

    def write_text_file(
        self,
        project_id: str,
        target_path: str,
        content: str,
        *,
        expected_mtime_ms: int | None = None,
    ) -> ProjectFileNode:
        """写入项目内文本文件"""
        project_root = self._require_project_root(project_id)
        try:
            return self._storage.write_text_file(
                project_root,
                target_path,
                content,
                expected_mtime_ms=expected_mtime_ms,
            )
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc

    def save_uploaded_image(
        self,
        project_id: str,
        *,
        filename: str | None,
        mime_type: str,
        data_base64: str,
    ) -> tuple[ProjectFileNode, str, int]:
        """保存输入区粘贴的图片到项目隐藏上传目录。"""
        project_root = self._require_project_root(project_id)
        normalized_mime_type = _normalize_image_mime_type(mime_type)
        content = _decode_upload_image(data_base64)
        _validate_image_signature(content, normalized_mime_type)
        extension = _IMAGE_MIME_EXTENSIONS[normalized_mime_type]
        target_path = _resolve_unique_upload_path(
            _UPLOAD_IMAGE_DIR,
            _build_upload_image_name(filename, extension),
            exists=lambda path: self._storage.entry_exists(project_root, path),
        )
        try:
            node = self._storage.write_binary_file(project_root, target_path, content)
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc
        return node, normalized_mime_type, len(content)

    def save_uploaded_file(
        self,
        project_id: str,
        *,
        filename: str,
        mime_type: str | None,
        data_base64: str,
    ) -> tuple[ProjectFileNode, str, str | None, int]:
        """保存用户拖入的文件到项目隐藏上传目录。"""
        project_root = self._require_project_root(project_id)
        safe_filename = _sanitize_upload_filename(filename)
        content = _decode_upload_base64(
            data_base64,
            empty_message="文件内容为空。",
        )
        target_path = _resolve_unique_upload_path(
            _UPLOAD_FILE_DIR,
            safe_filename,
            exists=lambda path: self._storage.entry_exists(project_root, path),
        )
        try:
            node = self._storage.write_binary_file(project_root, target_path, content)
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc
        return node, safe_filename, _normalize_optional_mime_type(mime_type), len(content)

    def delete_entry(self, project_id: str, target_path: str) -> None:
        """删除项目内的文件或文件夹"""
        project_root = self._require_project_root(project_id)
        try:
            self._storage.delete_entry(project_root, target_path)
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc

    def move_entry(
        self,
        project_id: str,
        *,
        target_path: str,
        target_parent_path: str | None,
    ) -> ProjectFileNode:
        """移动项目内的文件或文件夹"""
        project_root = self._require_project_root(project_id)
        try:
            return self._storage.move_entry(
                project_root,
                target_path=target_path,
                target_parent_path=target_parent_path,
            )
        except FileNotFoundError as exc:
            raise BadRequestError(str(exc)) from exc
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc

    def copy_entry(
        self,
        project_id: str,
        *,
        target_path: str,
        target_parent_path: str | None,
    ) -> ProjectFileNode:
        """复制项目内的文件或文件夹"""
        project_root = self._require_project_root(project_id)
        try:
            return self._storage.copy_entry(
                project_root,
                target_path=target_path,
                target_parent_path=target_parent_path,
            )
        except FileNotFoundError as exc:
            raise BadRequestError(str(exc)) from exc
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc

    def reveal_entry(self, project_id: str, target_path: str) -> None:
        """在系统资源管理器中显示项目内的文件或文件夹"""
        project_root = self._require_project_root(project_id)
        try:
            self._storage.reveal_entry(project_root, target_path)
        except FileNotFoundError as exc:
            raise BadRequestError(str(exc)) from exc
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc

    def open_entry_external(self, project_id: str, target_path: str):
        """用本机 Office/WPS 或系统默认程序打开项目内文件。"""
        project_root = self._require_project_root(project_id)
        try:
            return self._storage.open_entry_external(project_root, target_path)
        except FileNotFoundError as exc:
            raise BadRequestError(str(exc)) from exc
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc

    def convert_markdown_content_to_docx(
        self,
        project_id: str,
        *,
        target_path: str,
        content: str,
        page_orientation: str = DEFAULT_PAGE_ORIENTATION,
        page_size: str = DEFAULT_PAGE_SIZE,
    ) -> tuple[ProjectFileNode, tuple[str, ...]]:
        """用当前编辑器内容生成同目录 docx，不保存或改写源 Markdown。"""
        project_root = self._require_project_root(project_id)
        normalized_source_path = _normalize_markdown_source_path(target_path)
        try:
            source_file_path = self._storage.resolve_file_path(project_root, normalized_source_path)
            output_path = _resolve_unique_docx_target_path(
                normalized_source_path,
                exists=lambda path: self._storage.entry_exists(project_root, path),
            )
            result = self._markdown_docx.convert(
                content,
                base_path=source_file_path.parent,
                page_orientation=page_orientation,
                page_size=page_size,
            )
            node = self._storage.write_binary_file(
                project_root,
                output_path,
                result.content,
            )
        except FileNotFoundError as exc:
            raise NotFoundError(str(exc)) from exc
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc
        except Exception as exc:
            raise BadRequestError(f"Markdown 转 Word 失败：{exc}") from exc
        return node, result.warnings

    def _require_project_root(self, project_id: str) -> str:
        normalized_project_id = normalize_project_id(project_id)
        project = self._repository.get_project(normalized_project_id)
        if project is None:
            raise NotFoundError(f"项目 '{normalized_project_id}' 不存在。")
        return str(require_existing_project_root(project.root_path))


def _normalize_image_mime_type(mime_type: str) -> str:
    normalized = mime_type.split(";", 1)[0].strip().lower()
    if normalized not in _IMAGE_MIME_EXTENSIONS:
        raise BadRequestError("仅支持粘贴 PNG、JPEG、WebP、GIF 或 BMP 图片。")
    return normalized


def _decode_upload_image(data_base64: str) -> bytes:
    return _decode_upload_base64(
        data_base64,
        empty_message="图片内容为空。",
    )


def _decode_upload_base64(
    data_base64: str,
    *,
    empty_message: str,
    max_bytes: int | None = None,
    too_large_message: str | None = None,
) -> bytes:
    try:
        content = base64.b64decode(data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BadRequestError("上传数据不是有效的 base64 内容。") from exc
    if not content:
        raise BadRequestError(empty_message)
    if max_bytes is not None and len(content) > max_bytes:
        raise BadRequestError(too_large_message or "上传内容过大。")
    return content


def _validate_image_signature(content: bytes, mime_type: str) -> None:
    is_valid = (
        (mime_type == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n"))
        or (mime_type == "image/jpeg" and content.startswith(b"\xff\xd8\xff"))
        or (mime_type == "image/gif" and content.startswith((b"GIF87a", b"GIF89a")))
        or (mime_type == "image/webp" and len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP")
        or (mime_type == "image/bmp" and content.startswith(b"BM"))
    )
    if not is_valid:
        raise BadRequestError("图片内容和图片类型不匹配。")


def _build_upload_image_name(filename: str | None, extension: str) -> str:
    safe_filename = _sanitize_upload_image_filename(filename, extension)
    if safe_filename is not None:
        return safe_filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    return f"pasted_image_{timestamp}_{token_hex(4)}{extension}"


def _sanitize_upload_image_filename(filename: str | None, extension: str) -> str | None:
    if not filename:
        return None
    safe_filename = _sanitize_upload_filename(filename)
    path = PurePosixPath(safe_filename)
    stem = path.stem.strip(" .")
    if not stem or stem.lower() in _GENERIC_UPLOAD_IMAGE_NAMES:
        return None
    suffix = path.suffix.lower()
    if suffix not in set(_IMAGE_MIME_EXTENSIONS.values()):
        suffix = extension
    image_filename = f"{stem}{suffix}"
    return image_filename


def _sanitize_upload_filename(filename: str) -> str:
    leaf_name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    sanitized = "".join(_safe_upload_filename_character(character) for character in leaf_name)
    sanitized = " ".join(sanitized.split()).strip(" .")
    if not sanitized:
        sanitized = "uploaded_file"
    if sanitized in {".", ".."}:
        sanitized = "uploaded_file"
    return sanitized

def _safe_upload_filename_character(character: str) -> str:
    if ord(character) < 32 or character in '<>:"/\\|?*':
        return "_"
    return character


def _resolve_unique_upload_path(
    upload_dir: str,
    filename: str,
    *,
    exists,
) -> str:
    path = PurePosixPath(filename)
    stem = path.stem or "uploaded_file"
    suffix = path.suffix
    candidate = f"{upload_dir}/{stem}{suffix}"
    if not exists(candidate):
        return candidate
    for index in range(2, 1000):
        candidate = f"{upload_dir}/{stem}_{index}{suffix}"
        if not exists(candidate):
            return candidate
    return f"{upload_dir}/{stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{token_hex(4)}{suffix}"


def _normalize_markdown_source_path(target_path: str) -> str:
    normalized_path = str(PurePosixPath(target_path.replace("\\", "/")))
    if PurePosixPath(normalized_path).suffix.lower() not in {".md", ".markdown"}:
        raise BadRequestError("仅支持将 Markdown 文件生成 Word。")
    return normalized_path


def _resolve_unique_docx_target_path(
    source_path: str,
    *,
    exists,
) -> str:
    path = PurePosixPath(source_path)
    stem = path.stem.strip(" .") or "document"
    parent = path.parent
    index = 0
    while True:
        suffix = "" if index == 0 else f"_{index}"
        candidate = parent / f"{stem}{suffix}.docx"
        candidate_path = str(candidate)
        if candidate_path == ".":
            candidate_path = f"{stem}{suffix}.docx"
        if not exists(candidate_path):
            return candidate_path
        index += 1


def _normalize_optional_mime_type(mime_type: str | None) -> str | None:
    if mime_type is None:
        return None
    normalized = mime_type.split(";", 1)[0].strip().lower()
    return normalized or None


@lru_cache
def get_project_file_service() -> ProjectFileService:
    return ProjectFileService(
        get_project_repository(),
        get_file_workspace_storage(),
        get_markdown_docx_service(),
    )
