from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from app.services import workspace_storage as module


def put(root, name, size):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def service(*roots):
    projects = Mock()
    projects.list_projects.return_value = [SimpleNamespace(root_path=str(root)) for root in roots]
    return module.WorkspaceStorageService(projects), projects


def test_counts_databases_sidecars_and_attachments_only_under_registered_roots(tmp_path, monkeypatch):
    project = tmp_path / "project"
    put(project, ".Tiance/tiance.db", 100)
    put(project, ".Tiance/tiance.db-wal", 20)
    put(project, ".Tiance/tiance.db-shm", 10)
    put(project, ".Tiance/tiance.db-journal", 5)
    put(project, ".Tiance/conversations/attachments/image.png", 60)
    put(project, ".Tiance/conversations/attachments/tiance.db", 7)
    put(project, "report.xlsx", 1000)
    put(tmp_path / "unregistered", ".Tiance/tiance.db", 2000)
    empty = tmp_path / "empty"
    empty.mkdir()
    instance, _ = service(project, project / ".", empty)
    # Accounting cannot read file contents, open databases or initialize workspaces.
    monkeypatch.setattr(Path, "read_bytes", lambda *_: (_ for _ in ()).throw(AssertionError("content read")))
    monkeypatch.setattr("sqlite3.connect", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("DB opened")))
    result = instance.get_storage()
    assert result["total_bytes"] == 202
    assert result["database_bytes"] == 135
    assert result["other_bytes"] == 67
    assert result["complete"]
    assert not (empty / ".Tiance").exists()


def test_cache_merges_concurrent_requests_and_refreshes_catalog_after_five_minutes(tmp_path, monkeypatch):
    put(tmp_path, ".Tiance/tiance.db", 100)
    instance, projects = service(tmp_path)
    clock = [0]
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: instance.get_storage(), range(20)))
    assert all(result is results[0] for result in results)
    projects.list_projects.assert_called_once()
    put(tmp_path, ".Tiance/tiance.db", 200)
    clock[0] = 299
    assert instance.get_storage()["total_bytes"] == 100
    clock[0] = 300
    assert instance.get_storage()["total_bytes"] == 200
    assert projects.list_projects.call_count == 2


def test_entry_budget_returns_explicit_partial_result(tmp_path, monkeypatch):
    put(tmp_path, ".Tiance/tiance.db", 100)
    put(tmp_path, ".Tiance/image.png", 100)
    monkeypatch.setattr(module, "MAX_ENTRIES", 1)
    result = service(tmp_path)[0].get_storage()
    assert not result["complete"]
    assert result["total_bytes"] == 100


def test_time_budget_stops_scan(tmp_path, monkeypatch):
    put(tmp_path, ".Tiance/tiance.db", 100)
    monkeypatch.setattr(module, "SCAN_SECONDS", 0)
    result = service(tmp_path)[0].get_storage()
    assert not result["complete"]
    assert result["total_bytes"] == 0


def test_unreadable_and_reparse_directories_do_not_hide_valid_totals(tmp_path, monkeypatch):
    good, blocked, linked = [tmp_path / name for name in ("good", "blocked", "linked")]
    for root in (good, blocked, linked):
        put(root, ".Tiance/tiance.db", 100)
    original_stat = module.os.stat

    def checked_stat(path, *args, **kwargs):
        if Path(path) == blocked / ".Tiance":
            raise PermissionError()
        result = original_stat(path, *args, **kwargs)
        if Path(path) == linked / ".Tiance":
            return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
        return result

    monkeypatch.setattr(module.os, "stat", checked_stat)
    result = service(good, blocked, linked)[0].get_storage()
    assert not result["complete"]
    assert result["total_bytes"] == 100
