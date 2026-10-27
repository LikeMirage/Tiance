import json
from unittest.mock import Mock

import pytest

from app.api.routes import global_memory as route
from app.repositories.project.conversation_memory_repository import ProjectConversationMemoryRepository
from app.schemas.global_memory import GlobalMemoryOperationRequest, GlobalMemoryRecordResponse
from app.services.project import memory_management as module


def _service(tmp_path, events=()):
    root = tmp_path / "memory"
    root.mkdir()
    path = root / "global_memory.jsonl"
    path.write_text("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events), encoding="utf-8")
    repository = ProjectConversationMemoryRepository(Mock(), global_memory_root=root)
    return module.ProjectMemoryManagementService(repository), path


def _event(memory_id, operation="add", **kwargs):
    return {
        "operation": operation,
        "memory_id" if operation == "add" else "target_memory_id": memory_id,
        "content": "内容 " + memory_id,
        "keywords": ["记忆"],
        "created_at": "2026-10-27T00:00:00Z",
        "reason": "测试",
        "source_compression_id": "test",
        **kwargs,
    }


@pytest.mark.parametrize("operation", ["add", "update", "delete"])
def test_manual_operation_returns_same_full_record_without_listing_all(tmp_path, monkeypatch, operation):
    events = [_event(f"unrelated-{i}") for i in range(1000)]
    if operation != "add":
        events.insert(2, _event("target"))
        events.insert(5, _event("target", "update", content="旧内容", keywords=["旧关键词"]))
    service, _ = _service(tmp_path, events)
    list_records = service.list_memory_records
    summary_ids = []
    summary = module._event_summary

    def track_summary(event, **kwargs):
        summary_ids.append(kwargs["memory_id"])
        return summary(event, **kwargs)

    with monkeypatch.context() as changes:
        changes.setattr(route, "get_project_memory_management_service", lambda: service)
        changes.setattr(service, "list_memory_records", Mock(side_effect=AssertionError("full listing")))
        changes.setattr(service._repository, "list_global_memory_events", Mock(side_effect=AssertionError("full event list")))
        changes.setattr(module, "_event_summary", track_summary)
        result = route.apply_global_memory_operation(GlobalMemoryOperationRequest(
            operation=operation, memory_id=None if operation == "add" else "target",
            content="新内容\n第二行", keywords=["新关键词"], reason="用户修改",
        ))
    expected = next(item for item in list_records(scope="global", status="all")["items"] if item["id"] == result.memory_id)
    assert result.memory == GlobalMemoryRecordResponse(**expected)
    assert summary_ids == [result.memory_id] * (1 if operation == "add" else 3)
    assert result.memory.events[-1].event_index == len(events) + 1
    if operation == "delete":
        assert result.memory.status == "deleted"
        assert result.memory.content == "旧内容"
        assert result.memory.keywords == ["旧关键词"]
        assert result.memory.events[-1].after is None
    else:
        assert result.memory.status == "active"
        assert result.memory.content == "新内容\n第二行"


def test_single_record_streams_log_and_preserves_global_event_numbers(tmp_path, monkeypatch):
    events = [
        _event("target"), _event("other"),
        _event("target", "update", content="第二版"),
        _event("other", "delete"), _event("target", "delete"),
    ]
    service, path = _service(tmp_path, events)
    path.write_text("\n" + path.read_text(encoding="utf-8").replace("\n", "\n\n"), encoding="utf-8")
    from pathlib import Path
    monkeypatch.setattr(Path, "read_text", Mock(side_effect=AssertionError("must stream JSONL")))
    record = service.get_memory_record(scope="global", memory_id="target")
    assert record["status"] == "deleted"
    assert record["event_count"] == 3
    assert [event["event_index"] for event in record["events"]] == [1, 3, 5]
    assert record["events"][1]["before"]["content"] == "内容 target"
    assert record["content"] == "第二版"
    assert service.get_memory_record(scope="global", memory_id="missing") is None


@pytest.mark.parametrize("suffix,match", [('{broken\n', 'Invalid conversation memory'), ('[]\n', 'must be objects')])
def test_single_record_does_not_hide_corrupt_unrelated_log_entries(tmp_path, suffix, match):
    service, path = _service(tmp_path, [_event("target")])
    with path.open("a", encoding="utf-8") as out:
        out.write(suffix)
    with pytest.raises(ValueError, match=match):
        service.get_memory_record(scope="global", memory_id="target")


def test_missing_global_memory_file_returns_no_record(tmp_path):
    service, path = _service(tmp_path)
    path.unlink()
    assert service.get_memory_record(scope="global", memory_id="missing") is None
    assert service._repository.list_global_memory_events() == []
    assert not path.exists()


def test_single_project_record_keeps_scope_and_event_numbers():
    repository = Mock()
    repository.list_project_memory_events.return_value = [_event("other"), _event("target")]
    service = module.ProjectMemoryManagementService(repository)
    record = service.get_memory_record(scope="project", project_id="project-a", memory_id="target")
    assert record["scope"] == "project"
    assert record["events"][0]["event_index"] == 2
    repository.list_project_memory_events.assert_called_once_with("project-a")
    repository.iter_global_memory_events.assert_not_called()
