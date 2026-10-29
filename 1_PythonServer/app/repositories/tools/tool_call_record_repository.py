from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
import json
import os
from pathlib import Path
from threading import RLock
from uuid import uuid4
from dataclasses import dataclass

from app.core.jsonl_tail import repair_jsonl_tail
from app.domain.tools import ToolCallRecord, ToolCallRecordDraft
from app.domain.tools.call_record_page import (
    ToolCallRecordListItem, ToolCallRecordPage, ToolCallRecordSnapshotExpired,
)
from app.repositories.tools.tool_call_record_index import record_index


_RECORDS_RELATIVE_PATH = Path(".Tiance") / "tool-calls" / "records.jsonl"


@dataclass(frozen=True)
class ToolCallStatistic:
    tool_name: str
    created_at: str
    ok: bool


@dataclass
class _StatisticsCache:
    signature: tuple[int, int, int]
    rows: list[ToolCallStatistic]


class ToolCallRecordRepository:
    """Persist each tool project's calls inside that project directory."""

    def __init__(self) -> None:
        self._write_lock = RLock()
        self._statistics_cache: dict[Path, _StatisticsCache] = {}

    def list_statistics(self, project_roots: tuple[str, ...]) -> tuple[ToolCallStatistic, ...]:
        paths = {self.records_path(root) for root in project_roots}
        with self._write_lock:
            for removed in self._statistics_cache.keys() - paths:
                self._statistics_cache.pop(removed, None)
            return tuple(row for path in paths for row in self._statistics_rows(path))

    def _statistics_rows(self, path: Path) -> list[ToolCallStatistic]:
        if not path.is_file():
            self._statistics_cache.pop(path, None)
            return []
        repair_jsonl_tail(path, _payload_to_record)
        stat = path.stat()
        signature = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
        cached = self._statistics_cache.get(path)
        if cached and cached.signature == signature:
            return cached.rows
        # Tool logs are append-only. Replaced/truncated files rebuild this disposable cache.
        append_only = cached is not None and cached.signature[0] == stat.st_ino and cached.signature[1] < stat.st_size
        offset = cached.signature[1] if append_only else 0
        added: list[ToolCallStatistic] = []
        with path.open("rb") as stream:
            stream.seek(offset)
            for line in stream:
                if line.strip():
                    record = _payload_to_record(json.loads(line))
                    added.append(ToolCallStatistic(record.tool_name, record.created_at, record.ok))
        rows = cached.rows if append_only else []
        rows.extend(added)
        self._statistics_cache[path] = _StatisticsCache(signature, rows)
        return rows

    def append(self, project_root: str | Path, draft: ToolCallRecordDraft) -> ToolCallRecord:
        record = ToolCallRecord(
            record_id=f"tool_call_{uuid4().hex}",
            tool_project_id=draft.tool_project_id,
            tool_name=draft.tool_name,
            call_id=draft.call_id,
            source_project_id=draft.source_project_id,
            source_project_name="",
            session_id=draft.session_id,
            session_title="",
            arguments_text=draft.arguments_text,
            result_text=draft.result_text,
            ok=draft.ok,
            error=draft.error,
            created_at=datetime.now(UTC).isoformat(),
            elapsed_ms=draft.elapsed_ms,
            dynamic=draft.dynamic,
        )
        records_path = self.records_path(project_root)
        serialized = json.dumps(_record_to_payload(record), ensure_ascii=False, separators=(",", ":"))
        with self._write_lock:
            records_path.parent.mkdir(parents=True, exist_ok=True)
            repair_jsonl_tail(records_path, _payload_to_record)
            with records_path.open("ab") as stream:
                stream.write((serialized + "\n").encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
        return record

    def list_project_records(self, project_root: str | Path) -> tuple[ToolCallRecord, ...]:
        records_path = self.records_path(project_root)
        with self._write_lock:
            repair_jsonl_tail(records_path, _payload_to_record)
            return self._read_records(records_path)

    def list_project_page(
        self, project_root: str | Path, *, limit: int = 50, offset: int = 0,
        snapshot: str | None = None,
    ) -> ToolCallRecordPage:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("调用记录分页参数无效。")
        path = self.records_path(project_root)
        with self._write_lock:
            if not path.is_file():
                if snapshot:
                    raise ToolCallRecordSnapshotExpired("调用记录已变化，请刷新列表。")
                return ToolCallRecordPage((), 0, offset, limit, None)
            with record_index(path, _payload_to_record) as connection:
                generation = connection.execute("SELECT generation FROM source").fetchone()[0]
                boundary = connection.execute("SELECT COALESCE(MAX(position), -1) FROM records").fetchone()[0]
                if snapshot is not None:
                    try:
                        token, raw_boundary = snapshot.split(":")
                        requested_boundary = int(raw_boundary)
                    except (ValueError, TypeError) as exc:
                        raise ValueError("调用记录分页快照无效。") from exc
                    if token != generation or not -1 <= requested_boundary <= boundary:
                        raise ToolCallRecordSnapshotExpired("调用记录已变化，请刷新列表。")
                    boundary = requested_boundary
                count = connection.execute(
                    "SELECT COUNT(*) FROM records WHERE position <= ?", (boundary,),
                ).fetchone()[0]
                rows = connection.execute(
                    "SELECT * FROM records WHERE position <= ? "
                    "ORDER BY created_at DESC, position ASC LIMIT ? OFFSET ?",
                    (boundary, limit, offset),
                ).fetchall()
                items = tuple(ToolCallRecordListItem(
                    record_id=row["record_id"], tool_project_id=row["tool_project_id"],
                    tool_name=row["tool_name"], call_id=row["call_id"],
                    source_project_id=row["source_project_id"], source_project_name="",
                    session_id=row["session_id"], session_title="", ok=bool(row["ok"]),
                    created_at=row["created_at"], elapsed_ms=row["elapsed_ms"],
                    dynamic=None if row["dynamic"] is None else bool(row["dynamic"]),
                ) for row in rows)
                return ToolCallRecordPage(items, count, offset, limit, f"{generation}:{boundary}")

    def get_project_record(self, project_root: str | Path, record_id: str) -> ToolCallRecord | None:
        path = self.records_path(project_root)
        with self._write_lock:
            if not path.is_file():
                return None
            with record_index(path, _payload_to_record) as connection:
                row = connection.execute(
                    "SELECT position, length FROM records WHERE record_id = ?", (record_id,),
                ).fetchone()
                if row is None:
                    return None
                with path.open("rb") as stream:
                    stream.seek(row["position"])
                    record = _payload_to_record(json.loads(stream.read(row["length"])))
                if record.record_id != record_id:
                    raise ValueError("工具调用记录在读取期间发生变化，请刷新重试。")
                return record

    def _read_records(self, records_path: Path) -> tuple[ToolCallRecord, ...]:
        if not records_path.is_file():
            return ()
        records: list[ToolCallRecord] = []
        with records_path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    payload = json.loads(stripped)
                    records.append(_payload_to_record(payload))
                except (TypeError, ValueError, KeyError) as exc:
                    raise ValueError(
                        f"工具调用记录损坏：{records_path} 第 {line_number} 行。"
                    ) from exc
        records.sort(key=lambda item: item.created_at, reverse=True)
        return tuple(records)

    def list_all(self, project_roots: tuple[str, ...]) -> tuple[ToolCallRecord, ...]:
        records = [
            record
            for project_root in project_roots
            for record in self.list_project_records(project_root)
        ]
        records.sort(key=lambda item: item.created_at, reverse=True)
        return tuple(records)

    @staticmethod
    def records_path(project_root: str | Path) -> Path:
        return Path(project_root).resolve() / _RECORDS_RELATIVE_PATH


def _record_to_payload(record: ToolCallRecord) -> dict[str, object]:
    return {
        "record_id": record.record_id,
        "tool_project_id": record.tool_project_id,
        "tool_name": record.tool_name,
        "call_id": record.call_id,
        "source_project_id": record.source_project_id,
        "session_id": record.session_id,
        "arguments_text": record.arguments_text,
        "result_text": record.result_text,
        "ok": record.ok,
        "error": record.error,
        "elapsed_ms": record.elapsed_ms,
        "dynamic": record.dynamic,
        "created_at": record.created_at,
    }


def _payload_to_record(payload: object) -> ToolCallRecord:
    if not isinstance(payload, dict):
        raise ValueError("工具调用记录必须是 JSON 对象。")
    return ToolCallRecord(
        record_id=_required_string(payload, "record_id"),
        tool_project_id=_required_string(payload, "tool_project_id"),
        tool_name=_required_string(payload, "tool_name"),
        call_id=_required_string(payload, "call_id"),
        source_project_id=_optional_string(payload, "source_project_id"),
        source_project_name="",
        session_id=_optional_string(payload, "session_id"),
        session_title="",
        arguments_text=_required_string(payload, "arguments_text", allow_empty=True),
        result_text=_required_string(payload, "result_text", allow_empty=True),
        ok=_required_bool(payload, "ok"),
        error=_optional_string(payload, "error", allow_empty=True),
        elapsed_ms=_optional_int(payload, "elapsed_ms"),
        dynamic=_optional_bool(payload, "dynamic"),
        created_at=_required_string(payload, "created_at"),
    )


def _required_string(payload: dict[object, object], key: str, *, allow_empty: bool = False) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ValueError(f"字段 {key} 无效。")
    return value


def _optional_string(
    payload: dict[object, object],
    key: str,
    *,
    allow_empty: bool = False,
) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ValueError(f"字段 {key} 无效。")
    return value


def _required_bool(payload: dict[object, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"字段 {key} 无效。")
    return value


def _optional_bool(payload: dict[object, object], key: str) -> bool | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"字段 {key} 无效。")
    return value


def _optional_int(payload: dict[object, object], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"字段 {key} 无效。")
    return value


@lru_cache
def get_tool_call_record_repository() -> ToolCallRecordRepository:
    return ToolCallRecordRepository()
