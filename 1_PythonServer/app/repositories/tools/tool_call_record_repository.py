from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
import json
import os
from pathlib import Path
from threading import RLock
from uuid import uuid4

from app.domain.tools import ToolCallRecord, ToolCallRecordDraft


_RECORDS_RELATIVE_PATH = Path(".Tiance") / "tool-calls" / "records.jsonl"


class ToolCallRecordRepository:
    """Persist each tool project's calls inside that project directory."""

    def __init__(self) -> None:
        self._write_lock = RLock()

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
            with records_path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(serialized + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        return record

    def list_project_records(self, project_root: str | Path) -> tuple[ToolCallRecord, ...]:
        records_path = self.records_path(project_root)
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
