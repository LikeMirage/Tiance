"""Explicit, offline repair of inherited image snapshots; dry-run by default.

No schema migration, model requests, task retries or deletion of failed history.
Only an ancestor's verified attachment may be restored into a derived session.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import sys
from uuid import uuid4

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "1_PythonServer"))
from app.repositories.project.conversation_attachment_repository import referenced_attachment_ids
from app.repositories.project.conversation_serialization import _message_from_payload


def attachment_path(workspace: Path, session: str, record: dict) -> Path:
    directory = (workspace / "conversations" / "sessions" / session / "attachments").resolve()
    path = (directory / record["stored_name"]).resolve()
    if path.parent != directory or not directory.is_relative_to(workspace.resolve()):
        raise ValueError("Unsafe attachment path")
    return path


def verify_file(path: Path, record: dict) -> None:
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    if path.stat().st_size != record["size_bytes"] or digest.hexdigest() != record["sha256"]:
        raise ValueError(f"Attachment integrity check failed: {path}")


def plan_repairs(connection: sqlite3.Connection, workspace: Path) -> list[dict]:
    if connection.execute("SELECT 1 FROM conversation_runs WHERE status = 'running' LIMIT 1").fetchone():
        raise RuntimeError("Project has running tasks; stop them before repairing attachments.")
    row = connection.execute("SELECT value_json FROM conversation_meta WHERE key = 'branch_graph'").fetchone()
    graph = json.loads(row[0]) if row else {}
    parents = {n["session_id"]: n.get("parent_session_id") for n in graph.get("nodes", [])
               if n.get("history_mode") == "copy" and not n.get("deleted_at")}
    records = defaultdict(dict)
    for session, payload in connection.execute(
        "SELECT session_id, payload_json FROM conversation_session_events WHERE kind = 'attachments' ORDER BY ordinal"
    ):
        record = json.loads(payload)
        records[session].setdefault(record["attachment_id"], record)
    needed = defaultdict(set)
    for session, payload in connection.execute("SELECT session_id, payload_json FROM conversation_messages"):
        if session in parents:
            needed[session].update(referenced_attachment_ids((_message_from_payload(json.loads(payload)),)))
    repairs = []
    verified = set()
    for session, ids in needed.items():
        for attachment_id in sorted(ids):
            existing = records[session].get(attachment_id)
            if existing and attachment_path(workspace, session, existing).is_file():
                continue
            ancestor = parents.get(session)
            visited = {session}
            while ancestor and ancestor not in visited:
                visited.add(ancestor)
                source_record = records[ancestor].get(attachment_id)
                if source_record:
                    source = attachment_path(workspace, ancestor, source_record)
                    if source.is_file():
                        if source not in verified:
                            verify_file(source, source_record)
                            verified.add(source)
                        if existing and existing != source_record:
                            raise ValueError(f"Conflicting attachment metadata in {session}: {attachment_id}")
                        target = attachment_path(workspace, session, source_record)
                        if target.exists():
                            verify_file(target, source_record)
                        repairs.append({"session_id": session, "source_session_id": ancestor,
                            "record": source_record, "source": source, "target": target,
                            "add_record": existing is None})
                        break
                ancestor = parents.get(ancestor)
            else:
                raise ValueError(f"No verified ancestor attachment for {session}: {attachment_id}")
    return repairs


def repair(project: Path, *, apply: bool = False) -> dict:
    workspace = project.resolve() / ".Tiance"
    database = workspace / "tiance.db"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=5) as reader:
        reader.execute("PRAGMA query_only=ON")
        version = reader.execute("PRAGMA data_version").fetchone()[0]
        plan = plan_repairs(reader, workspace)
        summary = {"sessions": len({p["session_id"] for p in plan}), "attachments": len(plan),
            "new_records": sum(p["add_record"] for p in plan),
            "copy_bytes": sum(p["record"]["size_bytes"] for p in plan if not p["target"].exists()),
            "applied": False}
        if not apply or not plan:
            return summary
        backup_dir = workspace / "repair-backups" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8])
        backup_dir.mkdir(parents=True)
        backup = backup_dir / "tiance.db"
        with sqlite3.connect(backup) as saved:
            reader.backup(saved)
        created_files = []
        try:
            for item in plan:
                target = item["target"]
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    # Exclusive creation: never overwrite a file written by the application.
                    with target.open("xb") as output:
                        created_files.append(target)
                        with item["source"].open("rb") as source:
                            shutil.copyfileobj(source, output, 1024 * 1024)
                verify_file(target, item["record"])
            with sqlite3.connect(database, timeout=5) as writer:
                writer.execute("BEGIN IMMEDIATE")
                if reader.execute("PRAGMA data_version").fetchone()[0] != version:
                    raise RuntimeError("Project changed during repair; database was not modified. Retry when idle.")
                if writer.execute("SELECT 1 FROM conversation_runs WHERE status = 'running' LIMIT 1").fetchone():
                    raise RuntimeError("A task started during repair; database was not modified.")
                for item in plan:
                    if item["add_record"]:
                        ordinal = writer.execute(
                            "SELECT COALESCE(MAX(ordinal), -1) + 1 FROM conversation_session_events WHERE session_id = ? AND kind = 'attachments'",
                            (item["session_id"],),
                        ).fetchone()[0]
                        writer.execute("INSERT INTO conversation_session_events VALUES (?, 'attachments', ?, ?)",
                            (item["session_id"], ordinal, json.dumps(item["record"], ensure_ascii=False)))
                writer.commit()
        except BaseException:
            for path in reversed(created_files):
                path.unlink(missing_ok=True)
            raise
        summary.update(applied=True, backup=str(backup))
        report = {**summary, "restored": [{"session_id": p["session_id"],
            "source_session_id": p["source_session_id"], "attachment_id": p["record"]["attachment_id"]} for p in plan]}
        (backup_dir / "repair.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(repair(args.project, apply=args.apply), ensure_ascii=False, indent=2))
