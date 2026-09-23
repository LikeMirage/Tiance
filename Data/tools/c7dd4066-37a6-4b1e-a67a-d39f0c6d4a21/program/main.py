from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
import math
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
from urllib.parse import urlencode

from tiance_runtime import run_tool


CONTROL_ROOT = Path(tempfile.gettempdir()) / "Tiance" / "gui-control"
STATE_PATH = CONTROL_ROOT / "active-lock.json"
MUTEX_PATH = CONTROL_ROOT / "lock.mutex"
STARTUP_TIMEOUT_SECONDS = 10.0
MUTEX_TIMEOUT_SECONDS = 5.0
RPC_TIMEOUT_SECONDS = 10.0
STARTUP_ROLLBACK_TIMEOUT_SECONDS = 3.0
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
        error = int(kernel32.GetLastError())
        if error == 87:  # Invalid PID: the process no longer exists.
            return False
        raise ToolError("GUI_RUNTIME_PROCESS_STATUS_UNKNOWN", "无法读取运行器进程状态，不能认为界面锁已退出。",
                        {"pid": process_id, "active": None, "winerror": error})
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            raise ToolError("GUI_RUNTIME_PROCESS_STATUS_UNKNOWN", "无法确认运行器进程是否已经退出。",
                            {"pid": process_id, "active": None})
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def read_state() -> dict[str, Any] | None:
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ToolError("GUI_RUNTIME_STATE_ACCESS_FAILED", "无法访问GUI状态文件；锁状态未知，请勿认为已经解锁，可按Esc退出。",
                        {"state_file": str(STATE_PATH), "active": None, "winerror": getattr(exc, "winerror", None)}) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolError("GUI_RUNTIME_STATE_INVALID", "GUI后台运行器状态文件损坏，锁状态未知。", {"active": None}) from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ToolError("GUI_RUNTIME_STATE_INVALID", "GUI后台运行器状态格式无效。")
    return payload


def remove_state_if_matches(lock_id: Any) -> None:
    # Never delete a state file whose ownership cannot be read and verified.
    state = read_state()
    if state is not None and state.get("lock_id") == lock_id:
        STATE_PATH.unlink(missing_ok=True)


def public_state(state: dict[str, Any]) -> dict[str, Any]:
    alive = process_alive(state.get("pid"))
    return {
        "active": None if alive else False,
        "process_alive": alive,
        "runtime_id": state.get("lock_id"),
        "project_id": state.get("project_id"),
        "session_id": state.get("session_id"),
        "capture_mode": state.get("capture_mode"),
        "created_at": state.get("created_at"),
        "pid": state.get("pid"),
        "port": state.get("port"),
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


def preflight_state_storage() -> None:
    """Check the actual inherited ACL through file operations before creating a lock."""
    probe = CONTROL_ROOT / f".startup-{uuid4().hex}.tmp"
    replaced = probe.with_suffix(".check")
    try:
        CONTROL_ROOT.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"gui-state-access-check")
        os.replace(probe, replaced)
        if replaced.read_bytes() != b"gui-state-access-check":
            raise OSError("State storage verification failed")
        replaced.unlink()
    except OSError as exc:
        details: dict[str, Any] = {"state_directory": str(CONTROL_ROOT),
                                  "process_created": False, "winerror": getattr(exc, "winerror", None)}
        for path in (probe, replaced):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                details.setdefault("remaining_probe_files", []).append(str(path))
        raise ToolError("GUI_RUNTIME_STATE_ACCESS_FAILED",
                        "GUI状态目录读写、替换或删除检查失败，未创建运行器、未锁定界面；请检查该目录的实际访问权限。", details) from exc


def confirmed_lock_status(state: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    matches = all(data.get(key) == state.get(source)
                  for key, source in (("runtime_id", "lock_id"), ("pid", "pid"),
                                      ("project_id", "project_id"), ("session_id", "session_id")))
    if (response.get("ok") is not True or data.get("active") is not True
            or data.get("input_mode") != "blocked" or data.get("hooks_installed") is not True or not matches):
        raise ToolError("GUI_LOCK_NOT_CONFIRMED", "未能确认GUI界面锁实际生效。",
                        {"pid": state.get("pid"), "port": state.get("port"),
                         "active": data.get("active"), "hooks_installed": data.get("hooks_installed")})
    return data


def rollback_start(process: subprocess.Popen, lock_id: str, state: dict[str, Any] | None) -> dict[str, Any]:
    """Use the child handle we created, never a PID recovered from an unreadable file."""
    details: dict[str, Any] = {"runtime_id": lock_id, "pid": process.pid,
                              "port": state.get("port") if state else None, "process_created": True}
    if process.stdin is not None:
        try:
            process.stdin.close()  # EOF also requests child release before confirmation.
        except OSError:
            pass
    try:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=STARTUP_ROLLBACK_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        details["rollback_error"] = type(exc).__name__
    alive = process.poll() is None
    details.update({"process_alive": alive, "active": None if alive else False, "released": not alive})
    if not alive:
        try:
            remove_state_if_matches(lock_id)
        except (ToolError, OSError) as exc:
            details["state_cleanup_error"] = exc.code if isinstance(exc, ToolError) else type(exc).__name__
    return details


def start_lock(
    workspace: Path,
    project_id: str,
    session_id: str,
    idle_timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    if not math.isfinite(idle_timeout_seconds) or idle_timeout_seconds <= 0:
        raise ToolError("INVALID_ARGUMENT", "idle_timeout_seconds必须是有限正数。")
    existing = require_owned_state(workspace, project_id, session_id)
    if existing is not None:
        if existing.get("input_mode") != "blocked":
            raise ToolError("GUI_LOCK_REQUIRED", "旧的无锁运行器仍在运行，请先调用gui_runtime stop，再调用start。")
        try:
            status = rpc_call(existing, "status")
            data = confirmed_lock_status(existing, status)
        except ToolError as exc:
            exc.details.setdefault("pid", existing.get("pid"))
            exc.details.setdefault("port", existing.get("port"))
            exc.details.setdefault("active", None)
            raise
        if data.get("idle_timeout_seconds") != idle_timeout_seconds:
            raise ToolError("GUI_RUNTIME_CONFIG_CHANGED", "修改空闲时长需要先stop再start。")
        data["already_active"] = True
        return success("当前会话已经锁定界面。鼠标已禁止操作，按Esc退出。", data)

    preflight_state_storage()
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
        "--idle-timeout-seconds", str(idle_timeout_seconds),
        "--require-startup-confirmation",
        "--startup-timeout-seconds", str(STARTUP_TIMEOUT_SECONDS),
    ]
    api_base = str(os.environ.get("TIANCE_API_BASE_URL") or "").rstrip("/")
    if api_base:
        owner_url = api_base + "/llm/chat/completions/stream/status?" + urlencode({"project_id": project_id, "session_id": session_id})
        command.extend(["--owner-status-url", owner_url])
    creation_flags = 0x00000008 | 0x00000200 | 0x08000000
    process = subprocess.Popen(
        command,
        cwd=str(helper_path.parent),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
        close_fds=True,
    )
    known_state: dict[str, Any] | None = None
    try:
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            state = read_state()
            if state is not None and state.get("lock_id") == lock_id:
                known_state = state
                if state.get("status") == "failed":
                    raise ToolError("GUI_RUNTIME_START_FAILED", "GUI后台运行器启动失败。",
                                    {"reason": state.get("error") or "辅助进程启动失败。"})
                if state.get("status") == "active" and state.get("pid") == process.pid and process.poll() is None:
                    data = confirmed_lock_status(state, rpc_call(state, "status"))
                    if process.stdin is None:
                        raise ToolError("GUI_START_CONFIRMATION_FAILED", "启动确认通道不可用。")
                    process.stdin.write(b"confirm\n")
                    process.stdin.flush()
                    process.stdin.close()
                    data.update({"already_active": False, "startup_timeout_seconds": STARTUP_TIMEOUT_SECONDS})
                    return success("界面已锁定。鼠标已禁止操作，按Esc退出。", data)
            if process.poll() is not None:
                raise ToolError("GUI_RUNTIME_START_FAILED", "GUI后台运行器启动后立即退出。",
                                {"exit_code": process.returncode})
            time.sleep(0.05)
        raise ToolError("GUI_RUNTIME_START_TIMEOUT", "GUI后台运行器未在启动时限内完成确认。",
                        {"startup_timeout_seconds": STARTUP_TIMEOUT_SECONDS})
    except BaseException as exc:
        details = rollback_start(process, lock_id, known_state)
        if not isinstance(exc, Exception):
            raise
        error = exc if isinstance(exc, ToolError) else ToolError(
            "GUI_RUNTIME_STATE_ACCESS_FAILED" if isinstance(exc, OSError) else "GUI_RUNTIME_START_FAILED",
            "GUI启动未完成。", {"cause_type": type(exc).__name__})
        error.details.update(details)
        error.message += " 本次创建的运行器已退出，界面锁已释放。" if details["released"] else " 未能确认释放，请按Esc退出；不要继续操作。"
        if error is exc:
            raise
        raise error from exc


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
                return start_lock(workspace, project_id, session_id, float(payload.get("idle_timeout_seconds", 120)))
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
    except OSError as exc:
        return failure(ToolError("GUI_RUNTIME_STATE_ACCESS_FAILED", "GUI状态访问失败，不能确认当前锁状态；如界面仍被锁定，请按Esc退出。",
                                 {"active": None, "state_file": str(STATE_PATH), "winerror": getattr(exc, "winerror", None)}))
    except Exception as exc:
        return failure(ToolError("GUI_RUNTIME_INTERNAL_ERROR", "GUI后台运行器工具执行失败。", {"reason": str(exc)}))


if __name__ == "__main__":
    run_tool(run)
