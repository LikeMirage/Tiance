from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import sqlite3
from unittest.mock import Mock

import pytest

from app.domain.tools.call_record_page import ToolCallRecordSnapshotExpired
from app.repositories.tools import ToolCallRecordRepository
from app.repositories.tools import tool_call_record_index as index_module
from app.repositories.tools.tool_call_record_repository import _payload_to_record
from tests.test_tool_call_record_pagination import write_history


@pytest.mark.parametrize("version", [0, 987])
def test_incompatible_index_is_rebuilt_from_source_without_touching_history(tmp_path, version):
    repository = ToolCallRecordRepository()
    path = write_history(repository, tmp_path, 4)
    original = path.read_bytes()
    index = path.with_name("records-index.sqlite3")
    with closing(sqlite3.connect(index)) as db, db:
        db.execute("CREATE TABLE records (obsolete TEXT)")
        db.execute("CREATE TABLE obsolete_metadata (value TEXT)")
        db.execute("INSERT INTO records VALUES ('stale cache')")
        db.execute(f"PRAGMA user_version = {version}")

    page = repository.list_project_page(tmp_path)
    assert [row.record_id for row in page.items] == [f"record-{i}" for i in reversed(range(4))]
    assert page.count == 4
    assert repository.get_project_record(tmp_path, "record-2").result_text == "长返回内容" * 1600
    assert path.read_bytes() == original
    with closing(sqlite3.connect(index)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == index_module.INDEX_SCHEMA_VERSION
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='obsolete_metadata'").fetchone()


@pytest.mark.parametrize("change", [
    "PRAGMA user_version = 0",
    "DROP INDEX records_order",
    "ALTER TABLE records DROP COLUMN dynamic",
    "DROP TABLE source",
])
def test_rebuild_invalidates_old_page_snapshot_and_is_reused_afterwards(tmp_path, monkeypatch, change):
    repository = ToolCallRecordRepository()
    path = write_history(repository, tmp_path, 3)
    first = repository.list_project_page(tmp_path)
    original = path.read_bytes()
    with closing(sqlite3.connect(path.with_name("records-index.sqlite3"))) as db, db:
        db.execute(change)
    with pytest.raises(ToolCallRecordSnapshotExpired):
        repository.list_project_page(tmp_path, snapshot=first.snapshot)
    rebuilt = repository.list_project_page(tmp_path)
    assert rebuilt.items == first.items
    assert rebuilt.snapshot != first.snapshot
    parse = Mock(wraps=index_module.json.loads)
    monkeypatch.setattr(index_module.json, "loads", parse)
    assert repository.list_project_page(tmp_path, snapshot=rebuilt.snapshot) == rebuilt
    assert parse.call_count == 0
    assert path.read_bytes() == original


def test_failed_rebuild_rolls_back_schema_and_version_and_can_retry(tmp_path):
    repository = ToolCallRecordRepository()
    path = write_history(repository, tmp_path, 3)
    original = path.read_bytes()
    # A complete bad record must be reported, never skipped to produce an incomplete index.
    path.write_bytes(original + b'{"invalid":true}\n')
    invalid = path.read_bytes()
    index = path.with_name("records-index.sqlite3")
    with closing(sqlite3.connect(index)) as db, db:
        db.execute("CREATE TABLE records (obsolete TEXT)")
        db.execute("INSERT INTO records VALUES ('previous cache')")
    with pytest.raises(ValueError, match="第 4 行"):
        repository.list_project_page(tmp_path)
    assert path.read_bytes() == invalid
    with closing(sqlite3.connect(index)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0
        assert db.execute("SELECT * FROM records").fetchall() == [("previous cache",)]
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='source'").fetchone()
    path.write_bytes(original)
    assert repository.list_project_page(tmp_path).count == 3


def test_concurrent_connections_rebuild_once(tmp_path):
    repository = ToolCallRecordRepository()
    path = write_history(repository, tmp_path, 4)
    parse = Mock(wraps=_payload_to_record)

    def read_index():
        with index_module.record_index(path, parse) as db:
            return db.execute("SELECT generation FROM source").fetchone()[0]

    with ThreadPoolExecutor(max_workers=4) as executor:
        generations = list(executor.map(lambda _: read_index(), range(4)))
    assert len(set(generations)) == 1
    assert parse.call_count == 4
