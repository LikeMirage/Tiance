from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import tempfile
from typing import Any

from tiance_runtime import run_tool


METHOD = "mouse"
STATE_PATH = Path(tempfile.gettempdir()) / "Tiance" / "gui-control" / "active-lock.json"
RPC_TIMEOUT_SECONDS = 130.0
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
        self.code, self.message, self.details = code, message, details or {}


def failure(error: ToolError) -> dict[str, Any]:
    return {"ok": False, "error": f"{error.code}: {error.message}", "error_info": {"code": error.code, "message": error.message, "details": error.details}, "warnings": []}


def process_alive(value: Any) -> bool:
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return False
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        error = int(kernel32.GetLastError())
        if error == 87:  # Invalid PID: the process no longer exists.
            return False
        raise ToolError("GUI_RUNTIME_PROCESS_STATUS_UNKNOWN", "无法读取运行器进程状态，不能认为界面锁已退出。",
                        {"pid": pid, "active": None, "winerror": error})
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise ToolError("GUI_RUNTIME_PROCESS_STATUS_UNKNOWN", "无法确认运行器进程是否已经退出。",
                            {"pid": pid, "active": None})
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def context_and_state() -> tuple[Path, dict[str, Any]]:
    workspace_value = str(os.environ.get("TIANCE_WORKSPACE_ROOT") or "").strip()
    project_id = str(os.environ.get("TIANCE_PROJECT_ID") or "").strip()
    session_id = str(os.environ.get("TIANCE_SESSION_ID") or "").strip()
    if not workspace_value or not project_id or not session_id:
        raise ToolError("GUI_CONTEXT_UNAVAILABLE", "GUI工具必须在天策项目会话中运行。")
    workspace = Path(workspace_value).resolve(strict=False)
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ToolError("GUI_LOCK_REQUIRED", "请先调用gui_runtime start锁定界面，再调用gui_inspect start。") from exc
    except OSError as exc:
        raise ToolError("GUI_RUNTIME_STATE_ACCESS_FAILED", "无法访问GUI状态文件，当前锁状态未知；如界面仍锁定，请按Esc退出。",
                        {"active": None, "state_file": str(STATE_PATH), "winerror": getattr(exc, "winerror", None)}) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolError("GUI_RUNTIME_STATE_INVALID", "GUI后台运行器状态损坏，请重新调用gui_inspect start。") from exc
    if not isinstance(state, dict) or state.get("status") != "active" or not process_alive(state.get("pid")):
        raise ToolError("GUI_LOCK_REQUIRED", "界面锁已退出，请调用gui_runtime start后重新查看界面。")
    if state.get("input_mode") != "blocked":
        raise ToolError("GUI_LOCK_REQUIRED", "旧的无锁运行器仍在运行，请调用gui_runtime stop后重新start。")
    actual_workspace = Path(str(state.get("workspace") or "")).resolve(strict=False)
    if state.get("project_id") != project_id or state.get("session_id") != session_id or str(actual_workspace).casefold() != str(workspace).casefold():
        raise ToolError("GUI_RUNTIME_OWNED_BY_OTHER_SESSION", "GUI临时会话属于另一个项目会话。")
    return workspace, state


def call_helper(state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    request = {"token": state.get("token"), "project_id": state.get("project_id"), "session_id": state.get("session_id"), "method": METHOD, "payload": payload}
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
        raise ToolError("GUI_RESPONSE_TOO_LARGE", "GUI操作结果超过2MB限制。")
    try:
        response = json.loads(bytes(data).split(b"\n", 1)[0].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolError("GUI_INVALID_RESPONSE", "GUI辅助进程返回了无效结果。") from exc
    if not isinstance(response, dict):
        raise ToolError("GUI_INVALID_RESPONSE", "GUI辅助进程返回结果不是对象。")
    return response


def attach_image(response: dict[str, Any], workspace: Path) -> dict[str, Any]:
    raw_path = response.pop("image_path", None)
    if raw_path is None:
        response.setdefault("warnings", [])
        return response
    image_path = Path(str(raw_path)).resolve(strict=False)
    allowed_root = (workspace / ".Tiance" / "gui-temp").resolve(strict=False)
    try:
        image_path.relative_to(allowed_root)
    except ValueError as exc:
        raise ToolError("GUI_IMAGE_PATH_INVALID", "GUI图片不在当前项目的临时目录中。") from exc
    if not image_path.is_file() or image_path.suffix.lower() != ".png":
        raise ToolError("GUI_IMAGE_NOT_FOUND", "GUI结果图片不存在。")
    file_uri = image_path.as_uri()
    response["content"] = [{"type": "resource_link", "uri": f"tiance-local:{file_uri.removeprefix('file:')}", "name": image_path.name, "mimeType": "image/png", "size": image_path.stat().st_size, "annotations": {"audience": ["assistant"], "priority": 1.0}}]
    response.setdefault("warnings", [])
    return response


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        if os.name != "nt":
            raise ToolError("PLATFORM_NOT_SUPPORTED", "GUI工具目前只支持Windows。")
        workspace, state = context_and_state()
        response = call_helper(state, payload)
        # 失败结果也可能包含部分执行信息和最新截图，必须完整保留。
        try:
            return attach_image(response, workspace)
        except (ToolError, OSError) as image_error:
            if not response.get("data", {}).get("execution_status"):
                raise
            # Image delivery failure must not erase already-confirmed input.
            response["data"].update({"observation_status": "unavailable", "frame_id": None,
                                     "observation_error": {"code": getattr(image_error, "code", "GUI_IMAGE_UNAVAILABLE"), "message": str(image_error)}})
            response.setdefault("warnings", []).append("动作执行结果已保留，但截图未能交付；请重新观察，勿重放已完成的动作。")
            response["summary"] = "动作执行结果已保留，截图交付失败；请查看execution_status，勿重放已完成的动作。"
            return response
    except ToolError as exc:
        return failure(exc)
    except Exception as exc:
        return failure(ToolError("GUI_INTERNAL_ERROR", "GUI鼠标工具执行失败。", {"reason": str(exc)}))


if __name__ == "__main__":
    run_tool(run)
