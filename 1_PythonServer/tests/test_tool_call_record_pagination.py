from dataclasses import asdict, replace
import json
from pathlib import Path
import sqlite3
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.routes.tools import tool_call_records as routes
from app.domain.tools.call_record_page import ToolCallRecordSnapshotExpired
from app.repositories.tools import ToolCallRecordRepository
from app.repositories.tools import tool_call_record_index as index_module
from app.schemas.tools.tool_call_records import ToolCallRecordListItemResponse
from tests.test_tool_call_records import _FakeToolProjects, _draft, _service


def write_history(repository, root, count=1000):
    path = repository.records_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for i in range(count):
            payload = asdict(_draft(call_id=f"call-{i}"))
            payload.update(record_id=f"record-{i}", created_at=f"2026-10-29T00:{i // 60:02}:{i % 60:02}+00:00",
                           arguments_text='{"text":"完整参数"}', result_text="长返回内容" * 1600)
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return path


def test_thousand_large_records_list_is_small_and_warm_pages_only_read_index(tmp_path, monkeypatch):
    repository = ToolCallRecordRepository()
    path = write_history(repository, tmp_path)
    original = path.read_bytes()
    loads = Mock(wraps=index_module.json.loads)
    monkeypatch.setattr(index_module.json, "loads", loads)
    page = repository.list_project_page(tmp_path)
    assert page.count == 1000
    assert len(page.items) == 50
    assert page.items[0].record_id == "record-999"
    assert loads.call_count == 1000
    encoded = json.dumps([ToolCallRecordListItemResponse.from_domain(row).model_dump() for row in page.items])
    assert len(encoded.encode()) < 30_000
    assert all(word not in encoded for word in ("arguments_text", "result_text", '"error"'))
    # Reopening the repository also reuses the disk index, not a full-history RAM cache.
    repository = ToolCallRecordRepository()
    loads.reset_mock()
    next_page = repository.list_project_page(tmp_path, offset=50, snapshot=page.snapshot)
    assert loads.call_count == 0
    assert next_page.items[0].record_id == "record-949"
    detail = repository.get_project_record(tmp_path, page.items[0].record_id)
    assert loads.call_count == 1
    assert detail.arguments_text == '{"text":"完整参数"}'
    assert detail.result_text == "长返回内容" * 1600
    assert path.read_bytes() == original
    assert path.with_name("records-index.sqlite3").stat().st_size < 1_000_000


def test_snapshot_survives_new_calls_without_duplicate_or_missing_old_rows(tmp_path, monkeypatch):
    repository = ToolCallRecordRepository()
    write_history(repository, tmp_path, 121)
    expected = [r.record_id for r in repository.list_project_records(tmp_path)]
    first = repository.list_project_page(tmp_path)
    newest = repository.append(tmp_path, _draft(call_id="new-call"))
    loads = Mock(wraps=index_module.json.loads)
    monkeypatch.setattr(index_module.json, "loads", loads)
    second = repository.list_project_page(tmp_path, offset=50, snapshot=first.snapshot)
    assert loads.call_count == 1  # Only the append is indexed.
    third = repository.list_project_page(tmp_path, offset=100, snapshot=first.snapshot)
    assert first.count == second.count == third.count == 121
    assert [r.record_id for page in (first, second, third) for r in page.items] == expected
    refreshed = repository.list_project_page(tmp_path)
    assert refreshed.count == 122
    assert refreshed.items[0].record_id == newest.record_id


def test_created_at_order_and_equal_timestamp_order_match_original_reader(tmp_path):
    repository = ToolCallRecordRepository()
    path = write_history(repository, tmp_path, 4)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["created_at"] = rows[3]["created_at"]
    rows[2]["created_at"] = rows[3]["created_at"]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    assert [r.record_id for r in repository.list_project_page(tmp_path).items] == [
        r.record_id for r in repository.list_project_records(tmp_path)
    ]


@pytest.mark.parametrize("change", ["replace", "truncate", "rewrite"])
def test_replaced_or_truncated_file_invalidates_snapshot(tmp_path, change):
    repository = ToolCallRecordRepository()
    path = write_history(repository, tmp_path, 3)
    old = repository.list_project_page(tmp_path)
    if change == "replace":
        replacement = path.with_suffix(".new")
        replacement.write_bytes(path.read_bytes())
        replacement.replace(path)
    elif change == "truncate":
        path.write_bytes(b"")
    else:
        path.write_bytes(path.read_bytes().replace(b"record-0", b"record-x"))
    with pytest.raises(ToolCallRecordSnapshotExpired):
        repository.list_project_page(tmp_path, snapshot=old.snapshot)
    fresh = repository.list_project_page(tmp_path)
    assert fresh.count == (0 if change == "truncate" else 3)
    if change == "rewrite":
        assert repository.get_project_record(tmp_path, "record-0") is None
        assert repository.get_project_record(tmp_path, "record-x") is not None


def test_empty_missing_or_deleted_history_does_not_create_tool_directories(tmp_path):
    repository = ToolCallRecordRepository()
    root = tmp_path / "absent"
    assert repository.list_project_page(root).count == 0
    assert repository.get_project_record(root, "missing") is None
    assert not root.exists()
    path = write_history(repository, tmp_path, 1)
    old = repository.list_project_page(tmp_path)
    path.unlink()
    with pytest.raises(ToolCallRecordSnapshotExpired):
        repository.list_project_page(tmp_path, snapshot=old.snapshot)


def test_detail_is_scoped_to_requested_tool(tmp_path):
    repository = ToolCallRecordRepository()
    first = repository.append(tmp_path / "one", _draft())
    repository.append(tmp_path / "two", _draft(tool_project_id="tool-2"))
    assert repository.get_project_record(tmp_path / "two", first.record_id) is None
    assert repository.get_project_record(tmp_path / "one", first.record_id) == first


def test_partial_tail_repair_and_invalid_append_never_commit_partial_index(tmp_path):
    repository = ToolCallRecordRepository()
    path = write_history(repository, tmp_path, 2)
    first = repository.list_project_page(tmp_path)
    with path.open("ab") as stream:
        stream.write(b'{"torn":')
    assert repository.list_project_page(tmp_path).count == 2
    assert list(path.parent.glob("*.corrupt-tail"))
    valid = path.read_bytes()
    with path.open("ab") as stream:
        stream.write(valid.splitlines(keepends=True)[0].replace(b"record-0", b"record-z"))
        stream.write(b'{"invalid":true}\n')
    with pytest.raises(ValueError, match="第 4 行"):
        repository.list_project_page(tmp_path)
    with sqlite3.connect(path.with_name("records-index.sqlite3")) as connection:
        assert connection.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 2
    path.write_bytes(valid)
    assert repository.list_project_page(tmp_path).count == first.count


def test_names_are_resolved_once_per_distinct_source_per_page_and_stay_current(tmp_path):
    repository = ToolCallRecordRepository()
    fixtures = _FakeToolProjects(tmp_path)
    write_history(repository, fixtures.projects["tool-1"].root_path, 100)
    service = _service(repository, fixtures)
    project_lookup = Mock(wraps=service._project_service.get_project)
    session_lookup = Mock(wraps=service._conversation_service.get_session)
    service._project_service.get_project = project_lookup
    service._conversation_service.get_session = session_lookup
    first = service.list_project_page("category-1", "tool-1")
    assert project_lookup.call_count == session_lookup.call_count == 1
    assert {r.source_project_name for r in first.items} == {"当前项目名"}
    project_lookup.return_value = replace(project_lookup("source-project"), name="新名字")
    project_lookup.reset_mock()
    second = service.list_project_page("category-1", "tool-1", offset=50, snapshot=first.snapshot)
    assert {r.source_project_name for r in second.items} == {"新名字"}
    assert project_lookup.call_count == 1


def test_missing_source_names_are_also_cached(tmp_path):
    repository = ToolCallRecordRepository()
    fixtures = _FakeToolProjects(tmp_path)
    write_history(repository, fixtures.projects["tool-1"].root_path, 4)
    service = _service(repository, fixtures)
    service._project_service.get_project = Mock(return_value=None)
    service._conversation_service.get_session = Mock(return_value=None)
    page = service.list_project_page("category-1", "tool-1")
    assert service._project_service.get_project.call_count == 1
    assert service._conversation_service.get_session.call_count == 1
    assert all(r.source_project_name == r.session_title == "" for r in page.items)


@pytest.fixture
def client(tmp_path, monkeypatch):
    repository = ToolCallRecordRepository()
    fixtures = _FakeToolProjects(tmp_path)
    write_history(repository, fixtures.projects["tool-1"].root_path, 115)
    service = _service(repository, fixtures)
    monkeypatch.setattr(routes, "get_tool_call_record_service", lambda: service)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    with TestClient(app) as client:
        yield client


URL = "/api/tools/categories/category-1/projects/tool-1/call-records"


def test_api_pagination_and_lazy_full_detail(client):
    response = client.get(URL)
    assert response.status_code == 200
    first = response.json()
    assert first["count"] == 115 and len(first["items"]) == 50
    assert len(response.content) < 30_000
    assert "result_text" not in first["items"][0]
    last = client.get(URL, params={"offset": 100, "snapshot": first["snapshot"]}).json()
    assert len(last["items"]) == 15
    detail = client.get(URL + "/" + first["items"][0]["record_id"])
    assert detail.status_code == 200
    assert detail.json()["result_text"] == "长返回内容" * 1600
    assert client.get(URL + "/missing").status_code == 404
    assert client.get(URL, params={"snapshot": "bad"}).status_code == 400
    assert client.get(URL, params={"snapshot": "obsolete:1"}).status_code == 409


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"limit": -1}, {"offset": -1}, {"snapshot": "x" * 101}])
def test_api_rejects_unbounded_or_invalid_pagination(client, params):
    assert client.get(URL, params=params).status_code == 422
