from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from gzip import compress
from hashlib import sha256
from pathlib import Path
from random import Random
import sqlite3

import pytest

from app.repositories.project import conversation_database as db
from app.repositories.project.conversation_audit_delta import apply_delta, json_bytes, make_delta
from app.repositories.project.conversation_audit_snapshots import (
    MAX_DELTA_DEPTH,
)


def session_path(tmp_path: Path, session_id: str = "session-1") -> Path:
    conversations = tmp_path / ".Tiance" / "conversations"
    db.write_session(conversations, session_id, {"session_id": session_id})
    return conversations / "sessions" / session_id


def connection_for(session: Path) -> sqlite3.Connection:
    return sqlite3.connect(db.database_path_from_session(session))


def test_changes_restore_exact_bytes_after_append_compaction_reorder_and_parameter_removal(tmp_path: Path) -> None:
    session = session_path(tmp_path)
    tools = [{"name": "read", "description": "工具描述" * 600}]
    initial = {
        "round_index": 1,
        "request_snapshot": {
            "tools": tools,
            "messages": [{"role": "user", "content": "原始上下文" * 600}],
            "temperature": 1, "optional": None,
        },
        "response": {"content": "回复" * 600},
    }
    appended = deepcopy(initial)
    appended["round_index"] = 2
    appended["request_snapshot"]["messages"].append({"role": "assistant", "content": "回复" * 600})
    compressed = deepcopy(appended)
    compressed["round_index"] = 3
    compressed["request_snapshot"]["messages"] = [{"role": "system", "content": "压缩后的记忆"}]
    compressed["request_snapshot"]["tools"].append({"name": "write", "description": "写入"})
    del compressed["request_snapshot"]["temperature"]
    reordered = deepcopy(appended)
    reordered["request_snapshot"]["messages"].reverse()
    reordered["request_snapshot"]["temperature"] = 1.0
    reordered["response"] = {"content": True}
    reordered = dict(reversed(list(reordered.items())))
    expected = [initial, appended, compressed, reordered]
    for payload in expected:
        db.append_event(session, "model_exchanges", payload)

    # Every page is independently readable; no prior page or in-memory writer state is required.
    for ordinal, payload in reversed(list(enumerate(expected))):
        page = db.list_events_range(session, "model_exchanges", start_ordinal=ordinal, end_ordinal=ordinal + 1)
        assert json_bytes(page[0]) == json_bytes(payload)
    with connection_for(session) as connection:
        assert connection.execute("SELECT COUNT(*) FROM conversation_audit_blocks").fetchone()[0] == 4
        assert connection.execute("SELECT MAX(depth) FROM conversation_audit_snapshots").fetchone()[0] > 0


def test_long_chain_uses_bounded_checkpoints_and_shares_large_content(tmp_path: Path) -> None:
    session = session_path(tmp_path)
    messages = [{"role": "user", "content": sha256(str(i).encode()).hexdigest()} for i in range(120)]
    expected = []
    for i in range(MAX_DELTA_DEPTH * 2 + 5):
        payload = {"round": i, "messages": messages[:], "tools": [{"schema": "x" * 5000}]}
        expected.append(payload)
        db.append_event(session, "model_exchanges", payload)
        messages.append({"role": "tool", "content": f"第 {i} 次工具结果"})
    with connection_for(session) as connection:
        depths = [row[0] for row in connection.execute("SELECT depth FROM conversation_audit_snapshots ORDER BY snapshot_id")]
        assert max(depths) == MAX_DELTA_DEPTH
        assert depths[MAX_DELTA_DEPTH + 1] == 0
        assert connection.execute("SELECT COUNT(*) FROM conversation_audit_blocks").fetchone()[0] == 1
        stored = connection.execute("SELECT SUM(length(payload_blob)) FROM conversation_audit_snapshots").fetchone()[0]
        assert stored < sum(len(compress(json_bytes(value))) for value in expected) / 3
    assert db.read_events(session, "model_exchanges") == expected


def test_snapshot_and_owner_rollback_together_and_concurrent_appends_do_not_lose_rounds(tmp_path: Path) -> None:
    session = session_path(tmp_path)
    with pytest.raises(RuntimeError, match="abort"):
        with db.transaction_for_conversations(session.parent.parent):
            db.append_event(session, "model_exchanges", {"large": "rollback" * 1000})
            raise RuntimeError("abort")
    with connection_for(session) as connection:
        for table in ("conversation_session_events", "conversation_audit_snapshots", "conversation_audit_blocks"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda i: db.append_event(session, "model_exchanges", {"round": i, "text": "shared" * 1000}), range(20)))
    assert sorted(row["round"] for row in db.read_events(session, "model_exchanges")) == list(range(20))
    with connection_for(session) as connection:
        assert connection.execute("SELECT COUNT(*) FROM conversation_audit_snapshots").fetchone()[0] == 20
        assert connection.execute("SELECT COUNT(*) FROM conversation_audit_blocks").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_replace_and_delete_release_only_unreferenced_blocks(tmp_path: Path) -> None:
    first, second = session_path(tmp_path, "first"), session_path(tmp_path, "second")
    shared = {"shared": "common" * 1000}
    db.append_event(first, "model_exchanges", {**shared, "private": "private" * 1000})
    db.append_event(first, "model_exchanges", {**shared, "private": "private" * 1000, "round": 2})
    db.append_event(second, "model_exchanges", shared)
    with connection_for(first) as connection:
        assert connection.execute("SELECT COUNT(*) FROM conversation_audit_blocks").fetchone()[0] == 2
    db.replace_events(first, "model_exchanges", [shared, {**shared, "round": 3}])
    with connection_for(first) as connection:
        assert connection.execute("SELECT COUNT(*) FROM conversation_audit_blocks").fetchone()[0] == 1
    db.delete_session(first.parent.parent, first.name)
    assert db.read_events(second, "model_exchanges") == [shared]
    db.delete_session(second.parent.parent, second.name)
    with connection_for(second) as connection:
        for table in ("conversation_audit_snapshots", "conversation_audit_snapshot_blocks", "conversation_audit_blocks"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("payload", [
    {"request": {"messages": []}},
    {"__tiance_audit_manifest__": 1, "payload": {}, "external_values": []},
    {"__tiance_audit_manifest__": 99, "snapshot_id": 1},
])
def test_model_audit_requires_current_snapshot_format(tmp_path: Path, payload: dict) -> None:
    session = session_path(tmp_path)
    with connection_for(session) as connection:
        connection.execute(
            "INSERT INTO conversation_session_events VALUES (?, 'model_exchanges', 0, ?)",
            (session.name, json_bytes(payload).decode()),
        )
    with pytest.raises(RuntimeError, match="Invalid incremental audit manifest"):
        db.read_events(session, "model_exchanges")
    with pytest.raises(RuntimeError, match="Invalid incremental audit manifest"):
        db.list_events_range(session, "model_exchanges", start_ordinal=0, end_ordinal=1)


@pytest.mark.parametrize("compression", ["gzip", "gzip+audit-manifest-v1", "unknown"])
def test_http_audit_rejects_unsupported_storage_formats(tmp_path: Path, compression: str) -> None:
    session = session_path(tmp_path)
    payload = json_bytes({"request": {}, "response": {}})
    blob = compress(payload)
    db.write_artifact_record(
        session.parents[2], artifact_id="unsupported", session_id=session.name,
        kind="model_http_exchange", relative_path="", media_type="application/json", encoding="utf-8",
        size_bytes=len(payload), sha256=sha256(payload).hexdigest(), status="complete",
        created_at="2026-10-19T00:00:00Z", metadata={}, payload_blob=blob,
        compression=compression, stored_size_bytes=len(blob),
    )
    with pytest.raises(RuntimeError, match="unsupported compression"):
        db.list_embedded_artifacts_range(
            session.parents[2], session_id=session.name, kind="model_http_exchange", offset=0, limit=10,
        )


@pytest.mark.parametrize("damage", ["block", "missing_block", "tree", "base", "scope"])
def test_corruption_is_reported_instead_of_silently_returning_incomplete_context(tmp_path: Path, damage: str) -> None:
    session = session_path(tmp_path)
    payload = {"text": "large" * 1000, "items": list(range(200)), "round": 1}
    db.append_event(session, "model_exchanges", payload)
    db.append_event(session, "model_exchanges", {**payload, "round": 2})
    with connection_for(session) as connection:
        if damage == "block":
            connection.execute("UPDATE conversation_audit_blocks SET payload_blob = ?", (compress(b"corrupt"),))
        elif damage == "missing_block":
            connection.execute("DELETE FROM conversation_audit_blocks")
        elif damage == "tree":
            connection.execute("UPDATE conversation_audit_snapshots SET tree_sha256 = 'bad'")
        elif damage == "scope":
            connection.execute("UPDATE conversation_audit_snapshots SET stream = 'another_stream'")
        else:
            connection.execute("DELETE FROM conversation_audit_snapshots WHERE depth = 0")
    with pytest.raises(RuntimeError, match="Audit"):
        db.list_events_range(session, "model_exchanges", start_ordinal=1, end_ordinal=2)


def test_delta_preserves_json_types_and_key_order_across_random_edits() -> None:
    random = Random(20261019)

    def value(depth: int = 0):
        if depth > 2 or random.random() < .4:
            return random.choice([None, True, False, 0, 1, 1.0, -0.0, "", "中文", "~[/]"])
        if random.random() < .5:
            return [value(depth + 1) for _ in range(random.randrange(5))]
        return {str(key): value(depth + 1) for key in random.sample(range(6), random.randrange(6))}

    pairs = [({"a": 1, "b": 2}, {"b": 2, "a": 1}), (1, True), (1, 1.0)]
    pairs += [(value(), value()) for _ in range(250)]
    for before, after in pairs:
        original = json_bytes(before)
        assert json_bytes(apply_delta(before, make_delta(before, after))) == json_bytes(after)
        assert json_bytes(before) == original
