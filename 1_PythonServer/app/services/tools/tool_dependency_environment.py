from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
import logging
from pathlib import Path
import shutil
from tempfile import mkdtemp
from threading import Lock, RLock
from weakref import WeakValueDictionary

from app.core.atomic_replace import atomic_replace_path
from app.core.errors import BadRequestError
from app.services.tools.tool_dependency_site_packages import (
    read_installed_versions,
    remove_installed_distribution,
)

logger = logging.getLogger(__name__)
_locks_guard = Lock()
_locks: WeakValueDictionary[str, RLock] = WeakValueDictionary()


@contextmanager
def dependency_environment_lock(target: Path):
    key = str(target.resolve()).casefold()
    with _locks_guard:
        lock = _locks.setdefault(key, RLock())
    with lock:
        yield


def install_staged_environment(
    target: Path,
    *,
    install: Callable[[Path], None],
    validate: Callable[[Path], None],
) -> None:
    """Prepare a complete candidate before touching the currently usable environment."""
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    work = Path(mkdtemp(prefix=f".{target.name}.install-", dir=target.parent)).resolve()
    incoming = work / "incoming"
    prepared = work / "prepared"
    backup = work / "previous"
    incoming.mkdir()
    try:
        # pip writes only to an empty directory, including transitive dependencies.
        install(incoming)
        incoming_versions = read_installed_versions(incoming)
        if target.exists():
            shutil.copytree(target, prepared)
        else:
            prepared.mkdir()
        for package_name in incoming_versions:
            remove_installed_distribution(prepared, package_name)
        shutil.copytree(incoming, prepared, dirs_exist_ok=True)
        validate(prepared)

        had_previous = target.exists()
        if had_previous:
            atomic_replace_path(target, backup)
        try:
            atomic_replace_path(prepared, target)
        except OSError as install_error:
            if had_previous:
                try:
                    atomic_replace_path(backup, target)
                except OSError as rollback_error:
                    # Keep the only remaining copy of the old environment.
                    raise BadRequestError(
                        f"依赖环境替换及恢复失败，旧环境保留在 {backup}：{rollback_error}"
                    ) from install_error
            raise BadRequestError("依赖环境替换失败，原有依赖已保留。") from install_error
        _cleanup(work)
    finally:
        # Never delete the backup if restoring the original path failed.
        if not backup.exists():
            _cleanup(work)


def _cleanup(path: Path) -> None:
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except OSError:
        # Cleanup failure must not turn a successful update into an install error.
        logger.warning("Could not clean dependency staging directory %s", path, exc_info=True)
