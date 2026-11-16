import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.diagnostic_log import DiagnosticLog
from app import diagnostic_processes, runtime_diagnostics
from app.runtime_diagnostics import RuntimeDiagnostics


def records(log):
    return [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]


def test_log_rotates_with_bounded_size_and_complete_concurrent_records(tmp_path):
    log = DiagnosticLog(tmp_path, max_bytes=1024, backups=2)
    with ThreadPoolExecutor(max_workers=4) as workers:
        assert all(workers.map(lambda i: log.write("sample", count=i), range(100)))
    files = list(tmp_path.iterdir())
    assert len(files) == 3
    assert all(path.stat().st_size <= 1024 for path in files)
    for path in files:
        assert path.read_bytes().endswith(b"\n")
        for line in path.read_text().splitlines():
            assert json.loads(line)["event"] == "sample"
    assert not log.write("too_big", data="x" * 1024)
    log.close()
    assert not log.write("after_close")


def test_logging_failure_does_not_escape_into_application(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("not a directory")
    assert not DiagnosticLog(blocked).write("sample")
    assert not DiagnosticLog(tmp_path).write("sample", value=float("nan"))


def test_renderer_whitelist_limits_values_and_write_rate(tmp_path, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(runtime_diagnostics, "monotonic", lambda: now[0])
    monitor = RuntimeDiagnostics(tmp_path, SimpleNamespace())
    assert not monitor.record_renderer("body")
    assert monitor.record_renderer({"heap_used": 100, "content": "secret", "token": "secret",
        "heap_limit": float("inf"), "cached_chars": -1, "visible": True, "js_errors": 10 ** 1000})
    assert records(monitor.log)[0]["metrics"] == {"heap_used": 100}
    now[0] = 5
    assert monitor.record_renderer({"heap_used": 200})
    assert len(records(monitor.log)) == 1
    assert monitor.last_renderer == 5
    now[0] = 30
    assert monitor.record_renderer({"heap_used": 300})
    assert len(records(monitor.log)) == 2
    monitor.dispose()
    assert not monitor.record_renderer({"heap_used": 400})


def test_sampling_continues_when_page_heartbeat_stops_and_recovers(tmp_path, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(runtime_diagnostics, "monotonic", lambda: now[0])
    monitor = RuntimeDiagnostics(tmp_path, SimpleNamespace(), collector=lambda: {"process_count": 2})
    monitor.record_renderer({"heap_used": 100})
    now[0] = 91
    monitor.sample()
    now[0] = 121
    monitor.sample()
    monitor.record_renderer({"heap_used": 200})
    monitor.sample()
    data = records(monitor.log)
    assert [r["event"] for r in data].count("renderer_heartbeat_gap") == 1
    assert [r["event"] for r in data].count("renderer_heartbeat_resumed") == 1
    assert [r["renderer_age_seconds"] for r in data if r["event"] == "process_sample"] == [91, 121, 0]
    monitor.dispose()


class Handlers:
    def __init__(self):
        self.callbacks = []

    def __iadd__(self, callback):
        self.callbacks.append(callback)
        return self

    def __isub__(self, callback):
        self.callbacks.remove(callback)
        return self


def fake_core():
    return SimpleNamespace(ProcessFailed=Handlers(), NavigationStarting=Handlers(),
                           Environment=SimpleNamespace(BrowserVersionString="157.test"))


def test_native_events_rebind_once_and_sampler_survives_collection_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_diagnostics.sys, "platform", "win32")
    sampled = Event()
    calls = []

    def collect():
        calls.append(1)
        if len(calls) == 1:
            raise OSError("sensitive text must not be logged")
        sampled.set()
        return {"process_count": 1}

    core = fake_core()
    window = SimpleNamespace(native=SimpleNamespace(webview=SimpleNamespace(CoreWebView2=core)),
                             events=SimpleNamespace(shown=Handlers(), loaded=Handlers()))
    monitor = RuntimeDiagnostics(tmp_path, SimpleNamespace(), collector=collect, interval=0.02)
    try:
        monitor.start(window, lambda fn: fn())
        monitor.install()
        assert len(core.ProcessFailed.callbacks) == 1
        assert sampled.wait(2)
        core.ProcessFailed.callbacks[0](None, SimpleNamespace(ProcessFailedKind="RenderProcessExited",
            Reason="OutOfMemory", ExitCode=-536870904))
        replacement = fake_core()
        window.native.webview.CoreWebView2 = replacement
        monitor.loaded()
        assert core.ProcessFailed.callbacks == []
        assert core.NavigationStarting.callbacks == []
        assert len(replacement.ProcessFailed.callbacks) == 1
    finally:
        monitor.dispose()
        monitor.dispose()
    assert not monitor.thread.is_alive()
    assert window.events.shown.callbacks == window.events.loaded.callbacks == []
    assert replacement.ProcessFailed.callbacks == replacement.NavigationStarting.callbacks == []
    data = records(monitor.log)
    assert any(r["event"] == "monitor_sample_error" and r["error_type"] == "OSError" for r in data)
    assert any(r["event"] == "webview_process_failed" and r["reason"] == "OutOfMemory" for r in data)
    assert "sensitive text" not in monitor.log.path.read_text()
    assert data[-1]["event"] == "monitor_stopped"


def test_process_details_are_bounded_and_do_not_store_arguments(tmp_path, monkeypatch):
    def process(pid):
        return SimpleNamespace(pid=pid, oneshot=nullcontext, ppid=lambda: 1, create_time=lambda: 1,
            memory_info=lambda: SimpleNamespace(rss=pid, private=pid * 2, vms=pid * 3),
            name=lambda: "msedgewebview2.exe", num_threads=lambda: 4,
            cmdline=lambda: ["--type=renderer", "--secret=private"])
    root = process(1)
    root.children = lambda recursive: [process(i) for i in range(2, 102)]
    monkeypatch.setattr(diagnostic_processes.psutil, "Process", lambda pid: root)
    metrics = diagnostic_processes.collect_process_metrics()
    assert metrics["process_count"] == 101
    assert len(metrics["processes"]) == 64
    assert metrics["rss_total"] == sum(range(1, 102))
    assert metrics["processes"][0]["pid"] == 101
    assert metrics["processes"][0]["kind"] == "webview_renderer"
    assert "secret" not in json.dumps(metrics)


def test_bridge_preserves_shell_origin_check(monkeypatch, tmp_path):
    from app.api import ShellApi
    from app import api as api_module
    monkeypatch.setattr(api_module, "_project_root", lambda: tmp_path)
    api = ShellApi(SimpleNamespace(allow_remote_shell_api=False), SimpleNamespace())
    api._window = SimpleNamespace(url="https://untrusted.invalid")
    api._diagnostics.record_renderer = Mock()
    try:
        with pytest.raises(PermissionError):
            api.record_renderer_diagnostics({"heap_used": 100})
        api._diagnostics.record_renderer.assert_not_called()
    finally:
        api.dispose()
