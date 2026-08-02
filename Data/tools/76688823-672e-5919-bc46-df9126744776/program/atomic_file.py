from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import shutil
import tempfile


class FileChangedError(RuntimeError):
    pass


def replace_bytes_atomically(
    path: Path,
    new_bytes: bytes,
    expected_bytes: bytes,
    *,
    create_backup: bool,
) -> Path | None:
    """Replace one file without exposing a partially written target."""
    temp_path = _stage_bytes(path, new_bytes)
    backup_path: Path | None = None
    committed = False
    try:
        _require_unchanged(path, expected_bytes)
        if create_backup:
            backup_path = _create_unique_backup(path, expected_bytes)
        _require_unchanged(path, expected_bytes)
        os.replace(temp_path, path)
        committed = True
        return backup_path
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        if not committed and backup_path is not None:
            backup_path.unlink(missing_ok=True)


def _stage_bytes(path: Path, data: bytes) -> Path:
    file_descriptor, raw_temp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temp_path = Path(raw_temp_path)
    try:
        with os.fdopen(file_descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        shutil.copystat(path, temp_path)
        return temp_path
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _require_unchanged(path: Path, expected_bytes: bytes) -> None:
    try:
        current_bytes = path.read_bytes()
    except FileNotFoundError as exc:
        raise FileChangedError("目标文件在写入前已被删除。") from exc
    if current_bytes != expected_bytes:
        raise FileChangedError("目标文件在读取后又被其他程序修改。")


def _create_unique_backup(path: Path, data: bytes) -> Path:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    for sequence in range(1000):
        suffix = "" if sequence == 0 else f".{sequence}"
        backup_path = path.with_name(f"{path.name}.{stamp}{suffix}.bak")
        try:
            with backup_path.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            shutil.copystat(path, backup_path)
            return backup_path
        except FileExistsError:
            continue
        except Exception:
            backup_path.unlink(missing_ok=True)
            raise
    raise OSError("无法生成唯一的备份文件名。")
