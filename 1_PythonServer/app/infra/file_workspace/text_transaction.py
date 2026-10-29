"""Stage related text writes and restore originals if committing any file fails."""
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
import shutil
from threading import RLock
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.core.errors import ConflictError
from app.domain.file_workspace import TextFileUpdate

# Bounded locks; every application text writer for a workspace uses this path.
_LOCKS = tuple(RLock() for _ in range(64))


@contextmanager
def text_file_transaction(
    root: Path,
    updates: list[TextFileUpdate],
    resolve: Callable[[Path, str], Path],
) -> Iterator[list[Path]]:
    with _LOCKS[hash(root) % len(_LOCKS)]:
        targets = [resolve(root, update.path) for update in updates]
        if len(set(targets)) != len(targets):
            raise ValueError("同一批保存中不能重复指定文件。")
        staged: list[tuple[Path, Path, Path | None]] = []
        replaced: list[tuple[Path, Path | None]] = []
        recovery_failed = False
        try:
            for target, update in zip(targets, updates, strict=True):
                if target.exists() and not target.is_file():
                    raise ValueError("保存目标不是文件。")
                if update.expected_mtime_ms is not None and (
                    not target.is_file()
                    or int(target.stat().st_mtime * 1000) != update.expected_mtime_ms
                ):
                    raise ConflictError("文件已在外部发生变化，请重新加载后再保存。")
                target.parent.mkdir(parents=True, exist_ok=True)
                token = uuid4().hex
                temporary = target.with_name(f".{target.name}.{token}.tmp")
                backup = target.with_name(f".{target.name}.{token}.rollback.tmp") if target.exists() else None
                staged.append((target, temporary, backup))
                temporary.write_text(update.content, encoding="utf-8")
                if backup is not None:
                    shutil.copy2(target, backup)
            for target, temporary, backup in staged:
                atomic_replace_path(temporary, target)
                replaced.append((target, backup))
            yield targets
        except BaseException as error:
            failures = []
            for target, backup in reversed(replaced):
                try:
                    if backup is None:
                        target.unlink(missing_ok=True)
                    else:
                        atomic_replace_path(backup, target)
                except OSError:
                    failures.append(str(backup or target))
            if failures:
                recovery_failed = True
                raise RuntimeError("保存及恢复失败，恢复文件已保留：" + ", ".join(failures)) from error
            raise
        finally:
            for _, temporary, backup in staged:
                for path in (temporary, None if recovery_failed else backup):
                    if path is not None:
                        try:
                            path.unlink(missing_ok=True)
                        except OSError:
                            pass
