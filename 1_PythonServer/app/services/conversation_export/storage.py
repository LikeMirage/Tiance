from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import re
from shutil import rmtree
from threading import Lock
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.core.errors import BadRequestError
from app.domain.project.conversation_export import (
    RenderedConversationExport,
    StoredConversationExport,
)
from app.infra.file_workspace import FileWorkspaceStorage

_INVALID_FILE_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class ConversationExportStorage:
    """Owns export naming, collision avoidance, atomic persistence and native opening."""

    def __init__(self, file_storage: FileWorkspaceStorage) -> None:
        self._file_storage = file_storage
        self._write_lock = Lock()

    def store(
        self,
        rendered: RenderedConversationExport,
        *,
        target_directory: str,
        base_name: str,
    ) -> StoredConversationExport:
        directory = _require_export_directory(target_directory)
        normalized_base_name = _normalize_base_name(base_name, rendered.extension)
        with self._write_lock:
            resolved_base_name = _resolve_available_base_name(
                directory,
                normalized_base_name,
                extension=rendered.extension,
                bundle=rendered.bundle,
            )
            if rendered.bundle:
                return self._store_bundle(
                    directory,
                    resolved_base_name,
                    rendered,
                )
            return self._store_file(
                directory,
                resolved_base_name,
                rendered,
            )

    def open_export(self, output_path: Path) -> None:
        self._file_storage.open_entry_external(
            str(output_path.parent),
            output_path.name,
        )

    def _store_file(
        self,
        directory: Path,
        base_name: str,
        rendered: RenderedConversationExport,
    ) -> StoredConversationExport:
        output_path = directory / f"{base_name}{rendered.extension}"
        temp_path = directory / f".{base_name}.{uuid4().hex}.tmp"
        try:
            _write_bytes(temp_path, rendered.content)
            atomic_replace_path(temp_path, output_path)
        except OSError as exc:
            raise BadRequestError("无法写入导出文件，请检查目录权限或文件占用状态。") from exc
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
        return StoredConversationExport(
            container_path=output_path,
            output_path=output_path,
        )

    def _store_bundle(
        self,
        directory: Path,
        base_name: str,
        rendered: RenderedConversationExport,
    ) -> StoredConversationExport:
        output_dir = directory / base_name
        temp_dir = directory / f".{base_name}.{uuid4().hex}.tmp"
        try:
            temp_dir.mkdir()
            primary_path = temp_dir / f"{base_name}{rendered.extension}"
            _write_bytes(primary_path, rendered.content)
            seen_paths: set[PurePosixPath] = set()
            for file in rendered.files:
                relative_path = _validate_bundle_relative_path(file.relative_path)
                if relative_path in seen_paths:
                    continue
                seen_paths.add(relative_path)
                target_path = temp_dir.joinpath(*relative_path.parts)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                _write_bytes(target_path, file.content)
            atomic_replace_path(temp_dir, output_dir)
        except OSError as exc:
            raise BadRequestError("无法写入导出文件夹，请检查目录权限或文件占用状态。") from exc
        finally:
            if temp_dir.exists():
                rmtree(temp_dir, ignore_errors=True)
        return StoredConversationExport(
            container_path=output_dir,
            output_path=output_dir / f"{base_name}{rendered.extension}",
        )


def _require_export_directory(value: str) -> Path:
    raw_value = value.strip()
    if not raw_value:
        raise BadRequestError("导出路径不能为空。")
    directory = Path(raw_value).expanduser()
    if not directory.is_absolute():
        raise BadRequestError("导出路径必须是绝对路径。")
    try:
        resolved = directory.resolve(strict=True)
    except OSError as exc:
        raise BadRequestError("导出路径不存在或无法访问。") from exc
    if not resolved.is_dir():
        raise BadRequestError("导出路径不是文件夹。")
    return resolved


def _normalize_base_name(value: str, extension: str) -> str:
    base_name = value.strip()
    if extension and base_name.lower().endswith(extension.lower()):
        base_name = base_name[: -len(extension)].rstrip()
    if not base_name:
        raise BadRequestError("导出文件名不能为空。")
    if len(base_name) > 120:
        raise BadRequestError("导出文件名不能超过 120 个字符。")
    if _INVALID_FILE_NAME_CHARS.search(base_name):
        raise BadRequestError("导出文件名包含系统不允许的字符。")
    if base_name.endswith((".", " ")):
        raise BadRequestError("导出文件名不能以句点或空格结尾。")
    if base_name.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        raise BadRequestError("该导出文件名是系统保留名称。")
    return base_name


def _resolve_available_base_name(
    directory: Path,
    base_name: str,
    *,
    extension: str,
    bundle: bool,
) -> str:
    candidate = base_name
    copy_index = 2
    while (directory / candidate if bundle else directory / f"{candidate}{extension}").exists():
        suffix = f" ({copy_index})"
        candidate = f"{base_name[: max(1, 120 - len(suffix))]}{suffix}"
        copy_index += 1
    return candidate


def _validate_bundle_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or not path.parts or ".." in path.parts or path.parts[0] != "assets":
        raise BadRequestError("导出资源路径无效。")
    return path


def _write_bytes(path: Path, content: bytes) -> None:
    with path.open("xb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
