from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.api import ShellApi
from app.backend_process import BackendProcessManager
from app.backend_watchdog import ShellLease


def test_close_waits_for_pending_commits_before_destroying_window(monkeypatch):
    manager = BackendProcessManager(SimpleNamespace())
    manager._process = SimpleNamespace(poll=lambda: None)
    manager._lease = ShellLease("instance", "token", "http://127.0.0.1:9999/heartbeat")
    events = []
    states = iter([{"ready": False, "pending_tasks": 1}, {"ready": True, "pending_tasks": 0}])

    def request(lease, *, method):
        assert lease is manager._lease
        assert method == "POST"
        events.append("prepare")
        return next(states)

    monkeypatch.setattr(manager, "_request_exit_preparation", request)
    monkeypatch.setattr("app.backend_process.time.sleep", lambda _: events.append("wait"))
    api = ShellApi(SimpleNamespace(allow_remote_shell_api=False), manager)
    api._window = SimpleNamespace(
        url="http://127.0.0.1:18100", destroy=lambda: events.append("destroy"),
    )
    api.close_window()
    assert events == ["prepare", "wait", "prepare", "destroy"]
    assert api._allow_window_close


def test_preparation_failure_keeps_window_and_reopens_task_admission(monkeypatch):
    manager = BackendProcessManager(SimpleNamespace())
    manager._process = SimpleNamespace(poll=lambda: None)
    manager._lease = ShellLease("instance", "token", "http://127.0.0.1:9999/heartbeat")
    methods = []

    def request(_lease, *, method):
        methods.append(method)
        if method == "POST":
            raise TimeoutError("local server stalled")
        return {}

    monkeypatch.setattr(manager, "_request_exit_preparation", request)
    api = ShellApi(SimpleNamespace(allow_remote_shell_api=False), manager)
    api._window = SimpleNamespace(url="http://127.0.0.1:18100", destroy=Mock())
    with pytest.raises(RuntimeError, match="窗口已保留"):
        api.close_window()
    api._window.destroy.assert_not_called()
    assert not api._allow_window_close
    assert methods == ["POST", "DELETE"]


def test_unmanaged_backend_is_not_shut_down_by_closing_shell(monkeypatch):
    manager = BackendProcessManager(SimpleNamespace())
    request = Mock()
    monkeypatch.setattr(manager, "_request_exit_preparation", request)
    manager.prepare_exit()
    request.assert_not_called()


def test_native_destroy_failure_resumes_backend_work():
    manager = SimpleNamespace(prepare_exit=Mock(), cancel_exit_preparation=Mock())
    api = ShellApi(SimpleNamespace(allow_remote_shell_api=False), manager)
    api._window = SimpleNamespace(
        url="http://127.0.0.1:18100", destroy=Mock(side_effect=RuntimeError("window still open")),
    )
    with pytest.raises(RuntimeError, match="window still open"):
        api.close_window()
    manager.prepare_exit.assert_called_once()
    manager.cancel_exit_preparation.assert_called_once()
    assert not api._allow_window_close
