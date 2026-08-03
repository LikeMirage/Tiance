from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

TOOL_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def call(root: Path | None, payload: dict[str, object]) -> dict[str, object]:
    env = os.environ.copy()
    if root is None:
        env.pop("TIANCE_WORKSPACE_ROOT", None)
    else:
        env["TIANCE_WORKSPACE_ROOT"] = str(root)
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


def test_index_search_update_and_change_detection(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "memory.md").write_text("长期记忆变更通知必须原文保留。\n第二行内容。", encoding="utf-8")
    (tmp_path / "app.py").write_text("def build_index():\n    return 'workspace search'\n", encoding="utf-8")

    indexed = call(tmp_path, {"operation": "index"})
    assert indexed["ok"] is True
    assert indexed["data"]["file_count"] == 2

    chinese = call(tmp_path, {"operation": "search", "query": "长期记忆", "mode": "phrase"})
    assert chinese["ok"] is True
    assert chinese["data"]["engine"] == "fts5_trigram"
    assert chinese["data"]["results"][0]["path"] == "docs/memory.md"

    short = call(tmp_path, {"operation": "search", "query": "记忆"})
    assert short["ok"] is True
    assert short["data"]["engine"] == "literal_fallback"

    (tmp_path / "docs" / "memory.md").write_text("长期记忆已经更新。", encoding="utf-8")
    (tmp_path / "new.txt").write_text("新增文本", encoding="utf-8")
    (tmp_path / "app.py").unlink()
    changes = call(tmp_path, {"operation": "check_changes", "verification": "quick"})
    assert changes["ok"] is True
    assert changes["data"]["stale"] is True
    assert changes["data"]["counts"] == {"new": 1, "modified": 1, "deleted": 1, "unreadable": 0}

    updated = call(tmp_path, {"operation": "update"})
    assert updated["ok"] is True
    current = call(tmp_path, {"operation": "check_changes", "verification": "hash"})
    assert current["data"]["stale"] is False


def test_excludes_internal_dependencies_and_credentials(tmp_path: Path) -> None:
    (tmp_path / "visible.txt").write_text("可以建立索引", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=value", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "package.js").write_text("dependency", encoding="utf-8")
    result = call(tmp_path, {"operation": "index"})
    assert result["ok"] is True
    assert result["data"]["file_count"] == 1

    secret = call(tmp_path, {"operation": "search", "query": "SECRET"})
    assert secret["data"]["count"] == 0


def test_requires_real_workspace() -> None:
    result = call(None, {"operation": "status"})
    assert result["ok"] is False
    assert result["error_info"]["code"] == "WORKSPACE_REQUIRED"
