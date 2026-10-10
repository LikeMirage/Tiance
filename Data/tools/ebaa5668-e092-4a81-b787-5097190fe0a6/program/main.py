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
import time

from tiance_runtime import run_tool
from annotation_store import AnnotationError, AnnotationStore, read_json, validate, package_version


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.GetExitCodeProcess.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


def process_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        raise AnnotationError("ANNOTATION_STATE_INVALID", "标注进程编号无效。")
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return False
        raise AnnotationError("ANNOTATION_PROCESS_UNKNOWN", "无法确认标注进程状态。")
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise AnnotationError("ANNOTATION_PROCESS_UNKNOWN", "无法确认标注进程状态。")
        return code.value == 259
    finally:
        kernel32.CloseHandle(handle)


@contextmanager
def mutex(root):
    root.mkdir(parents=True, exist_ok=True)
    with (root / "annotation-control.lock").open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if not handle.tell():
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + 5
        while True:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise AnnotationError("ANNOTATION_BUSY", "其他标注请求仍在处理中。")
                time.sleep(0.05)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def current_context():
    values = [str(os.environ.get(name, "")).strip() for name in ("TIANCE_WORKSPACE_ROOT", "TIANCE_PROJECT_ID", "TIANCE_SESSION_ID")]
    if not all(values) or not Path(values[0]).is_dir():
        raise AnnotationError("GUI_CONTEXT_UNAVAILABLE", "标注工具必须在项目会话中运行。")
    return Path(values[0]).resolve(), values[1]


def endpoint(path, workspace, project_id):
    if not path.exists():
        return None
    state = read_json(path)
    if state.get("project_id") != project_id or str(Path(state.get("workspace", "")).resolve()).casefold() != str(workspace).casefold():
        raise AnnotationError("ANNOTATION_OWNER_MISMATCH", "标注运行器不属于当前项目。")
    if not process_alive(state.get("pid")):
        path.unlink(missing_ok=True)
        return None
    if state.get("status") != "ready":
        raise AnnotationError("ANNOTATION_RUNTIME_UNAVAILABLE", "标注运行器尚未就绪。")
    return state


def rpc(state, payload, *, timeout=25):
    request = {"token": state["token"], "project_id": state["project_id"], "payload": payload}
    try:
        with socket.create_connection(("127.0.0.1", int(state["port"])), timeout=timeout) as connection:
            connection.sendall((json.dumps(request, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))
            data = bytearray()
            while len(data) <= 2_000_000 and b"\n" not in data:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                data.extend(chunk)
            if len(data) > 2_000_000:
                raise AnnotationError("RESPONSE_TOO_LARGE", "标注响应超过2MB。")
            result = json.loads(bytes(data).split(b"\n", 1)[0])
            if not isinstance(result, dict):
                raise ValueError("response is not an object")
            return result
    except (OSError, ValueError, KeyError) as exc:
        raise AnnotationError("ANNOTATION_RESPONSE_UNKNOWN", "无法确认标注请求是否生效，先list核对，避免重复draw。") from exc


def retire_old_runtime(state, path, store):
    """Graceful handover uses the old authenticated RPC; saved annotations survive."""
    visible_groups = [group["gui_session_id"] for group in store.groups() if group["display_open"]]
    result = rpc(state, {"action": "close"}, timeout=10)
    if not result.get("ok"):
        raise AnnotationError("ANNOTATION_UPGRADE_FAILED", "旧标注进程未确认关闭，未启动第二个显示进程。")
    deadline = time.monotonic() + 3
    while path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    if path.exists():
        raise AnnotationError("ANNOTATION_UPGRADE_PENDING", "旧标注进程尚未退出，稍后重试。")
    # Preserve each group's visibility through the handover, including groups
    # that were already hidden. Updating hidden annotations must not reopen them.
    for gui_id in visible_groups:
        group = store.load(gui_id)
        group["display_open"] = bool(group["annotations"])
        store.save(group)


def launch(workspace, project_id, path, payload):
    token = secrets.token_hex(32)
    helper = Path(__file__).with_name("overlay_helper.py")
    env = os.environ.copy()
    paths = os.pathsep.join(dict.fromkeys([str(helper.parent), *(str(Path(p).resolve()) for p in sys.path if p and Path(p).exists())]))
    # The embedded Python ._pth ignores PYTHONPATH; inherit explicit tool/runtime paths.
    launcher = ("import os,runpy,sys;entry=sys.argv.pop(1);paths=sys.argv.pop(1).split(os.pathsep);"
                "sys.path[:0]=paths;sys.argv[0]=entry;runpy.run_path(entry,run_name='__main__')")
    child = subprocess.Popen([sys.executable, "-c", launcher, str(helper), paths, "--workspace", str(workspace), "--project-id", project_id,
                              "--state-file", str(path), "--token", token], cwd=str(helper.parent), env=env,
                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=0x00000008 | 0x00000200 | 0x08000000, close_fds=True)
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if path.exists():
                state = read_json(path)
                if state.get("token") == token and state.get("pid") == child.pid:
                    if state.get("status") == "failed":
                        raise AnnotationError("ANNOTATION_START_FAILED", state.get("error", "标注进程启动失败。"))
                    if state.get("status") == "ready":
                        if child.stdin is not None:
                            child.stdin.write(b"confirm\n")
                            child.stdin.flush()
                            child.stdin.close()
                        return rpc(state, payload)
            if child.poll() is not None:
                raise AnnotationError("ANNOTATION_START_FAILED", "标注进程启动后退出。")
            time.sleep(0.05)
        raise AnnotationError("ANNOTATION_START_TIMEOUT", "标注进程启动超时。")
    except BaseException:
        # Only reap the process handle created by this invocation, never an arbitrary PID.
        if child.stdin is not None and not child.stdin.closed:
            child.stdin.close()
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=3)
        if path.exists() and read_json(path).get("token") == token:
            path.unlink(missing_ok=True)
        raise


def attach_image(result, root):
    value = result.pop("image_path", None)
    if value:
        path = Path(value).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.suffix != ".png":
            raise AnnotationError("GUI_IMAGE_PATH_INVALID", "标注效果图路径无效。", {"data": result.get("data")})
        result["content"] = [{"type": "resource_link", "uri": "tiance-local:" + path.as_uri().removeprefix("file:"),
                              "name": path.name, "mimeType": "image/png", "size": path.stat().st_size,
                              "annotations": {"audience": ["assistant"], "priority": 1.0}}]
    return result


def run(payload):
    try:
        if os.name != "nt":
            raise AnnotationError("PLATFORM_NOT_SUPPORTED", "标注显示目前支持Windows。")
        validate(payload)
        workspace, project_id = current_context()
        store = AnnotationStore(workspace, project_id)
        path = store.root / "annotation-runtime.json"
        with mutex(store.root):
            state = endpoint(path, workspace, project_id)
            upgraded = bool(state and state.get("runtime_version") != package_version()
                            and payload["action"] in {"draw", "show", "update", "delete"})
            if upgraded:
                retire_old_runtime(state, path, store)
                state = None
            if state:
                result = rpc(state, payload)
            elif upgraded or payload["action"] in {"draw", "show"}:
                result = launch(workspace, project_id, path, payload)
            else:
                result = store.apply(payload)
                result["data"].update(display_running=False, visible_count=0)
            if not result.get("data", {}).get("display_running", True):
                deadline = time.monotonic() + 3
                while path.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
            data = result.get("data", {})
            if upgraded:
                data["runtime_upgraded"] = True
            for group in data.get("groups", []):
                group["display_visible"] = bool(data.get("display_running") and group["display_open"] and group["annotations"])
            return attach_image(result, store.root)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "error_info": {"code": getattr(exc, "code", "ANNOTATION_ERROR"),
                "details": getattr(exc, "details", {})}, "warnings": []}


if __name__ == "__main__":
    run_tool(run)
