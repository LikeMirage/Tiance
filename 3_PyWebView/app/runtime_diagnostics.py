"""Shell-owned sampling continues after renderer failure. No recovery or replay."""
import json
import math
from pathlib import Path
import sys
from threading import Event, Lock, Thread
from time import monotonic

from app.diagnostic_log import DiagnosticLog
from app.diagnostic_processes import collect_process_metrics


RENDERER_FIELDS = frozenset("""
    uptime_ms interval_lag_ms sample_duration_ms visible development heap_available
    heap_used heap_total heap_limit dom_nodes resources js_errors unhandled_rejections
    diagnostic_source_errors cached_sessions cached_messages cached_chars durable_messages
    durable_chars process_items tool_items running_messages largest_session_chars
    history_requests markdown_documents markdown_nodes markdown_chars
    mobile_bridge_instances mobile_poll_age_ms mobile_poll_errors mobile_pending
""".split())


class RuntimeDiagnostics:
    def __init__(self, root: Path, settings, *, collector=collect_process_metrics, interval=30):
        self.log = DiagnosticLog(root / "Data" / "logs")
        self.settings = settings
        self.collector = collector
        self.interval = interval
        self.wake = Event()
        self.stopped = Event()
        self.lock = Lock()
        self.thread = None
        self.core = None
        self.window = None
        self.on_ui_thread = None
        self.started = monotonic()
        self.last_renderer = None
        self.last_write = float("-inf")
        self.heartbeat_stale = False
        try:
            self.version = str(json.loads((root / "system/version.json").read_text(encoding="utf-8"))["version"])[:32]
        except (OSError, ValueError, KeyError):
            self.version = "unknown"

    def start(self, window, on_ui_thread):
        if self.thread is not None or self.stopped.is_set():
            return
        self.window, self.on_ui_thread = window, on_ui_thread
        window.events.shown += self.install
        window.events.loaded += self.loaded
        self.log.write("monitor_started", version=self.version, interval_seconds=self.interval,
                       runtime_mode=getattr(self.settings, "webview2_runtime_mode", "unknown"))
        self.thread = Thread(target=self._run, name="tiance-diagnostics", daemon=True)
        self.thread.start()
        self.install()

    def install(self, *_args):
        if sys.platform != "win32" or self.stopped.is_set():
            return
        def bind():
            control = getattr(getattr(self.window, "native", None), "webview", None)
            core = getattr(control, "CoreWebView2", None)
            if core is None or core == self.core or self.stopped.is_set():
                return
            self._unbind()
            self.core = core
            core.ProcessFailed += self.process_failed
            core.NavigationStarting += self.navigation_starting
            self.log.write("webview_bound", browser_version=str(core.Environment.BrowserVersionString)[:80])
        try:
            self.on_ui_thread(bind)
        except Exception as exc:
            self.log.write("monitor_bind_error", error_type=type(exc).__name__)

    def loaded(self, *_args):
        self.install()
        self.log.write("document_loaded")
        self.wake.set()

    def navigation_starting(self, *_args):
        self.log.write("navigation_starting")

    def process_failed(self, _sender, args):
        # The UI thread only writes a small event; process enumeration is elsewhere.
        self.log.write("webview_process_failed", kind=str(args.ProcessFailedKind)[:80],
                       reason=str(getattr(args, "Reason", "unknown"))[:80],
                       exit_code=int(getattr(args, "ExitCode", 0)))
        self.wake.set()

    def record_renderer(self, payload) -> bool:
        if not isinstance(payload, dict) or self.stopped.is_set():
            return False
        clean = {key: value for key in RENDERER_FIELDS if key in payload
                 and type(value := payload[key]) in (int, float)
                 and 0 <= value <= 1e16 and math.isfinite(value)}
        if not clean:
            return False
        now = monotonic()
        with self.lock:
            self.last_renderer = now
            if now - self.last_write < 10:
                return True
            self.last_write = now
        return self.log.write("renderer_sample", metrics=clean)

    def sample(self):
        with self.lock:
            age = None if self.last_renderer is None else max(0, monotonic() - self.last_renderer)
        stale = (age if age is not None else monotonic() - self.started) > 90
        if stale != self.heartbeat_stale:
            self.heartbeat_stale = stale
            # A hidden/throttled page can also miss a heartbeat; this is not a crash verdict.
            self.log.write("renderer_heartbeat_gap" if stale else "renderer_heartbeat_resumed", age_seconds=age)
        self.log.write("process_sample", renderer_age_seconds=age, **self.collector())

    def _run(self):
        while not self.stopped.is_set():
            try:
                self.sample()
            except Exception as exc:
                self.log.write("monitor_sample_error", error_type=type(exc).__name__)
            self.wake.wait(self.interval)
            self.wake.clear()

    def _unbind(self):
        if self.core is not None:
            try:
                self.core.ProcessFailed -= self.process_failed
                self.core.NavigationStarting -= self.navigation_starting
            except Exception:
                pass
            self.core = None

    def dispose(self):
        if self.stopped.is_set():
            return
        self.stopped.set()
        self.wake.set()
        if self.window is not None:
            try:
                self.window.events.shown -= self.install
                self.window.events.loaded -= self.loaded
                self.on_ui_thread(self._unbind)
            except Exception:
                pass
        if self.thread is not None:
            self.thread.join(timeout=1)
            self.log.write("monitor_stopped")
        self.log.close()
