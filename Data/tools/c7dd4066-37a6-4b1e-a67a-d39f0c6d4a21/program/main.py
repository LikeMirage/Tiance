from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
import msvcrt
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterator
from uuid import uuid4

from tiance_runtime import run_tool


CONTROL_ROOT = Path(tempfile.gettempdir()) / "Tiance" / "gui-control"
STATE_PATH = CONTROL_ROOT / "active-lock.json"
MUTEX_PATH = CONTROL_ROOT / "lock.mutex"
STARTUP_TIMEOUT_SECONDS = 10.0
MUTEX_TIMEOUT_SECONDS = 5.0
RPC_TIMEOUT_SECONDS = 10.0
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259


kernel32 = ctypes.windll.kernel32
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class ToolError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def success(summary: str, data: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    return {"ok": True, "summary": summary, "data": data, "warnings": warnings or []}


def failure(error: ToolError) -> dict[str, Any]:
    return {
        "ok": False,
        "error": f"{error.code}: {error.message}",
        "error_info": {"code": error.code, "message": error.message, "details": error.details},
        "warnings": [],
    }


def current_context() -> tuple[Path, str, str]:
    workspace_value = str(os.environ.get("TIANCE_WORKSPACE_ROOT") or "").strip()
    project_id = str(os.environ.get("TIANCE_PROJECT_ID") or "").strip()
    session_id = str(os.environ.get("TIANCE_SESSION_ID") or "").strip()
    if not workspace_value or not project_id or not session_id:
        raise ToolError(
            "GUI_CONTEXT_UNAVAILABLE",
            "GUI工具必须在天策项目会话中运行。",
            {
                "workspace_available": bool(workspace_value),
                "project_id_available": bool(project_id),
                "session_id_available": bool(session_id),
            },
        )
    workspace = Path(workspace_value).resolve(strict=False)
    if not workspace.is_dir():
        raise ToolError("GUI_CONTEXT_UNAVAILABLE", "当前项目工作区不存在。")
    return workspace, project_id, session_id


def process_alive(pid: Any) -> bool:
    try:
        process_id = int(pid)
    except (TypeError, ValueError):
        return False
    if process_id <= 0:
        return False
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def read_state() -> dict[str, Any] | None:
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolError("GUI_RUNTIME_STATE_INVALID", "GUI后台运行器状态文件损坏。", {"reason": str(exc)}) from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ToolError("GUI_RUNTIME_STATE_INVALID", "GUI后台运行器状态格式无效。")
    return payload


def remove_state_if_matches(lock_id: Any) -> None:
    try:
        state = read_state()
    except ToolError:
        STATE_PATH.unlink(missing_ok=True)
        return
    if state is not None and state.get("lock_id") == lock_id:
        STATE_PATH.unlink(missing_ok=True)


def public_state(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "active": state.get("status") == "active" and process_alive(state.get("pid")),
        "runtime_id": state.get("lock_id"),
        "project_id": state.get("project_id"),
        "session_id": state.get("session_id"),
        "capture_mode": state.get("capture_mode"),
        "created_at": state.get("created_at"),
    }


@contextmanager
def state_mutex() -> Iterator[None]:
    CONTROL_ROOT.mkdir(parents=True, exist_ok=True)
    with MUTEX_PATH.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + MUTEX_TIMEOUT_SECONDS
        while True:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise ToolError(
                        "GUI_RUNTIME_BUSY",
                        "另一个GUI后台运行器请求仍在处理中。",
                        {"mutex_timeout_seconds": MUTEX_TIMEOUT_SECONDS},
                    ) from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def rpc_call(state: dict[str, Any], method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    request = {
        "token": state.get("token"),
        "project_id": state.get("project_id"),
        "session_id": state.get("session_id"),
        "method": method,
        "payload": payload or {},
    }
    data = bytearray()
    try:
        with socket.create_connection(("127.0.0.1", int(state["port"])), timeout=RPC_TIMEOUT_SECONDS) as connection:
            connection.settimeout(RPC_TIMEOUT_SECONDS)
            connection.sendall((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
            while len(data) <= 2_000_000:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                data.extend(chunk)
                if b"\n" in chunk:
                    break
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ToolError("GUI_RUNTIME_UNAVAILABLE", "无法连接GUI后台运行器。", {"reason": str(exc)}) from exc
    if len(data) > 2_000_000:
        raise ToolError("GUI_RUNTIME_RESPONSE_TOO_LARGE", "GUI后台运行器返回结果超过2MB限制。")
    try:
        response = json.loads(bytes(data).split(b"\n", 1)[0].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolError("GUI_RUNTIME_INVALID_RESPONSE", "GUI后台运行器返回了无效结果。") from exc
    if not isinstance(response, dict):
        raise ToolError("GUI_RUNTIME_INVALID_RESPONSE", "GUI后台运行器返回结果不是对象。")
    return response


def require_owned_state(workspace: Path, project_id: str, session_id: str) -> dict[str, Any] | None:
    state = read_state()
    if state is None:
        return None
    if not process_alive(state.get("pid")):
        remove_state_if_matches(state.get("lock_id"))
        return None
    if state.get("status") != "active":
        raise ToolError("GUI_RUNTIME_BUSY", "GUI后台运行器尚未进入可用状态。", public_state(state))
    expected_workspace = str(workspace.resolve(strict=False)).casefold()
    actual_workspace = str(Path(str(state.get("workspace") or "")).resolve(strict=False)).casefold()
    if (
        state.get("project_id") != project_id
        or state.get("session_id") != session_id
        or actual_workspace != expected_workspace
    ):
        raise ToolError("GUI_RUNTIME_OWNED_BY_OTHER_SESSION", "GUI后台运行器属于另一个项目会话。", public_state(state))
    return state


def start_lock(
    workspace: Path,
    project_id: str,
    session_id: str,
    *,
    block_user_input: bool = False,
) -> dict[str, Any]:
    existing = require_owned_state(workspace, project_id, session_id)
    if existing is not None:
        status = rpc_call(existing, "status")
        if not status.get("ok"):
            raise ToolError("GUI_RUNTIME_UNAVAILABLE", str(status.get("error") or "GUI后台运行器状态异常。"))
        data = status.get("data") if isinstance(status.get("data"), dict) else {}
        data["already_active"] = True
        return success("当前会话的GUI后台运行器已经启动。", data)

    lock_id = f"lock_{uuid4().hex}"
    token = secrets.token_urlsafe(32)
    # 部分Windows鼠标输入链路只保留dwExtraInfo的低32位；使用非零31位标记，
    # 让鼠标与键盘低级钩子都能稳定识别由天策注入的事件。
    marker = secrets.randbits(31) | (1 << 30)
    helper_path = Path(__file__).with_name("overlay_helper.py")
    dependency_path = Path(__file__).resolve().parents[1] / "dependencies" / "py313" / "site-packages"
    helper_python_paths = os.pathsep.join(dict.fromkeys(
        str(path)
        for path in [dependency_path, *sys.path]
        if path and Path(path).exists()
    ))
    helper_launcher = (
        "import os,runpy,sys;"
        "entry=sys.argv.pop(1);"
        "paths=sys.argv.pop(1).split(os.pathsep);"
        "sys.path[:0]=[path for path in paths if path];"
        "sys.argv[0]=entry;"
        "runpy.run_path(entry,run_name='__main__')"
    )
    command = [
        sys.executable,
        "-c",
        helper_launcher,
        str(helper_path),
        helper_python_paths,
        "--state-file", str(STATE_PATH),
        "--workspace", str(workspace),
        "--project-id", project_id,
        "--session-id", session_id,
        "--lock-id", lock_id,
        "--token", token,
        "--marker", str(marker),
    ]
    if block_user_input:
        command.append("--block-user-input")
    creation_flags = 0x00000008 | 0x00000200 | 0x08000000
    process = subprocess.Popen(
        command,
        cwd=str(helper_path.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
        close_fds=True,
    )
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        state = read_state()
        if state is not None and state.get("lock_id") == lock_id:
            if state.get("status") == "failed":
                error = str(state.get("error") or "辅助进程启动失败。")
                remove_state_if_matches(lock_id)
                raise ToolError("GUI_RUNTIME_START_FAILED", "GUI后台运行器启动失败。", {"reason": error})
            if state.get("status") == "active" and process_alive(state.get("pid")):
                result = rpc_call(state, "status")
                if result.get("ok"):
                    data = result.get("data") if isinstance(result.get("data"), dict) else {}
                    data["already_active"] = False
                    data["startup_timeout_seconds"] = STARTUP_TIMEOUT_SECONDS
                    return success("GUI后台运行器已启动，不会显示覆盖层或拦截用户输入。", data)
        if process.poll() is not None:
            remove_state_if_matches(lock_id)
            raise ToolError(
                "GUI_RUNTIME_START_FAILED",
                "GUI后台运行器启动后立即退出。",
                {"exit_code": process.returncode},
            )
        time.sleep(0.05)
    remove_state_if_matches(lock_id)
    try:
        process.terminate()
    except OSError:
        pass
    raise ToolError(
        "GUI_RUNTIME_START_TIMEOUT",
        "GUI后台运行器未在10秒内启动完成。",
        {"startup_timeout_seconds": STARTUP_TIMEOUT_SECONDS},
    )


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        if os.name != "nt":
            raise ToolError("PLATFORM_NOT_SUPPORTED", "GUI工具目前只支持Windows。")
        workspace, project_id, session_id = current_context()
        action = str(payload.get("action") or "").strip()
        if action not in {"start", "status", "stop"}:
            raise ToolError("INVALID_ARGUMENT", "action必须是start、status或stop。")
        with state_mutex():
            if action == "start":
                return start_lock(workspace, project_id, session_id, block_user_input=False)
            state = require_owned_state(workspace, project_id, session_id)
            if state is None:
                if action == "status":
                    return success("GUI后台运行器当前没有启动。", {"active": False})
                return success("GUI后台运行器当前没有启动。", {"active": False, "released": False})
            response = rpc_call(state, "unlock" if action == "stop" else action)
            if not response.get("ok"):
                info = response.get("error_info") if isinstance(response.get("error_info"), dict) else {}
                raise ToolError(str(info.get("code") or "GUI_RUNTIME_ERROR"), str(response.get("error") or "GUI后台运行器操作失败。"), info.get("details"))
            if action == "stop":
                deadline = time.monotonic() + 3.0
                while time.monotonic() < deadline and STATE_PATH.exists():
                    time.sleep(0.05)
            response.setdefault("warnings", [])
            return response
    except ToolError as exc:
        return failure(exc)
    except Exception as exc:
        return failure(ToolError("GUI_RUNTIME_INTERNAL_ERROR", "GUI后台运行器工具执行失败。", {"reason": str(exc)}))


if __name__ == "__main__":
    run_tool(run)
