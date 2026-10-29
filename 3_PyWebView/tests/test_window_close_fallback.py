from types import SimpleNamespace
from unittest.mock import Mock
import threading

import pytest

from app import window_close as module
from app.window_close import WindowCloseCoordinator


@pytest.fixture
def harness(monkeypatch):
    clock = [0.0]
    timers, workers, controllers = [], [], []

    class Timer:
        def __init__(self, delay, action, args=()):
            self.at, self.action, self.args = clock[0] + delay, action, args
            self.cancelled = False
        def start(self):
            timers.append(self)
        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module.threading, "Timer", Timer)
    monkeypatch.setattr(module, "mark", lambda *args, **kwargs: None)
    monkeypatch.setattr(WindowCloseCoordinator, "_spawn", staticmethod(workers.append))

    def advance(seconds):
        clock[0] += seconds
        due = [timer for timer in timers if not timer.cancelled and timer.at <= clock[0]]
        for timer in due:
            timer.cancelled = True
            timer.action(*timer.args)

    def make(**callbacks):
        callbacks = {name: callbacks.get(name, Mock()) for name in ("dispatch", "prepare", "destroy", "prompt")}
        coordinator = WindowCloseCoordinator(**callbacks)
        controllers.append(coordinator)
        return SimpleNamespace(controller=coordinator, **callbacks)

    yield SimpleNamespace(make=make, advance=advance, workers=workers, timers=timers)
    for coordinator in controllers:
        coordinator.dispose()


def test_failed_dispatch_merges_clicks_and_uses_backend_settlement(harness):
    events = []
    h = harness.make(dispatch=Mock(side_effect=RuntimeError("renderer dead")),
                     prepare=lambda: events.append("prepare"), destroy=lambda: events.append("destroy"),
                     prompt=Mock(return_value="exit"))
    request = h.controller.request()
    assert [h.controller.request(), h.controller.request(), h.controller.request("exit")] == [request] * 3
    assert len(harness.workers) == 1
    harness.workers.pop()()
    harness.advance(0.02)
    assert events == ["prepare", "destroy"]
    h.prompt.assert_called_once_with("frontend", "")
    assert not h.controller.complete(request)


def test_no_listener_and_waiting_for_user_are_distinguished(harness):
    h = harness.make(prompt=Mock(return_value="wait"))
    request = h.controller.request()
    harness.workers.pop()()
    harness.advance(5)
    h.prompt.assert_called_once()
    for i in range(100):
        assert h.controller.report(request, "saving" if i % 2 else "waiting")
        harness.advance(1)
    assert h.prompt.call_count == 1  # User deciding / slow save, renderer still responsive.
    assert h.controller.report(request, "cancelled")
    harness.advance(30)
    assert h.prompt.call_count == 1
    replacement = h.controller.request()
    assert replacement != request
    assert not h.controller.report(request, "waiting")
    assert not h.controller.complete(request)


def test_blocked_js_call_does_not_block_watchdog_or_accumulate_threads(harness):
    started, release = threading.Event(), threading.Event()
    def dispatch(*_):
        started.set()
        release.wait(5)
    h = harness.make(dispatch=Mock(side_effect=dispatch), prompt=Mock(return_value="exit"))
    request = h.controller.request()
    worker = threading.Thread(target=harness.workers.pop())
    worker.start()
    try:
        assert started.wait(1)
        assert h.controller.report(request, "cancelled")
        for _ in range(10):
            h.controller.request("exit")
        assert harness.workers == []
        harness.advance(5)
        h.prepare.assert_called_once()
        h.destroy.assert_called_once()
        assert worker.is_alive()
    finally:
        release.set()
        worker.join(2)


def test_cancel_before_dispatch_delivers_only_the_new_request(harness):
    h = harness.make()
    old = h.controller.request()
    h.controller.report(old, "cancelled")
    new = h.controller.request("exit")
    harness.workers.pop()()
    h.dispatch.assert_not_called()
    assert len(harness.workers) == 1
    harness.workers.pop()()
    h.dispatch.assert_called_once_with(new, "exit")


def test_wait_can_reach_recovered_frontend_without_new_request(harness):
    h = harness.make(prompt=Mock(return_value="wait"))
    request = h.controller.request("exit")
    harness.workers.pop()()
    harness.advance(5)
    harness.workers.pop()()
    assert h.dispatch.call_args_list[0] == h.dispatch.call_args_list[1]
    assert h.controller.report(request, "waiting")
    assert h.controller.complete(request)
    h.prepare.assert_called_once()
    h.destroy.assert_called_once()


@pytest.mark.parametrize("choice", ["wait", "force"])
def test_pending_backend_has_separate_watchdog_and_never_restarts_settlement(harness, choice):
    started, release = threading.Event(), threading.Event()
    def prepare():
        started.set()
        release.wait(5)
    h = harness.make(prepare=Mock(side_effect=prepare), prompt=Mock(return_value=choice))
    request = h.controller.request()
    worker = threading.Thread(target=lambda: h.controller.complete(request))
    worker.start()
    try:
        assert started.wait(1)
        harness.advance(30)
        h.prompt.assert_called_once_with("settling", "")
        assert not h.controller.report(request, "cancelled")
        assert not h.controller.complete(request)
        assert h.destroy.call_count == (1 if choice == "force" else 0)
        h.prepare.assert_called_once()
    finally:
        release.set()
        worker.join(2)
    h.destroy.assert_called_once()


def test_backend_finishing_during_native_dialog_does_not_close_under_dialog(harness):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    def prepare():
        started.set()
        release.wait(5)
    h = harness.make(prepare=prepare)
    def prompt(*_):
        release.set()
        assert finished.wait(1)
        h.destroy.assert_not_called()
        return "wait"
    h.prompt.side_effect = prompt
    request = h.controller.request()
    worker = threading.Thread(target=lambda: (h.controller.complete(request), finished.set()))
    worker.start()
    try:
        assert started.wait(1)
        harness.advance(30)
        h.destroy.assert_called_once()
    finally:
        release.set()
        worker.join(2)


@pytest.mark.parametrize("choice", ["retry", "force", "cancel"])
def test_failed_backend_has_native_recovery_choices(harness, choice):
    h = harness.make(prepare=Mock(side_effect=[RuntimeError("save failed"), None]),
                     prompt=Mock(return_value=choice))
    request = h.controller.request()
    with pytest.raises(RuntimeError, match="save failed"):
        h.controller.complete(request)
    h.destroy.assert_not_called()
    harness.advance(0.02)
    h.prompt.assert_called_once_with("failed", "save failed")
    assert h.prepare.call_count == (2 if choice == "retry" else 1)
    assert h.destroy.call_count == (0 if choice == "cancel" else 1)
    assert not h.controller.complete(request)


def test_late_cancel_invalidates_native_prompt_choice(harness):
    h = harness.make()
    request = h.controller.request()
    def prompt(*_):
        assert h.controller.report(request, "cancelled")
        assert h.controller.request() == request  # No second prompt while this one is open.
        return "exit"
    h.prompt.side_effect = prompt
    harness.advance(5)
    h.prepare.assert_not_called()
    h.destroy.assert_not_called()
    assert h.controller.request() != request


def test_shell_routes_window_tray_and_bridge_to_one_request(harness, monkeypatch):
    from app.api import ShellApi
    from app import api as api_module
    monkeypatch.setattr(api_module.sys, "platform", "win32")
    manager = SimpleNamespace(prepare_exit=Mock(), cancel_exit_preparation=Mock())
    api = ShellApi(SimpleNamespace(allow_remote_shell_api=False), manager)
    api._window = SimpleNamespace(url="http://127.0.0.1:18100", evaluate_js=Mock(side_effect=RuntimeError("dead")), destroy=Mock())
    monkeypatch.setattr(api_module, "show_native_exit_prompt", Mock(return_value="exit"))
    try:
        assert [api._handle_window_closing() for _ in range(3)] == [False] * 3
        api._request_exit_from_windows_tray()
        assert len(harness.workers) == 1
        harness.workers.pop()()
        harness.advance(0.02)
        manager.prepare_exit.assert_called_once()
        api._window.destroy.assert_called_once()
    finally:
        api.dispose()


def test_tray_exit_uses_exit_intent_and_dispose_invalidates_timers(harness, monkeypatch):
    from app.api import ShellApi
    api = ShellApi(SimpleNamespace(allow_remote_shell_api=False), SimpleNamespace())
    api._window = SimpleNamespace(evaluate_js=Mock())
    monkeypatch.setattr(api, "_show_window_from_windows_tray", Mock())
    api._request_exit_from_windows_tray()
    harness.workers.pop()()
    assert '"intent": "exit"' in api._window.evaluate_js.call_args.args[0]
    api._show_window_from_windows_tray.assert_called_once()
    api.dispose()
    harness.advance(60)
    assert api._close_coordinator.request() is None


@pytest.mark.parametrize("reason,result,choice,default", [
    ("frontend", 6, "exit", 0x100), ("frontend", 7, "wait", 0x100),
    ("settling", 6, "force", 0x100), ("settling", 7, "wait", 0x100),
    ("failed", 6, "retry", 0x200), ("failed", 7, "force", 0x200),
    ("failed", 2, "cancel", 0x200),
])
def test_native_dialog_uses_no_javascript_and_defaults_to_wait_or_cancel(monkeypatch, reason, result, choice, default):
    import ctypes
    box = Mock(return_value=result)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=SimpleNamespace(MessageBoxW=box)))
    assert module.show_native_exit_prompt(123, reason, "failure") == choice
    assert box.call_args.args[0] == 123
    assert box.call_args.args[3] & 0xF00 == default
