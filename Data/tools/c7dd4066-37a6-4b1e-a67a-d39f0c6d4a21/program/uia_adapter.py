"""Optional UIA capability; no dependency on Tiance application services or schemas."""
from __future__ import annotations

import json
import ctypes
from ctypes import wintypes
import math
import queue
import re
import subprocess
import threading
import time
from pathlib import Path
from uuid import uuid4


SNAPSHOT_ID = re.compile(r"^uia_[a-f0-9]{32}$")
ELEMENT_ID = re.compile(r"^(uia_[a-f0-9]{32}):(\d+)$")
MUTATIONS = {"invoke", "set_value", "select", "toggle", "expand", "collapse", "focus"}


class WorkerJob:
    """The worker must also exit if its owning GUI runtime is forcibly killed."""
    def __init__(self, pid):
        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                        ("max_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]
        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", ctypes.c_uint64 * 6),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.api.SetInformationJobObject.restype = wintypes.BOOL
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.AssignProcessToJobObject.restype = wintypes.BOOL
        self.api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.api.OpenProcess.restype = wintypes.HANDLE
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        process_handle = None
        try:
            limits = Extended()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            process_handle = self.api.OpenProcess(0x0101, False, pid)  # SET_QUOTA | TERMINATE
            if not process_handle or not self.api.AssignProcessToJobObject(self.handle, process_handle):
                raise ctypes.WinError(ctypes.get_last_error())
        except Exception:
            self.close()
            raise
        finally:
            if process_handle:
                self.api.CloseHandle(process_handle)

    def close(self):
        handle, self.handle = self.handle, None
        if handle:
            self.api.CloseHandle(handle)


class UiaAdapter:
    def __init__(self, host, error_type, window_info, foreground, read_json, write_json):
        self.host, self.Error = host, error_type
        self.window_info, self.foreground = window_info, foreground
        self.read_json, self.write_json = read_json, write_json
        self.process = None
        self.responses = None
        self.job = None

    def close(self):
        process, self.process = self.process, None
        self.responses = None
        if self.job is not None:
            self.job.close()
            self.job = None
        if process is not None:
            try:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass  # Releasing the desktop lock must not depend on worker cleanup.
            finally:
                for stream in (process.stdin, process.stdout):
                    if stream is not None:
                        try:
                            stream.close()
                        except (OSError, ValueError):
                            pass

    def _start(self):
        if self.process is not None and self.process.poll() is None:
            return
        self.close()
        self.process = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Mta", "-ExecutionPolicy", "Bypass",
             "-File", str(Path(__file__).with_name("uia_worker.ps1"))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            encoding="utf-8", text=True, bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.job = WorkerJob(self.process.pid)
        self.responses = queue.Queue()
        def receive(stream, responses):
            try:
                for line in stream:
                    responses.put(line)
            except (OSError, ValueError):
                pass  # The owning runtime closes the worker on cancellation.
            finally:
                responses.put(None)
        threading.Thread(target=receive, args=(self.process.stdout, self.responses), daemon=True).start()

    def _query(self, request, timeout):
        mutating = request["operation"] in MUTATIONS
        sent = False
        answered = False
        deadline = time.monotonic() + timeout
        try:
            if self.host.cancel_event.is_set():
                raise self.Error("GUI_RUNTIME_STOPPED", "界面锁已退出。")
            self._start()
            request = {**request, "request_id": uuid4().hex}
            # Once writing starts, a failed response cannot prove no action occurred.
            sent = True
            def send(stream, responses, payload):
                try:
                    stream.write(payload)
                    stream.flush()
                except (OSError, ValueError) as error:
                    responses.put(error)
            # Pipe writes can block while a provider is starting or hung; the
            # request deadline and cancellation must remain effective then too.
            threading.Thread(target=send, args=(self.process.stdin, self.responses,
                             json.dumps(request, ensure_ascii=False) + "\n"), daemon=True).start()
            while True:
                if self.host.cancel_event.is_set():
                    raise self.Error("GUI_RUNTIME_STOPPED", "UIA调用已取消；已提交的控件动作可能已经生效。")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise self.Error("UIA_TIMEOUT", f"UIA调用超过配置的{timeout:g}秒；未返回不完整列表，也不会自动重试。")
                try:
                    line = self.responses.get(timeout=min(0.1, remaining))
                except queue.Empty:
                    continue
                if line is None:
                    raise self.Error("UIA_WORKER_STOPPED", "UIA进程已退出，未收到完整结果。")
                if isinstance(line, Exception):
                    raise self.Error("UIA_WORKER_STOPPED", "UIA请求写入中断，未收到完整结果。")
                result = json.loads(line.lstrip("\ufeff"))
                if result.get("request_id") != request["request_id"]:
                    raise self.Error("UIA_INVALID_RESPONSE", "UIA返回的请求身份不匹配。")
                answered = True
                if not result.get("ok"):
                    raise self.Error(result.get("code", "UIA_FAILED"), result.get("message", "UIA调用失败。"),
                                     {"execution_status": result.get("execution_status", "not_started")})
                return result
        except Exception as error:
            if not answered:
                self.close()
            exc = error if isinstance(error, self.Error) else self.Error("UIA_UNAVAILABLE", "UIA进程未返回有效结果。")
            exc.details.setdefault("execution_status", "unknown" if mutating and sent else "not_started")
            raise exc

    def _folder(self, session):
        return self.host._session_dir(session["gui_session_id"]) / "uia"

    def _snapshot(self, session, snapshot_id):
        if not isinstance(snapshot_id, str) or not SNAPSHOT_ID.fullmatch(snapshot_id):
            raise self.Error("UIA_SNAPSHOT_INVALID", "控件快照编号无效。")
        path = self._folder(session) / f"{snapshot_id}.json"
        if not path.is_file():
            raise self.Error("UIA_SNAPSHOT_NOT_FOUND", "控件快照不属于当前GUI会话，请重新inspect。")
        snapshot = self.read_json(path)
        if snapshot.get("lock_id") != self.host.lock_id or snapshot.get("gui_session_id") != session["gui_session_id"]:
            raise self.Error("UIA_SNAPSHOT_NOT_FOUND", "控件快照不属于当前界面锁。")
        return snapshot

    def handle(self, arguments):
        action = arguments.get("action")
        session = self.host._load_session(str(arguments.get("gui_session_id", "")))
        timeout = arguments.get("timeout_seconds", 10)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 1 <= timeout <= 60:
            raise self.Error("INVALID_ARGUMENT", "timeout_seconds必须在1到60秒之间。")
        if action == "inspect":
            snapshot_id = arguments.get("snapshot_id")
            offset, limit = arguments.get("offset", 0), arguments.get("limit", 100)
            if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
                raise self.Error("INVALID_ARGUMENT", "offset必须非负，limit必须在1到500之间。")
            if snapshot_id:
                snapshot = self._snapshot(session, snapshot_id)
            else:
                if offset:
                    raise self.Error("INVALID_ARGUMENT", "翻页必须提供上一页的snapshot_id。")
                hwnd = session["target"].get("hwnd") if session["target"]["type"] == "window" else self.foreground()["hwnd"]
                window = self.window_info(int(hwnd or 0))
                if session["target"]["type"] == "window" and window["process_id"] != session["target"]["process_id"]:
                    raise self.Error("WINDOW_IDENTITY_CHANGED", "窗口身份已变化，请重新选择窗口。")
                result = self._query({"operation": "inspect", "hwnd": window["hwnd"], "process_id": window["process_id"]}, timeout)
                snapshot_id = "uia_" + uuid4().hex
                snapshot = {"snapshot_id": snapshot_id, "gui_session_id": session["gui_session_id"],
                            "lock_id": self.host.lock_id, "window": window, "elements": result["elements"]}
                self.write_json(self._folder(session) / f"{snapshot_id}.json", snapshot)
            query = str(arguments.get("query", "")).casefold()
            matches = [{"element_id": f"{snapshot_id}:{i}", **item} for i, item in enumerate(snapshot["elements"])
                       if query in str(item.get("name", "")).casefold() or query in str(item.get("automation_id", "")).casefold()]
            page = matches[offset:offset + limit]
            next_offset = offset + len(page)
            return {"ok": True, "summary": f"返回{len(page)}个控件，共{len(matches)}个匹配项。",
                    "data": {"snapshot_id": snapshot_id, "window": snapshot["window"], "elements": page,
                             "total": len(matches), "complete": next_offset >= len(matches),
                             "next_offset": next_offset if next_offset < len(matches) else None}, "warnings": []}
        if action not in MUTATIONS | {"read"}:
            raise self.Error("INVALID_ARGUMENT", "不支持的UIA操作。")
        match = ELEMENT_ID.fullmatch(str(arguments.get("element_id", "")))
        if not match:
            raise self.Error("UIA_ELEMENT_INVALID", "控件编号无效，请使用inspect实际返回的element_id。")
        snapshot = self._snapshot(session, match[1])
        index = int(match[2])
        if index >= len(snapshot["elements"]):
            raise self.Error("UIA_ELEMENT_INVALID", "该控件不在已读取的快照中。")
        expected = {key: snapshot["elements"][index][key] for key in
                    ("runtime_id", "process_id", "name", "automation_id", "control_type", "class_name")}
        window = self.window_info(snapshot["window"]["hwnd"])
        if window["process_id"] != snapshot["window"]["process_id"]:
            raise self.Error("WINDOW_IDENTITY_CHANGED", "窗口身份已变化，请重新inspect。")
        request = {"operation": action, "hwnd": window["hwnd"], "process_id": window["process_id"], "expected": expected}
        if action == "read":
            result = self._query(request, timeout)
            return {"ok": True, "summary": "已重新读取控件当前状态。",
                    "data": {"element_id": arguments["element_id"], **result["element"]}, "warnings": []}
        delay = self.host._screenshot_delay(arguments)
        self.host._validate_window_target({"type": "window", "hwnd": window["hwnd"], "process_id": window["process_id"]})
        if action == "set_value":
            if not isinstance(arguments.get("text"), str) or len(arguments["text"]) > 100000:
                raise self.Error("INVALID_ARGUMENT", "set_value必须提供text字符串，最多100000字符，超出不执行。")
            request["value"] = arguments["text"]
        mouse_before, keyboard_before = self.host.external_mouse_events, self.host.external_keyboard_events
        try:
            result = self._query(request, timeout)
        except self.Error as error:
            status = error.details.get("execution_status", "unknown")
            error.details.update({"element_id": arguments["element_id"], "foreground_window": self.foreground(),
                                  "performed": None if status == "unknown" else False})
            if status == "unknown":
                try:
                    self.host._invalidate_frame(session)
                except Exception:
                    self.host.request_stop("action_state_write_failed")
                error.details["recovery"] = "动作可能已生效；先重新观察或read控件状态，不要直接重试。"
            raise
        self.host.input_events_sent += 1
        data = {"type": action, "element_id": arguments["element_id"], "method": "UIAutomation"}
        if action == "set_value":
            data["character_count"] = len(arguments["text"])
        return self.host._finish_action(session=session, mouse_before=mouse_before, keyboard_before=keyboard_before,
                                        action_name="uia_" + action, action_data=data, screenshot_delay_seconds=delay)
