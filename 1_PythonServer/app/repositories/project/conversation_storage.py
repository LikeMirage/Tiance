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
            from app.repositories.project.conversation_records import ensure_file_storage

            ensure_file_storage(workspace_dir)
            return workspace_dir
        if for_write:
            ensure_workspace_readme(workspace_dir)
        from app.repositories.project.conversation_records import ensure_file_storage

        ensure_file_storage(workspace_dir)
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
- `storage.json`：工作区数据结构版本与事实来源声明。
- `state.json`：只保存当前项目的人机工作区状态，不承载会话历史。
- `cache/conversation-index.db`：可删除、可重建的消息分页索引；不是事实来源。

## conversations/sessions/

每个会话独立保存自己的事实，不再维护一份所有会话共同改写的权威总表。

- `conversations/control.json`：当前选中会话；只属于工作区导航。
- `conversations/sessions/{session_id}/session.json`：会话身份、配置与消息计数。
- `conversations/sessions/{session_id}/state.json`：该会话的置顶与运行状态。
- `conversations/sessions/{session_id}/branch.json`：该会话自己的来源关系和消息版本。
- `conversations/sessions/{session_id}/messages.jsonl`：完整原始消息，不设置隐式条数上限。
- `conversations/sessions/{session_id}/*.jsonl`：压缩、命名、附件等追加记录。
- `conversations/sessions/{session_id}/*.json`：注入预览、记忆投递和功能任务状态。
- `conversations/sessions/{session_id}/attachments/`：该会话独立持有的附件文件。

## 数据看板

消息、压缩、注入预览、会话状态和项目记忆看板直接读取上述事实文件。界面为了可读性可以分页或生成总览，但不会改变模型读取完整有效历史的合同。

全局长期记忆不放在项目目录内，而是保存在天策运行数据目录的 `memory/global_memory.jsonl`。
"""


@contextmanager
def conversation_write_lock(conversations_dir: Path):
    with _file_write_lock(conversations_dir):
        yield


@contextmanager
def _file_write_lock(target_dir: Path):
    target_dir.mkdir(parents=True, exist_ok=True)
    write_queue = _write_queue_for(target_dir)
    with write_queue.wait_for_turn():
        # Session locks live beside their deletable directory so Windows can
        # remove that directory while the lock remains held. Other scopes keep
        # the established internal lock and do not create project-root noise.
        lock_path = _write_lock_path(target_dir)
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


def _write_lock_path(target_dir: Path) -> Path:
    if (
        target_dir.parent.name == "sessions"
        and target_dir.parent.parent.name == CONVERSATIONS_DIR
    ):
        return target_dir.parent / f".{target_dir.name}{_WRITE_LOCK_FILE}"
    return target_dir / _WRITE_LOCK_FILE


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
