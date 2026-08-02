from __future__ import annotations

from dataclasses import asdict, replace
from json import JSONDecodeError, dumps, loads
import os
from pathlib import Path
from threading import RLock
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.domain.llm.usage import LlmUsageRecord


USAGE_EVENTS_FILE = "usage_records.jsonl"
_EVENT_VERSION = 1


class UsageFileStore:
    """Append-only usage facts whose summaries can be rebuilt by replaying the file."""

    def __init__(self, root_path: Path) -> None:
        self.root_path = root_path
        self.events_path = root_path / USAGE_EVENTS_FILE
        self._lock = RLock()
        self._records_cache: dict[str, LlmUsageRecord] | None = None
        self._message_usage_ids_cache: dict[str, str] | None = None

    def list_records(self) -> tuple[LlmUsageRecord, ...]:
        with self._lock:
            records, _ = self._ensure_cache_unlocked()
            return tuple(records.values())

    def append_upsert(self, record: LlmUsageRecord) -> None:
        event = {"version": _EVENT_VERSION, "operation": "upsert", "record": asdict(record)}
        with self._lock:
            records, message_usage_ids = self._ensure_cache_unlocked()
            self._append_event_unlocked(event)
            _apply_upsert(records, message_usage_ids, record)

    def append_delete_model(self, *, provider_id: str, model_id: str) -> None:
        event = {
            "version": _EVENT_VERSION,
            "operation": "delete_model",
            "provider_id": provider_id,
            "model_id": model_id,
        }
        with self._lock:
            records, message_usage_ids = self._ensure_cache_unlocked()
            self._append_event_unlocked(event)
            _apply_model_delete(records, message_usage_ids, provider_id, model_id)

    def replace_records(self, records: tuple[LlmUsageRecord, ...]) -> None:
        content = "".join(
            dumps(
                {"version": _EVENT_VERSION, "operation": "upsert", "record": asdict(record)},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
            for record in records
        )
        with self._lock:
            self.root_path.mkdir(parents=True, exist_ok=True)
            temporary_path = self.events_path.with_name(
                f".{self.events_path.name}.{uuid4().hex}.tmp"
            )
            try:
                with temporary_path.open("w", encoding="utf-8") as output:
                    output.write(content)
                    output.flush()
                    os.fsync(output.fileno())
                atomic_replace_path(temporary_path, self.events_path)
                records_cache: dict[str, LlmUsageRecord] = {}
                message_usage_ids_cache: dict[str, str] = {}
                for record in records:
                    _apply_upsert(records_cache, message_usage_ids_cache, record)
                self._records_cache = records_cache
                self._message_usage_ids_cache = message_usage_ids_cache
            finally:
                temporary_path.unlink(missing_ok=True)

    def _append_event_unlocked(self, event: dict[str, object]) -> None:
        encoded = dumps(event, ensure_ascii=False, separators=(",", ":"))
        self.root_path.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as output:
            output.write(encoded)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())

    def _ensure_cache_unlocked(
        self,
    ) -> tuple[dict[str, LlmUsageRecord], dict[str, str]]:
        if self._records_cache is None or self._message_usage_ids_cache is None:
            self._records_cache, self._message_usage_ids_cache = self._replay_unlocked()
        return self._records_cache, self._message_usage_ids_cache

    def _replay_unlocked(self) -> tuple[dict[str, LlmUsageRecord], dict[str, str]]:
        records: dict[str, LlmUsageRecord] = {}
        message_usage_ids: dict[str, str] = {}
        if not self.events_path.is_file():
            return records, message_usage_ids

        with self.events_path.open("r", encoding="utf-8") as source:
            for line_number, raw_line in enumerate(source, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = loads(line)
                except JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid usage event JSON at line {line_number}."
                    ) from exc
                if not isinstance(event, dict) or event.get("version") != _EVENT_VERSION:
                    raise ValueError(f"Invalid usage event at line {line_number}.")
                operation = event.get("operation")
                if operation == "upsert":
                    record = _record_from_payload(event.get("record"), line_number=line_number)
                    _apply_upsert(records, message_usage_ids, record)
                    continue
                if operation == "delete_model":
                    provider_id = event.get("provider_id")
                    model_id = event.get("model_id")
                    if not isinstance(provider_id, str) or not isinstance(model_id, str):
                        raise ValueError(f"Invalid usage delete event at line {line_number}.")
                    _apply_model_delete(records, message_usage_ids, provider_id, model_id)
                    continue
                raise ValueError(f"Unknown usage event operation at line {line_number}.")
        return records, message_usage_ids


def _apply_upsert(
    records: dict[str, LlmUsageRecord],
    message_usage_ids: dict[str, str],
    incoming: LlmUsageRecord,
) -> None:
    existing_usage_id = (
        message_usage_ids.get(incoming.message_id) if incoming.message_id is not None else None
    )
    if existing_usage_id is None:
        records[incoming.usage_id] = incoming
        if incoming.message_id is not None:
            message_usage_ids[incoming.message_id] = incoming.usage_id
        return

    existing = records[existing_usage_id]
    records[existing_usage_id] = replace(
        existing,
        provider_id=incoming.provider_id,
        model_id=incoming.model_id,
        usage_feature_key=incoming.usage_feature_key,
        prompt_tokens=incoming.prompt_tokens,
        completion_tokens=incoming.completion_tokens,
        total_tokens=incoming.total_tokens,
        reasoning_tokens=incoming.reasoning_tokens,
        prompt_cache_hit_tokens=incoming.prompt_cache_hit_tokens,
        prompt_cache_miss_tokens=incoming.prompt_cache_miss_tokens,
        cost_amount=incoming.cost_amount,
        cost_currency=incoming.cost_currency,
        is_estimated=incoming.is_estimated,
    )


def _apply_model_delete(
    records: dict[str, LlmUsageRecord],
    message_usage_ids: dict[str, str],
    provider_id: str,
    model_id: str,
) -> None:
    deleted_ids = tuple(
        usage_id
        for usage_id, record in records.items()
        if record.provider_id == provider_id and record.model_id == model_id
    )
    for usage_id in deleted_ids:
        record = records.pop(usage_id)
        if record.message_id is not None:
            message_usage_ids.pop(record.message_id, None)


def _record_from_payload(payload: object, *, line_number: int) -> LlmUsageRecord:
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid usage record at line {line_number}.")
    try:
        return LlmUsageRecord(
            usage_id=_required_str(payload, "usage_id"),
            project_id=_optional_str(payload.get("project_id")),
            session_id=_optional_str(payload.get("session_id")),
            message_id=_optional_str(payload.get("message_id")),
            provider_id=_required_str(payload, "provider_id"),
            model_id=_required_str(payload, "model_id"),
            usage_feature_key=_required_str(payload, "usage_feature_key"),
            prompt_tokens=_int_value(payload.get("prompt_tokens")),
            completion_tokens=_int_value(payload.get("completion_tokens")),
            total_tokens=_int_value(payload.get("total_tokens")),
            reasoning_tokens=_int_value(payload.get("reasoning_tokens")),
            prompt_cache_hit_tokens=_int_value(payload.get("prompt_cache_hit_tokens")),
            prompt_cache_miss_tokens=_int_value(payload.get("prompt_cache_miss_tokens")),
            cost_amount=_optional_float(payload.get("cost_amount")),
            cost_currency=_optional_str(payload.get("cost_currency")),
            is_estimated=bool(payload.get("is_estimated")),
            created_at=_required_str(payload, "created_at"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid usage record at line {line_number}.") from exc


def _required_str(payload: dict[object, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Missing required string field: {key}")
    return value


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _int_value(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a token count.")
    return int(value or 0)


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)
