from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.repositories.tools.tool_call_record_repository import ToolCallRecordRepository
from tests.test_tool_call_records import _draft


@pytest.mark.parametrize("tail", [b'{"record_id":', b'{"text":"\xe4\xb8', b'{"text":"' + b'x' * 20000])
@pytest.mark.parametrize("recover_by", ["read", "append"])
def test_torn_tail_preserves_old_and_new_calls(tmp_path, tail, recover_by):
    repository = ToolCallRecordRepository()
    first = repository.append(tmp_path, _draft())
    path = repository.records_path(tmp_path)
    with path.open("ab") as output:
        output.write(tail)
    if recover_by == "read":
        assert repository.list_project_records(tmp_path) == (first,)
    second = repository.append(tmp_path, _draft(call_id="second"))
    assert {item.record_id for item in repository.list_project_records(tmp_path)} == {first.record_id, second.record_id}
    backup, = path.parent.glob("*.corrupt-tail")
    assert backup.read_bytes() == tail
    assert len(list(path.parent.glob("*.corrupt-tail"))) == 1


def test_complete_record_without_newline_is_retained(tmp_path):
    repository = ToolCallRecordRepository()
    first = repository.append(tmp_path, _draft())
    path = repository.records_path(tmp_path)
    path.write_bytes(path.read_bytes().rstrip(b"\n"))
    repository.append(tmp_path, _draft(call_id="second"))
    assert first in repository.list_project_records(tmp_path)
    assert len(repository.list_project_records(tmp_path)) == 2
    assert not list(path.parent.glob("*.corrupt-tail"))


@pytest.mark.parametrize("damage", [b'{"broken":\n', b'{"record_id":"invalid-schema"}', b'bad\n{}\n'])
def test_complete_bad_records_are_not_silently_deleted(tmp_path, damage):
    repository = ToolCallRecordRepository()
    path = repository.records_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(damage)
    with pytest.raises(ValueError):
        repository.list_project_records(tmp_path)
    assert path.read_bytes() == damage
    assert not list(path.parent.glob("*.corrupt-tail"))


def test_tail_backup_failure_keeps_original_bytes(tmp_path, monkeypatch):
    repository = ToolCallRecordRepository()
    path = repository.records_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{"broken":')
    real_open = Path.open

    def open_file(path, *args, **kwargs):
        if path.name.endswith(".corrupt-tail"):
            raise OSError("disk full")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_file)
    with pytest.raises(OSError, match="disk full"):
        repository.append(tmp_path, _draft())
    assert path.read_bytes() == b'{"broken":'


def test_read_and_append_are_serialized_during_tail_recovery(tmp_path):
    repository = ToolCallRecordRepository()
    repository.append(tmp_path, _draft())
    path = repository.records_path(tmp_path)
    with path.open("ab") as output:
        output.write(b'{"broken":')
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = []
        for i in range(12):
            futures.append(executor.submit(repository.append, tmp_path, _draft(call_id=f"call-{i}")))
            futures.append(executor.submit(repository.list_project_records, tmp_path))
        for future in futures:
            future.result(timeout=5)
    assert len(repository.list_project_records(tmp_path)) == 13
    assert len(list(path.parent.glob("*.corrupt-tail"))) == 1
