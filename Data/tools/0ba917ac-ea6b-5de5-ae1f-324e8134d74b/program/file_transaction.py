from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import shutil
import tempfile


class FileTransactionError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class PreparedFileChange:
    target: Path
    original_exists: bool
    original_bytes: bytes
    original_stat: os.stat_result | None
    new_bytes: bytes | None


def apply_file_transaction(
    changes: list[PreparedFileChange],
    *,
    create_backups: bool,
) -> dict[Path, Path]:
    """Commit validated file changes and roll back the batch on failure."""
    staged: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    created_directories: list[Path] = []
    committed: list[PreparedFileChange] = []
    try:
        _create_required_directories(changes, created_directories)
        for change in changes:
            if change.new_bytes is not None:
                staged[change.target] = _stage_change(change)

        _require_all_unchanged(changes)
        if create_backups:
            for change in changes:
                if change.original_exists:
                    backups[change.target] = _create_unique_backup(change)
        _require_all_unchanged(changes)

        for change in changes:
            _require_unchanged(change)
            if change.new_bytes is None:
                change.target.unlink()
            else:
                os.replace(staged[change.target], change.target)
                staged.pop(change.target)
            committed.append(change)
        return backups
    except FileTransactionError:
        rollback_errors = _rollback(committed)
        if rollback_errors:
            raise FileTransactionError(
                "ROLLBACK_FAILED",
                "补丁写入失败，且自动回滚未能完全恢复。",
                {
                    "rollback_errors": rollback_errors,
                    "backup_paths": [str(path) for path in backups.values()],
                },
            )
        _remove_backups(backups)
        raise
    except OSError as exc:
        rollback_errors = _rollback(committed)
        if rollback_errors:
            raise FileTransactionError(
                "ROLLBACK_FAILED",
                "补丁写入失败，且自动回滚未能完全恢复。",
                {
                    "message": str(exc),
                    "rollback_errors": rollback_errors,
                    "backup_paths": [str(path) for path in backups.values()],
                },
            ) from exc
        _remove_backups(backups)
        raise FileTransactionError(
            "WRITE_FAILED",
            "补丁写入失败，已回滚本次已提交的文件。",
            {"message": str(exc)},
        ) from exc
    finally:
        for temp_path in staged.values():
            temp_path.unlink(missing_ok=True)
        _remove_empty_directories(created_directories)


def _create_required_directories(
    changes: list[PreparedFileChange],
    created: list[Path],
) -> None:
    for change in changes:
        if change.new_bytes is None or change.target.parent.exists():
            continue
        missing: list[Path] = []
        current = change.target.parent
        while not current.exists():
            missing.append(current)
            current = current.parent
        for directory in reversed(missing):
            directory.mkdir()
            created.append(directory)


def _stage_change(change: PreparedFileChange) -> Path:
    descriptor, raw_path = tempfile.mkstemp(
        dir=change.target.parent,
        prefix=f".{change.target.name}.",
        suffix=".tmp",
    )
    temp_path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(change.new_bytes or b"")
            stream.flush()
            os.fsync(stream.fileno())
        if change.original_stat is not None:
            os.chmod(temp_path, change.original_stat.st_mode)
            os.utime(
                temp_path,
                ns=(change.original_stat.st_atime_ns, change.original_stat.st_mtime_ns),
            )
        return temp_path
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _require_all_unchanged(changes: list[PreparedFileChange]) -> None:
    for change in changes:
        _require_unchanged(change)


def _require_unchanged(change: PreparedFileChange) -> None:
    exists = change.target.exists()
    if exists != change.original_exists:
        raise FileTransactionError(
            "WRITE_CONFLICT",
            "补丁目标在验证后发生了变化。",
            {"file": str(change.target)},
        )
    if exists and change.target.read_bytes() != change.original_bytes:
        raise FileTransactionError(
            "WRITE_CONFLICT",
            "补丁目标在读取后又被其他程序修改。",
            {"file": str(change.target)},
        )


def _create_unique_backup(change: PreparedFileChange) -> Path:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    for sequence in range(1000):
        suffix = "" if sequence == 0 else f".{sequence}"
        backup_path = change.target.with_name(
            f"{change.target.name}.{stamp}{suffix}.bak"
        )
        try:
            with backup_path.open("xb") as stream:
                stream.write(change.original_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            shutil.copystat(change.target, backup_path)
            return backup_path
        except FileExistsError:
            continue
        except Exception:
            backup_path.unlink(missing_ok=True)
            raise
    raise OSError("无法生成唯一的备份文件名。")


def _rollback(changes: list[PreparedFileChange]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for change in reversed(changes):
        temp_path: Path | None = None
        try:
            if change.original_exists:
                restore = PreparedFileChange(
                    target=change.target,
                    original_exists=change.target.exists(),
                    original_bytes=(
                        change.target.read_bytes() if change.target.exists() else b""
                    ),
                    original_stat=change.original_stat,
                    new_bytes=change.original_bytes,
                )
                temp_path = _stage_change(restore)
                os.replace(temp_path, change.target)
            else:
                change.target.unlink(missing_ok=True)
        except OSError as exc:
            errors.append({"file": str(change.target), "message": str(exc)})
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
    return errors


def _remove_backups(backups: dict[Path, Path]) -> None:
    for backup_path in backups.values():
        backup_path.unlink(missing_ok=True)


def _remove_empty_directories(directories: list[Path]) -> None:
    for directory in reversed(directories):
        try:
            directory.rmdir()
        except OSError:
            pass
