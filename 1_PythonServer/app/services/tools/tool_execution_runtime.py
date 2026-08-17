from __future__ import annotations

from json import dumps
from pathlib import Path
import os
import subprocess
import sys
from tempfile import TemporaryFile
import threading
from time import monotonic, sleep
from typing import Callable

from app.services.tools.tool_dependency_runtime import resolve_tool_site_packages

_PYTHON_TOOL_LAUNCHER = """
import os
import runpy
import sys

entry_path = sys.argv[1]
paths = [path for path in sys.argv[2:] if path]
for path in reversed(paths):
    if path not in sys.path:
        sys.path.insert(0, path)
sys.argv = [entry_path]
runpy.run_path(entry_path, run_name="__main__")
""".strip()

_SAFE_INHERITED_ENV_KEYS = (
    "APPDATA",
    "COMSPEC",
    "HOMEDRIVE",
    "HOMEPATH",
    "LOCALAPPDATA",
    "PATH",
    "PATHEXT",
    "SystemRoot",
    "TEMP",
    "TMP",
    "WINDIR",
)

CommandRunner = Callable[
    [list[str], str, Path, dict[str, str], int],
    subprocess.CompletedProcess[str],
]

_PROCESS_POLL_SECONDS = 0.05


class ToolExecutionCancellation:
    """Thread-safe ownership handle for one foreground tool process."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        self._cancelled.set()

    def register(self, process: subprocess.Popen[bytes]) -> None:
        with self._lock:
            self._process = process
            cancelled = self._cancelled.is_set()
        if cancelled:
            terminate_process_tree(process)

    def unregister(self, process: subprocess.Popen[bytes]) -> None:
        with self._lock:
            if self._process is process:
                self._process = None


def resolve_entry_path(tool_root: Path, entry: object) -> Path | None:
    raw_entry = entry if isinstance(entry, str) else ""
    normalized_entry = raw_entry.strip().replace("\\", "/").strip("/")
    if not normalized_entry:
        return None
    entry_path = (tool_root / normalized_entry).resolve()
    try:
        entry_path.relative_to(tool_root)
    except ValueError:
        return None
    return entry_path


def runtime_timeout_seconds(value: object) -> int:
    if isinstance(value, bool):
        return 60
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 60
    return max(1, parsed)


def resolve_workspace_root(workspace_root: str | None) -> Path | None:
    if not workspace_root:
        return None
    path = Path(workspace_root).expanduser().resolve(strict=False)
    return path if path.is_dir() else None


def build_tool_env(
    *,
    python_paths: tuple[Path, ...],
    workspace_root: Path | None,
    tools_root: Path | None = None,
    api_base_url: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    provider_id: str | None = None,
    model_id: str | None = None,
    input_modalities: tuple[str, ...] = (),
    host_capability_token: str | None = None,
) -> dict[str, str]:
    env = _base_tool_env()
    env["PYTHONPATH"] = os.pathsep.join(str(path) for path in python_paths)
    env["PYTHONIOENCODING"] = "utf-8"
    if api_base_url:
        env["TIANCE_API_BASE_URL"] = api_base_url
    if workspace_root is not None:
        env["TIANCE_WORKSPACE_ROOT"] = str(workspace_root)
    if tools_root is not None:
        env["TIANCE_TOOLS_ROOT"] = str(tools_root)
    if project_id:
        env["TIANCE_PROJECT_ID"] = project_id
    if session_id:
        env["TIANCE_SESSION_ID"] = session_id
    if host_capability_token:
        env["TIANCE_HOST_CAPABILITY_TOKEN"] = host_capability_token
    env["TIANCE_MODEL_CONTEXT"] = dumps(
        {
            "provider_id": provider_id,
            "model_id": model_id,
            "input_modalities": sorted(
                {
                    modality.strip().lower()
                    for modality in input_modalities
                    if modality.strip()
                }
            ),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return env


def build_tool_python_paths(
    *,
    entry_path: Path,
    tool_root: Path,
    backend_site_packages_path: Path,
) -> tuple[Path, ...]:
    return (
        entry_path.parent,
        resolve_tool_site_packages(tool_root),
        backend_site_packages_path,
        _backend_root(),
    )


def build_python_command(
    *,
    python_executable: Path,
    entry_path: Path,
    python_paths: tuple[Path, ...],
) -> list[str]:
    return [
        str(python_executable),
        "-c",
        _PYTHON_TOOL_LAUNCHER,
        str(entry_path),
        *[str(path) for path in python_paths],
    ]


def default_python_executable(embedded_python_file: Path) -> Path:
    return embedded_python_file if embedded_python_file.is_file() else Path(sys.executable)


def resolve_backend_api_base_url(api_prefix: str) -> str:
    host = _connect_host(os.environ.get("TIANCE_API_HOST", "127.0.0.1"))
    port = os.environ.get("TIANCE_API_PORT", "18000").strip() or "18000"
    prefix = "/" + api_prefix.strip().strip("/")
    if prefix == "/":
        prefix = ""
    return f"http://{host}:{port}{prefix}"


def run_command(
    command: list[str],
    input_text: str,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int,
    *,
    cancellation: ToolExecutionCancellation | None = None,
) -> subprocess.CompletedProcess[str]:
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    with TemporaryFile(mode="w+b") as stdout_file, TemporaryFile(mode="w+b") as stderr_file:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=stdout_file,
            stderr=stderr_file,
            cwd=str(cwd),
            env=env,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
        if cancellation is not None:
            cancellation.register(process)
        failure_reason: str | None = None
        try:
            if process.stdin is not None:
                try:
                    process.stdin.write(input_text.encode("utf-8"))
                except (BrokenPipeError, OSError):
                    pass
                finally:
                    process.stdin.close()

            deadline = monotonic() + timeout_seconds
            while process.poll() is None:
                if cancellation is not None and cancellation.is_cancelled:
                    failure_reason = "工具执行已取消。"
                    terminate_process_tree(process)
                    break
                if monotonic() >= deadline:
                    failure_reason = "工具执行超时。"
                    terminate_process_tree(process)
                    break
                sleep(_PROCESS_POLL_SECONDS)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                terminate_process_tree(process)
                process.wait(timeout=5)
        finally:
            if cancellation is not None:
                cancellation.unregister(process)

        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read().decode("utf-8", errors="replace")
        stderr = stderr_file.read().decode("utf-8", errors="replace")

    if failure_reason is not None:
        failure_stderr = f"{stderr.rstrip()}\n{failure_reason}" if stderr.strip() else failure_reason
        return subprocess.CompletedProcess(
            command,
            returncode=process.returncode if process.returncode not in {None, 0} else 1,
            stdout=stdout,
            stderr=failure_stderr,
        )
    return subprocess.CompletedProcess(
        command,
        returncode=process.returncode or 0,
        stdout=stdout,
        stderr=stderr,
    )


def terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=2,
            )
        except subprocess.TimeoutExpired:
            pass
    if os.name != "nt":
        try:
            os.killpg(process.pid, 15)
        except (ProcessLookupError, PermissionError):
            pass
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass


def _base_tool_env() -> dict[str, str]:
    return {key: value for key in _SAFE_INHERITED_ENV_KEYS if (value := os.environ.get(key))}


def _connect_host(value: str | None) -> str:
    host = (value or "").strip() or "127.0.0.1"
    if host in {"0.0.0.0", "::"}:
        return "127.0.0.1"
    return host


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[3]
