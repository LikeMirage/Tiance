import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.gateway_process import GatewayProcessManager
from app.gateway_process_log import (
    GATEWAY_LOG_BACKUPS,
    GatewayProcessLog,
    RollingGatewayLog,
    configure_gateway_logging,
)
from app.process_security import ProcessSecurity


def retained_bytes(path: Path) -> bytes:
    files = [path.with_name(f"{path.name}.{i}") for i in range(GATEWAY_LOG_BACKUPS, 0, -1)] + [path]
    return b"".join(p.read_bytes() for p in files if p.exists())


def assert_bounded(path: Path, maximum: int) -> None:
    files = list(path.parent.glob(f"{path.name}*"))
    assert len(files) <= GATEWAY_LOG_BACKUPS + 1
    assert all(p.stat().st_size <= maximum for p in files)


def test_rotation_is_bounded_during_writes_and_keeps_latest_bytes(tmp_path):
    path = tmp_path / "gateway.log"
    writer = RollingGatewayLog(path, max_bytes=100)
    complete = b""
    try:
        for index in range(50):
            chunk = (f"request {index}: ".encode() + b"x" * 31 + b"\n")
            writer.write(chunk)
            complete += chunk
            assert_bounded(path, 100)
            remaining = retained_bytes(path)
            assert remaining == complete[-len(remaining):]
    finally:
        writer.close()


def test_one_large_write_cannot_exceed_file_limit(tmp_path):
    path = tmp_path / "gateway.log"
    writer = RollingGatewayLog(path, max_bytes=128)
    payload = bytes(range(256)) * 100
    writer.write(payload)
    writer.close()
    assert_bounded(path, 128)
    assert retained_bytes(path) == payload[-384:]


def test_old_oversized_files_are_trimmed_before_opening(tmp_path):
    path = tmp_path / "gateway.log"
    for index in range(3):
        target = path if not index else path.with_name(f"{path.name}.{index}")
        target.write_bytes(b"old" * 1000 + f"tail {index}".encode())
    writer = RollingGatewayLog(path, max_bytes=100)
    assert_bounded(path, 100)
    assert path.read_bytes().endswith(b"tail 0")
    writer.write(b"new run\n")
    writer.close()
    assert_bounded(path, 100)
    assert retained_bytes(path).endswith(b"tail 0new run\n")


def test_restart_appends_small_log_without_discarding_history(tmp_path):
    path = tmp_path / "gateway.log"
    for payload in (b"first\n", b"second\n"):
        writer = RollingGatewayLog(path, max_bytes=100)
        writer.write(payload)
        writer.close()
    assert path.read_bytes() == b"first\nsecond\n"


def start_child(script: str):
    return subprocess.Popen(
        [sys.executable, "-u", "-c", script], stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, bufsize=0,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def test_pipe_capture_drains_large_output_and_keeps_final_stderr(tmp_path):
    path = tmp_path / "gateway.log"
    log = GatewayProcessLog(path, max_bytes=1024)
    process = start_child("import os; os.write(1, b'x' * 262144); os.write(2, b'final error\\n')")
    try:
        log.start(process.stdout)
        assert process.wait(timeout=5) == 0
        assert log.finish()
        assert_bounded(path, 1024)
        assert retained_bytes(path).endswith(b"final error\n")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        log.finish()


def test_write_failure_still_drains_pipe_without_repeated_errors(tmp_path, monkeypatch, caplog):
    log = GatewayProcessLog(tmp_path / "gateway.log", max_bytes=1024)

    def fail(_):
        raise OSError("disk full")

    monkeypatch.setattr(log._writer, "write", fail)
    process = start_child("import os; os.write(1, b'x' * 1048576)")
    try:
        log.start(process.stdout)
        assert process.wait(timeout=5) == 0
        assert log.finish()
        assert sum("draining output without saving" in r.message for r in caplog.records) == 1
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        log.finish()


def test_log_filter_defaults_and_explicit_diagnostic_override():
    env = {"Logging__LogLevel__Yarp.ReverseProxy": "Debug"}
    configure_gateway_logging(env)
    assert env["Logging__LogLevel__Microsoft.AspNetCore"] == "Warning"
    assert env["Logging__LogLevel__Yarp.ReverseProxy"] == "Debug"


def test_gateway_startup_failure_reaps_process_and_closes_log(tmp_path, monkeypatch):
    import app.gateway_process as module

    executable = tmp_path / "gateway.exe"
    executable.touch()
    manager = GatewayProcessManager(SimpleNamespace(
        api_host="127.0.0.1", api_port=18000, gateway_listen_host="127.0.0.1",
        gateway_executable_path=str(executable), backend_url="http://127.0.0.1:18200",
        external_access_enabled=False, dev_url="",
    ), ProcessSecurity())
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module, "is_port_open", lambda *_: False)
    created = []
    popen = subprocess.Popen

    def launch(_args, **kwargs):
        assert kwargs['env']['Logging__LogLevel__Microsoft.AspNetCore'] == 'Warning'
        child = popen([sys.executable, '-u', '-c', 'import sys,time; sys.stdin.readline(); time.sleep(30)'], **kwargs)
        created.append(child)
        return child

    monkeypatch.setattr(module.subprocess, 'Popen', launch)

    def fail_ready():
        raise RuntimeError('simulated readiness failure')

    monkeypatch.setattr(manager, '_wait_until_ready', fail_ready)
    with pytest.raises(RuntimeError, match='simulated readiness failure'):
        manager.ensure_running()
    assert created[0].poll() is not None
    assert created[0].stdout.closed
    manager.stop()
    # A new writer can replace the file: neither failed startup nor stop leaks it.
    writer = RollingGatewayLog(tmp_path / 'Data/logs/gateway.log', max_bytes=1)
    writer.write(b'two bytes')
    writer.close()


def test_gateway_spawn_failure_closes_log(tmp_path, monkeypatch):
    import app.gateway_process as module

    executable = tmp_path / "gateway.exe"
    executable.touch()
    manager = GatewayProcessManager(SimpleNamespace(
        api_host="127.0.0.1", api_port=18000, gateway_listen_host="127.0.0.1",
        gateway_executable_path=str(executable), backend_url="http://127.0.0.1:18200",
        external_access_enabled=False, dev_url="",
    ), ProcessSecurity())
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module, "is_port_open", lambda *_: False)

    def fail_spawn(*args, **kwargs):
        raise OSError('simulated spawn failure')

    monkeypatch.setattr(module.subprocess, 'Popen', fail_spawn)
    with pytest.raises(OSError, match='simulated spawn failure'):
        manager.ensure_running()
    assert manager._log.finish()
    manager.stop()
