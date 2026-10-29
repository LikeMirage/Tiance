"""Shell-owned close handshake. No renderer is required for the fallback UI."""
from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from app.startup_timing import mark

FRONTEND_RESPONSE_SECONDS = 5.0
BACKEND_WAIT_NOTICE_SECONDS = 30.0


@dataclass
class CloseRequest:
    request_id: str
    intent: str = "close"
    phase: str = "frontend"
    deadline: float = 0.0
    prompt_open: bool = False
    error: str = ""


class WindowCloseCoordinator:
    def __init__(self, *, dispatch: Callable[[str, str], None], prepare: Callable[[], None],
                 destroy: Callable[[], None], prompt: Callable[[str, str], str]) -> None:
        self._dispatch = dispatch
        self._prepare = prepare
        self._destroy = destroy
        self._prompt = prompt
        self._lock = threading.RLock()
        self._request: CloseRequest | None = None
        self._timer: threading.Timer | None = None
        self._disposed = False
        self._dispatch_running = False

    def request(self, intent: str = "close") -> str | None:
        with self._lock:
            if self._disposed:
                return None
            if self._request is not None:
                return self._request.request_id
            request = CloseRequest(uuid.uuid4().hex, intent=intent,
                                   deadline=time.monotonic() + FRONTEND_RESPONSE_SECONDS)
            self._request = request
            self._arm(request)
            # A broken WebView may never return from evaluate_js. Never accumulate
            # more dispatch threads while that call is stuck; the watchdog is separate.
            if not self._dispatch_running:
                self._dispatch_running = True
                self._spawn(lambda: self._send(request, intent))
            return request.request_id

    def report(self, request_id: str, state: str) -> bool:
        if state not in {"waiting", "saving", "cancelled"}:
            raise ValueError("Unknown window close state")
        with self._lock:
            request = self._request
            if request is None or request.request_id != request_id or request.phase != "frontend":
                return False
            if state == "cancelled":
                if request.prompt_open:
                    request.phase = "cancelled"
                else:
                    self._reset()
            else:
                request.deadline = time.monotonic() + FRONTEND_RESPONSE_SECONDS
            return True

    def complete(self, request_id: str) -> bool:
        with self._lock:
            request = self._request
            if (request is None or request.request_id != request_id
                    or request.phase != "frontend" or request.prompt_open):
                return False
            self._begin_settlement(request)
        self._settle(request)
        return True

    def dispose(self) -> None:
        with self._lock:
            self._disposed = True
            self._reset()

    def _reset(self) -> None:
        self._request = None
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _arm(self, request: CloseRequest) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(max(0.01, request.deadline - time.monotonic()), self._check, (request,))
        self._timer.daemon = True
        self._timer.start()

    @staticmethod
    def _spawn(action: Callable[[], None]) -> None:
        threading.Thread(target=action, name="tiance-window-close", daemon=True).start()

    def _send(self, request: CloseRequest, intent: str) -> None:
        try:
            with self._lock:
                if self._request is not request or request.phase != "frontend":
                    return
            self._dispatch(request.request_id, intent)
        except Exception as exc:
            mark("window close: frontend dispatch failed", error=type(exc).__name__)
            with self._lock:
                if self._request is request and request.phase == "frontend":
                    request.deadline = time.monotonic()
                    self._arm(request)
        finally:
            with self._lock:
                self._dispatch_running = False
                current = self._request
                if current is not None and current is not request and current.phase == "frontend":
                    self._dispatch_running = True
                    self._spawn(lambda: self._send(current, current.intent))

    def _check(self, request: CloseRequest) -> None:
        with self._lock:
            if self._request is not request or request.prompt_open or self._disposed:
                return
            if request.deadline > time.monotonic():
                self._arm(request)
                return
            reason = request.phase
            if reason not in {"frontend", "settling", "failed"}:
                return
            request.prompt_open = True
        # This runs on a timer thread, never inside the blocked JS dispatch or
        # backend preparation call, and never holds the coordinator lock in UI.
        try:
            choice = self._prompt(reason, request.error)
        except Exception as exc:
            mark("window close: native prompt failed", error=type(exc).__name__)
            choice = "wait"
        with self._lock:
            if self._request is not request or self._disposed:
                return
            request.prompt_open = False
            if request.phase == "cancelled":
                self._reset()
                return
            if request.phase == "ready":
                action = "destroy"
            elif request.phase != reason:
                # Settlement failed while its slow-operation prompt was open.
                request.deadline = time.monotonic()
                self._arm(request)
                return
            elif reason == "frontend" and choice == "exit":
                self._begin_settlement(request)
                action = "settle"
            elif reason == "failed" and choice == "retry":
                self._begin_settlement(request)
                action = "settle"
            elif reason in {"settling", "failed"} and choice == "force":
                action = "destroy"
            elif reason == "failed" and choice == "cancel":
                self._reset()
                return
            else:
                request.deadline = time.monotonic() + (
                    FRONTEND_RESPONSE_SECONDS if reason == "frontend" else BACKEND_WAIT_NOTICE_SECONDS)
                self._arm(request)
                if reason == "frontend" and not self._dispatch_running:
                    # A recovered/reloaded page may have missed the original event.
                    # Same ID is idempotent for an already participating frontend.
                    self._dispatch_running = True
                    self._spawn(lambda: self._send(request, request.intent))
                return
        if action == "settle":
            self._settle(request, propagate=False)
        else:
            self._finish(request)

    def _begin_settlement(self, request: CloseRequest) -> None:
        request.phase = "settling"
        request.error = ""
        request.deadline = time.monotonic() + BACKEND_WAIT_NOTICE_SECONDS
        self._arm(request)

    def _settle(self, request: CloseRequest, *, propagate: bool = True) -> None:
        try:
            self._prepare()
        except Exception as exc:
            self._failed(request, exc)
            if propagate:
                raise
            return
        with self._lock:
            if self._request is not request or request.phase != "settling":
                return
            request.phase = "ready"
            if request.prompt_open:
                return  # Do not destroy a window beneath an outstanding native dialog.
        self._finish(request, propagate=propagate)

    def _failed(self, request: CloseRequest, exc: Exception) -> None:
        with self._lock:
            if self._request is not request or request.phase == "destroying":
                return
            request.phase = "failed"
            request.error = str(exc)
            request.deadline = time.monotonic()
            self._arm(request)

    def _finish(self, request: CloseRequest, *, propagate: bool = False) -> None:
        with self._lock:
            if self._request is not request or request.phase == "destroying":
                return
            request.phase = "destroying"
            if self._timer is not None:
                self._timer.cancel()
        try:
            self._destroy()
        except Exception as exc:
            with self._lock:
                if self._request is request:
                    request.phase = "failed"
            self._failed(request, exc)
            if propagate:
                raise
        else:
            self.dispose()


def show_native_exit_prompt(hwnd: int | None, reason: str, error: str) -> str:
    """Win32 dialog on its own thread; no evaluate_js, WebView, or HTTP required."""
    import ctypes
    from ctypes import wintypes

    if reason == "frontend":
        title = "天策界面未响应"
        message = ("界面未响应关闭请求。继续退出可能丢失尚未保存的编辑内容。\n\n"
                   "选择“是”：退出，仍会等待后台任务收尾和记录保存。\n选择“否”：继续等待界面响应。")
        choices, flags = {6: "exit", 7: "wait"}, 0x00000004
    elif reason == "settling":
        title = "天策正在退出"
        message = ("后台任务仍在收尾或保存，暂时不能正常退出。\n\n"
                   "是否强制退出？强制退出可能丢失未完成的数据或中断文件写入。\n选择“否”继续等待。")
        choices, flags = {6: "force", 7: "wait"}, 0x00000004
    else:
        title = "天策退出失败"
        message = (f"{error}\n\n选择“是”：重试正常退出。\n"
                   "选择“否”：强制退出，可能丢失未完成的数据或中断文件写入。\n选择“取消”：保留窗口。")
        choices, flags = {6: "retry", 7: "force", 2: "cancel"}, 0x00000003
    message_box = ctypes.windll.user32.MessageBoxW
    message_box.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    message_box.restype = ctypes.c_int
    # Default to waiting/cancel, never to forced exit. Bring only this requested dialog forward.
    default = 0x00000200 if reason == "failed" else 0x00000100
    result = message_box(hwnd, message, title, flags | default | 0x00000030 | 0x00010000)
    return choices.get(result, "wait")
