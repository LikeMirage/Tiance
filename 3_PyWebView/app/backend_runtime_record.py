from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

import psutil

from app.startup_timing import mark


RECORD_SCHEMA_VERSION = 1
RECORD_RELATIVE_PATH = Path("Data") / "cache" / "desktop-shell" / "backend-process.json"
PROCESS_TERMINATE_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class ProcessIdentity:
    executable_path: str
    creation_time: int
    command_line: tuple[str, ...]


@dataclass(frozen=True)
class ManagedBackendRecord:
    schema_version: int
    project_root: str
    pid: int
    executable_path: str
    creation_time: int
    instance_id: str
    api_url: str


def cleanup_orphaned_managed_backend(project_root: Path) -> None:
    record_path = _record_path(project_root)
    record = _read_record(record_path)
    if record is None:
        return

    if _normalize_path(record.project_root) != _normalize_path(str(project_root.resolve())):
        _remove_record(record_path)
        return

    identity = _query_process_identity(record.pid)
    if identity is None:
        _remove_record(record_path)
        return

    if not _identity_matches_record(identity, record):
        _remove_record(record_path)
        return

    if not _is_expected_backend_process(identity, project_root):
        _remove_record(record_path)
        return

    active_instance_id = _probe_instance_id(record.api_url)
    if active_instance_id not in {None, record.instance_id}:
        _remove_record(record_path)
        return

    mark(
        "backend orphan cleanup: verified managed backend",
        pid=record.pid,
        api_url=record.api_url,
    )
    if _terminate_process_tree(record.pid):
        _remove_record(record_path)
        mark("backend orphan cleanup: completed", pid=record.pid)
        return

    mark("backend orphan cleanup: termination failed", pid=record.pid)


def record_managed_backend(
    project_root: Path,
    *,
    pid: int,
    instance_id: str,
    api_url: str,
) -> None:
    identity = _query_process_identity(pid)
    if identity is None:
        mark("backend runtime record: process identity unavailable", pid=pid)
        return

    record = ManagedBackendRecord(
        schema_version=RECORD_SCHEMA_VERSION,
        project_root=str(project_root.resolve()),
        pid=pid,
        executable_path=identity.executable_path,
        creation_time=identity.creation_time,
        instance_id=instance_id,
        api_url=api_url,
    )
    _write_record(_record_path(project_root), record)


def clear_managed_backend_record(project_root: Path, *, pid: int) -> None:
    record_path = _record_path(project_root)
    record = _read_record(record_path)
    if record is None or record.pid != pid:
        return
    _remove_record(record_path)


def _record_path(project_root: Path) -> Path:
    return project_root / RECORD_RELATIVE_PATH


def _read_record(path: Path) -> ManagedBackendRecord | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        record = ManagedBackendRecord(
            schema_version=int(payload["schema_version"]),
            project_root=str(payload["project_root"]),
            pid=int(payload["pid"]),
            executable_path=str(payload["executable_path"]),
            creation_time=int(payload["creation_time"]),
            instance_id=str(payload["instance_id"]),
            api_url=str(payload["api_url"]),
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        _remove_record(path)
        return None

    if (
        record.schema_version != RECORD_SCHEMA_VERSION
        or record.pid <= 0
        or not record.instance_id
        or not _is_loopback_http_url(record.api_url)
    ):
        _remove_record(path)
        return None
    return record


def _write_record(path: Path, record: ManagedBackendRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temporary_path.write_text(
            json.dumps(asdict(record), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary_path, path)
    except OSError as exc:
        mark("backend runtime record: write failed", error=str(exc))
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def _remove_record(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        mark("backend runtime record: remove failed", error=str(exc))


def _identity_matches_record(
    identity: ProcessIdentity,
    record: ManagedBackendRecord,
) -> bool:
    return (
        identity.creation_time == record.creation_time
        and _normalize_path(identity.executable_path)
        == _normalize_path(record.executable_path)
    )


def _normalize_path(value: str) -> str:
    return os.path.normcase(os.path.abspath(value))


def _is_loopback_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        and port is not None
        and not parsed.username
        and not parsed.password
    )


def _probe_instance_id(api_url: str) -> str | None:
    if not _is_loopback_http_url(api_url):
        return None
    request = Request(f"{api_url.rstrip('/')}/api/health", method="GET")
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(request, timeout=1) as response:
            if getattr(response, "status", 200) != 200:
                return None
            payload = json.loads(response.read(64 * 1024).decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return None

    instance_id = payload.get("instance_id") if isinstance(payload, dict) else None
    return instance_id if isinstance(instance_id, str) and instance_id else None


def _query_process_identity(pid: int) -> ProcessIdentity | None:
    try:
        process = psutil.Process(pid)
        with process.oneshot():
            executable_path = process.exe()
            creation_time = round(process.create_time() * 1_000_000)
            command_line = tuple(process.cmdline())
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, OSError):
        return None
    return ProcessIdentity(
        executable_path=executable_path,
        creation_time=creation_time,
        command_line=command_line,
    )


def _is_expected_backend_process(
    identity: ProcessIdentity,
    project_root: Path,
) -> bool:
    expected_entry = _normalize_path(str(project_root / "1_PythonServer" / "run.py"))
    return any(_normalize_path(argument) == expected_entry for argument in identity.command_line)


def _terminate_process_tree(pid: int) -> bool:
    try:
        process = psutil.Process(pid)
        processes = [*process.children(recursive=True), process]
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
        return not psutil.pid_exists(pid)

    for item in processes:
        try:
            item.terminate()
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            pass

    _, alive = psutil.wait_procs(processes, timeout=PROCESS_TERMINATE_TIMEOUT_SECONDS)
    for item in alive:
        try:
            item.kill()
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            pass
    if alive:
        _, alive = psutil.wait_procs(alive, timeout=PROCESS_TERMINATE_TIMEOUT_SECONDS)
    if not alive:
        return True

    return _query_process_identity(pid) is None
