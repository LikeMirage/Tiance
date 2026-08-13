from contextlib import contextmanager
from collections import deque
from json import dumps
import os
from pathlib import Path
from threading import Event, Lock
from time import monotonic, sleep, time
from uuid import uuid4
from weakref import WeakValueDictionary

from app.core.atomic_replace import atomic_replace_path
from app.core.errors import ConflictError
from app.infra.projects.project_storage import require_existing_project_root

WORKSPACE_DIR = ".Tiance"
WORKSPACE_README_FILE = "README.md"
CONVERSATIONS_DIR = "conversations"
_WRITE_LOCK_FILE = ".write.lock"
_WRITE_LOCK_TIMEOUT_SECONDS = 10.0
_WRITE_LOCK_STALE_AFTER_SECONDS = 60.0
_WRITE_LOCK_RELEASE_TIMEOUT_SECONDS = 1.0


class _WriteQueue:
    def __init__(self) -> None:
        self._lock = Lock()
        self._waiters: deque[Event] = deque()

    @contextmanager
    def wait_for_turn(self):
        ready = Event()
        with self._lock:
            self._waiters.append(ready)
            if len(self._waiters) == 1:
                ready.set()
        ready.wait()
        try:
            yield
        finally:
            with self._lock:
                if self._waiters and self._waiters[0] is ready:
                    self._waiters.popleft()
                if self._waiters:
                    self._waiters[0].set()


_WRITE_QUEUE_REGISTRY_LOCK = Lock()
_WRITE_QUEUES: WeakValueDictionary[str, _WriteQueue] = WeakValueDictionary()


class ProjectWorkspaceDirectoryResolver:
    def resolve_workspace_dir(self, project_root: Path, *, for_write: bool = False) -> Path:
        workspace_dir = require_existing_project_root(project_root) / WORKSPACE_DIR
        if workspace_dir.exists():
            if for_write:
                ensure_workspace_readme(workspace_dir)
            from app.repositories.project.conversation_database import ensure_database

            ensure_database(workspace_dir)
            return workspace_dir
        if for_write:
            ensure_workspace_readme(workspace_dir)
        from app.repositories.project.conversation_database import ensure_database

        ensure_database(workspace_dir)
        return workspace_dir


def ensure_workspace_readme(workspace_dir: Path) -> None:
    readme_path = workspace_dir / WORKSPACE_README_FILE
    if readme_path.exists():
        return
    atomic_write_text(readme_path, _workspace_readme_content())


def _workspace_readme_content() -> str:
    return """# .Tiance

`.Tiance` 是当前项目的天策工作区数据目录，用于保存项目内会话、记忆和运行状态。这个目录由程序维护，普通项目文件不要放在这里。

## 根目录文件

- `README.md`：说明 `.Tiance` 内各文件和目录的用途。
- `tiance.db`：项目会话、消息、分支、项目记忆、任务状态和工作区状态的唯一数据源。数据库使用 WAL 模式，允许界面读取与后台写入并行进行。
- `tiance.db-wal`、`tiance.db-shm`：SQLite 运行期间自动维护的 WAL 文件，软件正常关闭或数据库检查点执行后可能消失，不应手工编辑或删除。

## conversations/sessions/

这里只保留必须作为实体文件存在的会话附件。会话元数据、消息、压缩记录、注入预览和附件索引都保存在 `tiance.db` 中。

- `conversations/sessions/{session_id}/attachments/`：该会话独立持有的附件文件。分支会复制自己的附件副本，删除会话时一并清理。

## 数据看板

消息、压缩、注入预览、会话索引和项目记忆看板通过后端只读数据视图从 `tiance.db` 获取内容，不依赖磁盘上的 JSON/JSONL 镜像文件。

全局长期记忆不放在项目目录内，而是保存在天策运行数据目录的 `memory/global_memory.jsonl`。
"""


@contextmanager
def conversation_write_lock(conversations_dir: Path):
    if conversations_dir.name != CONVERSATIONS_DIR:
        with _file_write_lock(conversations_dir):
            yield
        return
    from app.repositories.project.conversation_database import (
        transaction_for_conversations,
    )

    with transaction_for_conversations(conversations_dir):
        yield


@contextmanager
def _file_write_lock(target_dir: Path):
    target_dir.mkdir(parents=True, exist_ok=True)
    write_queue = _write_queue_for(target_dir)
    with write_queue.wait_for_turn():
        lock_path = target_dir / _WRITE_LOCK_FILE
        lock_token = f"{os.getpid()}:{uuid4().hex}"
        deadline = monotonic() + _WRITE_LOCK_TIMEOUT_SECONDS
        fd: int | None = None
        while fd is None:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, lock_token.encode("ascii"))
            except (FileExistsError, PermissionError) as exc:
                _remove_stale_lock(lock_path)
                if monotonic() >= deadline:
                    raise ConflictError("数据正在写入，请稍后重试。") from exc
                sleep(0.05)
        try:
            yield
        finally:
            if fd is not None:
                os.close(fd)
            _remove_owned_lock(lock_path, lock_token)


def _write_queue_for(conversations_dir: Path) -> _WriteQueue:
    key = os.path.normcase(os.path.abspath(conversations_dir))
    with _WRITE_QUEUE_REGISTRY_LOCK:
        queue = _WRITE_QUEUES.get(key)
        if queue is None:
            queue = _WriteQueue()
            _WRITE_QUEUES[key] = queue
        return queue


def _remove_owned_lock(lock_path: Path, lock_token: str) -> None:
    deadline = monotonic() + _WRITE_LOCK_RELEASE_TIMEOUT_SECONDS
    while True:
        try:
            if lock_path.read_text(encoding="ascii") != lock_token:
                return
            lock_path.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if monotonic() >= deadline:
                return
            sleep(0.01)


def _remove_stale_lock(lock_path: Path) -> None:
    try:
        age = time() - lock_path.stat().st_mtime
    except OSError:
        return
    if age <= _WRITE_LOCK_STALE_AFTER_SECONDS:
        return
    try:
        owner_pid = int(lock_path.read_text(encoding="ascii").partition(":")[0])
    except (OSError, ValueError):
        owner_pid = None
    if (
        owner_pid is not None
        and owner_pid != os.getpid()
        and _process_is_running(owner_pid)
    ):
        return
    try:
        lock_path.unlink()
    except OSError:
        return


def _process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        return _windows_process_is_running(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _windows_process_is_running(pid: int) -> bool:
    import ctypes

    process_query_limited_information = 0x1000
    error_access_denied = 5
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(
        process_query_limited_information,
        False,
        pid,
    )
    if handle:
        exit_code = ctypes.c_ulong()
        query_succeeded = kernel32.GetExitCodeProcess(
            handle,
            ctypes.byref(exit_code),
        )
        kernel32.CloseHandle(handle)
        return bool(query_succeeded) and exit_code.value == still_active
    return ctypes.get_last_error() == error_access_denied


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(dumps(payload, ensure_ascii=False, separators=(",", ":")))
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        atomic_replace_path(temp_path, path)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
