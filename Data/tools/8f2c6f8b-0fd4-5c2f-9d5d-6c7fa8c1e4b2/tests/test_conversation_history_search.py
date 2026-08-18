from __future__ import annotations

import json
from gzip import compress as gzip_compress
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


TOOL_ROOT = Path(__file__).resolve().parents[1]


def call(root: Path, payload: dict[str, object], *, session_id: str = "session-a") -> dict:
    runtime_root = root / "test-runtime"
    runtime_root.mkdir(exist_ok=True)
    (runtime_root / "tiance_runtime.py").write_text(
        """import json
import sys

def run_tool(handler):
    payload = json.loads(sys.stdin.read() or "{}")
    sys.stdout.write(json.dumps(handler(payload), ensure_ascii=False))
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["TIANCE_WORKSPACE_ROOT"] = str(root)
    env["TIANCE_SESSION_ID"] = session_id
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(TOOL_ROOT / "program"), str(runtime_root)]
    )
    completed = subprocess.run(
        [sys.executable, str(TOOL_ROOT / "program" / "main.py")],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )
    return json.loads(completed.stdout)


def make_database(root: Path) -> None:
    workspace = root / ".Tiance"
    workspace.mkdir()
    connection = sqlite3.connect(workspace / "tiance.db")
    connection.executescript(
        """
        CREATE TABLE conversation_sessions (
            session_id TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE conversation_messages (
            session_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            message_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(session_id, ordinal)
        );
        CREATE TABLE conversation_session_events (
            session_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(session_id, kind, ordinal)
        );
        CREATE TABLE conversation_artifacts (
            artifact_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            media_type TEXT NOT NULL,
            encoding TEXT,
            size_bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL
        );
        CREATE TABLE conversation_artifact_payloads (
            artifact_id TEXT PRIMARY KEY,
            compression TEXT NOT NULL,
            stored_size_bytes INTEGER NOT NULL,
            payload_blob BLOB NOT NULL
        );
        CREATE TABLE conversation_journal (
            event_id INTEGER PRIMARY KEY,
            session_id TEXT,
            run_id TEXT,
            turn_id TEXT,
            tool_call_id TEXT,
            event_type TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            artifact_id TEXT
        );
        """
    )
    for session_id, title in (("session-a", "当前会话"), ("session-b", "其他会话")):
        connection.execute(
            "INSERT INTO conversation_sessions VALUES (?, ?)",
            (session_id, json.dumps({"session_id": session_id, "title": title}, ensure_ascii=False)),
        )
    messages = [
        ("session-a", 0, "m1", {"role": "user", "content": "Word 表格里的公式怎么修改", "created_at": "t1"}),
        ("session-a", 1, "m2", {"role": "assistant", "content": "先定位 Word 原生公式", "created_at": "t2"}),
        ("session-a", 2, "m-error", {"role": "error", "content": "供应商请求失败", "created_at": "t3"}),
        ("session-b", 0, "m3", {"role": "user", "content": "Excel 复杂格式", "created_at": "t3"}),
    ]
    connection.executemany(
        "INSERT INTO conversation_messages VALUES (?, ?, ?, ?)",
        [(sid, ordinal, mid, json.dumps(payload, ensure_ascii=False)) for sid, ordinal, mid, payload in messages],
    )
    connection.execute(
        "INSERT INTO conversation_session_events VALUES (?, ?, ?, ?)",
        (
            "session-a",
            "model_exchanges",
            0,
            json.dumps({"provider_id": "deepseek", "response_status": 200}, ensure_ascii=False),
        ),
    )
    connection.execute(
        "INSERT INTO conversation_journal VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            1,
            "session-a",
            "run-1",
            "m1",
            "call-1",
            "tool.execution.completed",
            "2026-08-18T00:00:00Z",
            json.dumps({"tool_name": "word_document_editor"}, ensure_ascii=False),
            "artifact-1",
        ),
    )
    exchange = json.dumps(
        {
            "request": {"model": "deepseek-v4-flash", "input": "原始请求标记"},
            "response": {"status": 200, "body": "原始响应标记"},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    compressed = gzip_compress(exchange, mtime=0)
    connection.execute(
        "INSERT INTO conversation_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "artifact-1", "session-a", "model_http_exchange",
            "conversations/sessions/session-a/model_http_exchanges.jsonl",
            "application/json", "utf-8", len(exchange), "digest", "complete",
            "2026-08-18T00:00:00Z", json.dumps({"provider_id": "deepseek"}),
        ),
    )
    connection.execute(
        "INSERT INTO conversation_artifact_payloads VALUES (?, ?, ?, ?)",
        ("artifact-1", "gzip", len(compressed), compressed),
    )
    connection.commit()
    connection.close()


def test_defaults_to_current_session_and_returns_raw_record(tmp_path: Path) -> None:
    make_database(tmp_path)
    result = call(tmp_path, {"query": "Word 表格", "mode": "contains"})
    assert result["ok"] is True
    assert result["session_id"] == "session-a"
    assert result["total_count"] == 1
    assert result["results"][0]["raw"]["content"] == "Word 表格里的公式怎么修改"


def test_can_search_another_session_and_filter_role(tmp_path: Path) -> None:
    make_database(tmp_path)
    result = call(
        tmp_path,
        {
            "query": "Excel 复杂",
            "mode": "all_terms",
            "session_id": "session-b",
            "roles": ["user"],
            "include_raw": False,
        },
    )
    assert result["ok"] is True
    assert result["session_title"] == "其他会话"
    assert result["results"][0]["message_id"] == "m3"
    assert "raw" not in result["results"][0]


def test_reports_missing_project_database(tmp_path: Path) -> None:
    result = call(tmp_path, {"query": "anything"})
    assert result["ok"] is False
    assert result["error"]["code"] == "DATABASE_NOT_FOUND"


def test_supports_error_role(tmp_path: Path) -> None:
    make_database(tmp_path)
    result = call(tmp_path, {"query": "供应商", "roles": ["error"]})
    assert result["ok"] is True
    assert result["total_count"] == 1
    assert result["results"][0]["role"] == "error"


def test_searches_model_exchanges_journal_and_raw_artifacts(tmp_path: Path) -> None:
    make_database(tmp_path)

    exchanges = call(tmp_path, {"query": "deepseek", "sources": ["model_exchanges"]})
    assert exchanges["ok"] is True
    assert exchanges["results"][0]["source"] == "model_exchanges"

    journal = call(tmp_path, {"query": "word_document_editor", "sources": ["journal"]})
    assert journal["ok"] is True
    assert journal["results"][0]["event_type"] == "tool.execution.completed"

    artifacts = call(tmp_path, {"query": "原始响应标记", "sources": ["artifacts"]})
    assert artifacts["ok"] is True
    assert artifacts["results"][0]["raw"]["payload"]["response"]["status"] == 200


def test_paginates_across_selected_sources(tmp_path: Path) -> None:
    make_database(tmp_path)
    result = call(
        tmp_path,
        {
            "query": "deepseek",
            "sources": ["model_exchanges", "artifacts"],
            "limit": 1,
            "offset": 1,
        },
    )
    assert result["ok"] is True
    assert result["total_count"] == 2
    assert result["source_counts"] == {"model_exchanges": 1, "artifacts": 1}
    assert result["results"][0]["source"] == "artifacts"


def test_rejects_exact_content_for_non_message_sources(tmp_path: Path) -> None:
    make_database(tmp_path)
    result = call(
        tmp_path,
        {"query": "deepseek", "mode": "exact_content", "sources": ["journal"]},
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "MODE_SOURCE_CONFLICT"
