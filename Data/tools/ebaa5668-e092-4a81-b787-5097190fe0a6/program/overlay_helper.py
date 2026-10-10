"""Annotation display service owned by the tool package, independent of GUI locks."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import queue
import socket
import sys
import threading

from annotation_store import AnnotationError, AnnotationStore, atomic_json, read_json, package_version
from native_layer import NativeLayer, WM_WORK, WM_STOP, kernel32, user32


def failure(exc, **details):
    return {"ok": False, "error": str(exc), "error_info": {"code": getattr(exc, "code", "ANNOTATION_DISPLAY_FAILED"),
            "details": {**getattr(exc, "details", {}), **details}}, "warnings": []}


class AnnotationService:
    def __init__(self, args):
        self.args = args
        self.runtime_version = package_version()
        self.store = AnnotationStore(Path(args.workspace), args.project_id)
        self.path = Path(args.state_file)
        self.jobs = queue.Queue()
        self.stopping = threading.Event()
        self.confirmed = threading.Event()
        self.thread_id = kernel32.GetCurrentThreadId()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(8)
        self.socket.settimeout(0.25)
        self.layer = None
        self.server_thread = None

    def stop(self):
        self.stopping.set()
        user32.PostThreadMessageW(self.thread_id, WM_STOP, 0, 0)

    def user_close(self):
        try:
            self.store.apply({"action": "close"})
        finally:
            self.stop()
            if self.layer:
                self.layer.destroy_windows()

    def confirm_startup(self):
        if sys.stdin.buffer.readline().strip() == b"confirm":
            self.confirmed.set()
        else:
            self.stop()

    def startup_deadline(self):
        if not self.confirmed.wait(15):
            self.stop()

    def serve(self):
        while not self.stopping.is_set():
            try:
                connection, _ = self.socket.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with connection:
                try:
                    connection.settimeout(15)
                    raw = bytearray()
                    while len(raw) <= 2_000_000 and b"\n" not in raw:
                        chunk = connection.recv(65536)
                        if not chunk:
                            break
                        raw.extend(chunk)
                    if len(raw) > 2_000_000:
                        raise AnnotationError("REQUEST_TOO_LARGE", "标注请求超过2MB。")
                    request = json.loads(bytes(raw).split(b"\n", 1)[0])
                    if request.get("token") != self.args.token or request.get("project_id") != self.args.project_id:
                        raise AnnotationError("ANNOTATION_AUTH_FAILED", "标注运行器归属或连接凭证无效。")
                    event = threading.Event()
                    job = {"payload": request["payload"], "event": event}
                    self.jobs.put(job)
                    if not user32.PostThreadMessageW(self.thread_id, WM_WORK, 0, 0) or not event.wait(20):
                        raise AnnotationError("ANNOTATION_RESPONSE_UNKNOWN", "无法确认标注请求结果，先list核对后再修改。")
                    response = job["response"]
                except Exception as exc:
                    response = failure(exc)
                try:
                    wire = (json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
                    if len(wire) > 2_000_000:
                        wire = (json.dumps(failure(AnnotationError("RESPONSE_TOO_LARGE", "标注结果超过2MB，请指定gui_session_id查看。"))) + "\n").encode()
                    connection.sendall(wire)
                except OSError:
                    pass

    def process_jobs(self):
        while not self.jobs.empty():
            job = self.jobs.get_nowait()
            response = None
            try:
                if self.stopping.is_set():
                    raise AnnotationError("ANNOTATION_STOPPED", "标注显示已关闭，重新调用show或draw。")
                response = self.store.apply(job["payload"])
                items = [item for group in self.store.groups() if group["display_open"] for item in group["annotations"]]
                self.layer.update(items)
                response["data"]["display_running"] = bool(items)
                response["data"]["visible_count"] = len(items)
                job["response"] = response
                if not items:
                    self.stop()
            except Exception as exc:
                # Persisted IDs survive display failure; do not ask the AI to redraw blindly.
                job["response"] = failure(exc, data_saved=response is not None, data=(response or {}).get("data"))
                if response:
                    job["response"].update({key: response[key] for key in ("data", "image_path") if key in response})
                self.stop()
            finally:
                job["event"].set()

    def run(self):
        try:
            # Create the thread's message queue before publishing the RPC endpoint.
            message = wintypes.MSG()
            user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
            self.layer = NativeLayer(self.user_close)
            atomic_json(self.path, {"schema_version": 1, "workspace": str(Path(self.args.workspace).resolve()),
                                   "project_id": self.args.project_id, "token": self.args.token,
                                   "runtime_version": self.runtime_version,
                                   "pid": os.getpid(), "port": self.socket.getsockname()[1], "status": "ready"})
            self.server_thread = threading.Thread(target=self.serve, daemon=True)
            self.server_thread.start()
            threading.Thread(target=self.confirm_startup, daemon=True).start()
            threading.Thread(target=self.startup_deadline, daemon=True).start()
            while not self.stopping.is_set():
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0 or message.message == WM_STOP:
                    break
                if message.message == WM_WORK:
                    self.process_jobs()
                else:
                    user32.TranslateMessage(ctypes.byref(message))
                    user32.DispatchMessageW(ctypes.byref(message))
            return 0
        except Exception as exc:
            atomic_json(self.path, {"pid": os.getpid(), "token": self.args.token, "project_id": self.args.project_id,
                                   "workspace": self.args.workspace, "status": "failed", "error": str(exc)})
            return 1
        finally:
            self.stopping.set()
            self.socket.close()
            if self.server_thread:
                self.server_thread.join(timeout=2)
            if self.layer:
                self.layer.close()
            try:
                self.store.apply({"action": "close"})
            except Exception:
                pass
            try:
                state = read_json(self.path)
                if state.get("token") == self.args.token and state.get("status") != "failed":
                    self.path.unlink(missing_ok=True)
            except (OSError, AnnotationError):
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for option in ("workspace", "project-id", "state-file", "token"):
        parser.add_argument("--" + option, required=True)
    raise SystemExit(AnnotationService(parser.parse_args()).run())
