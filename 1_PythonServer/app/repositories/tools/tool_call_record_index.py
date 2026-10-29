"""Disposable, on-disk metadata/byte-offset index; records.jsonl remains authoritative."""

from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from app.core.jsonl_tail import repair_jsonl_tail
from app.domain.tools import ToolCallRecord


@contextmanager
def record_index(
    path: Path, parse: Callable[[object], ToolCallRecord],
) -> Iterator[sqlite3.Connection]:
    # Caller holds the same lock used by JSONL append and tail repair.
    repair_jsonl_tail(path, parse)
    with closing(sqlite3.connect(path.with_name("records-index.sqlite3"))) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("""CREATE TABLE IF NOT EXISTS source (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            inode TEXT NOT NULL, size INTEGER NOT NULL, modified INTEGER NOT NULL,
            generation TEXT NOT NULL, line_count INTEGER NOT NULL
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS records (
            position INTEGER PRIMARY KEY, length INTEGER NOT NULL,
            record_id TEXT NOT NULL UNIQUE, tool_project_id TEXT NOT NULL,
            tool_name TEXT NOT NULL, call_id TEXT NOT NULL,
            source_project_id TEXT, session_id TEXT, ok INTEGER NOT NULL,
            created_at TEXT NOT NULL, elapsed_ms INTEGER, dynamic INTEGER
        )""")
        connection.execute("""CREATE INDEX IF NOT EXISTS records_order
            ON records(created_at DESC, position ASC)""")
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            _synchronize(connection, path, parse)
        yield connection


def _synchronize(connection: sqlite3.Connection, path: Path, parse) -> None:
    stat = path.stat()
    signature = (str(stat.st_ino), stat.st_size, stat.st_mtime_ns)
    previous = connection.execute("SELECT * FROM source WHERE singleton = 1").fetchone()
    if previous and signature == (previous["inode"], previous["size"], previous["modified"]):
        return
    append_only = previous is not None and previous["inode"] == str(stat.st_ino) and previous["size"] < stat.st_size
    offset = previous["size"] if append_only else 0
    line_count = previous["line_count"] if append_only else 0
    generation = previous["generation"] if append_only else uuid4().hex
    if not append_only:
        connection.execute("DELETE FROM records")
    with path.open("rb") as stream:
        stream.seek(offset)
        while line := stream.readline():
            position = offset
            offset += len(line)
            line_count += 1
            if not line.strip():
                continue
            try:
                record = parse(json.loads(line))
                connection.execute(
                    "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (position, len(line), record.record_id, record.tool_project_id,
                     record.tool_name, record.call_id, record.source_project_id,
                     record.session_id, record.ok, record.created_at,
                     record.elapsed_ms, record.dynamic),
                )
            except (TypeError, ValueError, KeyError, sqlite3.IntegrityError) as exc:
                raise ValueError(f"工具调用记录损坏：{path} 第 {line_count} 行。") from exc
    current = path.stat()
    if signature != (str(current.st_ino), current.st_size, current.st_mtime_ns):
        raise ValueError("工具调用记录在读取期间发生变化，请刷新重试。")
    connection.execute(
        "INSERT OR REPLACE INTO source VALUES (1, ?, ?, ?, ?, ?)",
        (*signature, generation, line_count),
    )
