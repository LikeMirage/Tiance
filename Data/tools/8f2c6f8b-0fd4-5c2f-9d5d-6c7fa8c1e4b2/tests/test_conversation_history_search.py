from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


TOOL_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def call(root: Path, payload: dict[str, object], *, session_id: str = "session-a") -> dict:
    env = os.environ.copy()
    env["TIANCE_WORKSPACE_ROOT"] = str(root)
    env["TIANCE_SESSION_ID"] = session_id
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(TOOL_ROOT / "program"), str(REPOSITORY_ROOT / "1_PythonServer")]
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


def make_storage(root: Path) -> None:
    sessions_root = root / ".Tiance" / "conversations" / "sessions"
    for session_id, title in (("session-a", "当前会话"), ("session-b", "其他会话")):
        session_dir = sessions_root / session_id
        session_dir.mkdir(parents=True)
        (session_dir / "session.json").write_text(
            json.dumps({"session_id": session_id, "title": title}, ensure_ascii=False),
            encoding="utf-8",
        )
    messages = [
        ("session-a", 0, "m1", {"role": "user", "content": "Word 表格里的公式怎么修改", "created_at": "t1"}),
        ("session-a", 1, "m2", {"role": "assistant", "content": "先定位 Word 原生公式", "created_at": "t2"}),
        ("session-b", 0, "m3", {"role": "user", "content": "Excel 复杂格式", "created_at": "t3"}),
    ]
    for session_id in ("session-a", "session-b"):
        records = [
            {"message_id": message_id, **payload}
            for candidate_id, _ordinal, message_id, payload in messages
            if candidate_id == session_id
        ]
        (sessions_root / session_id / "messages.jsonl").write_text(
            "".join(
                json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
                for record in records
            ),
            encoding="utf-8",
        )


def test_defaults_to_current_session_and_returns_raw_record(tmp_path: Path) -> None:
    make_storage(tmp_path)
    result = call(tmp_path, {"query": "Word 表格", "mode": "contains"})
    assert result["ok"] is True
    assert result["session_id"] == "session-a"
    assert result["total_count"] == 1
    assert result["results"][0]["raw"]["content"] == "Word 表格里的公式怎么修改"


def test_can_search_another_session_and_filter_role(tmp_path: Path) -> None:
    make_storage(tmp_path)
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


def test_reports_missing_session_storage(tmp_path: Path) -> None:
    result = call(tmp_path, {"query": "anything"})
    assert result["ok"] is False
    assert result["error"]["code"] == "SESSION_NOT_FOUND"
