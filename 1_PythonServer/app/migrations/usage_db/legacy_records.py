"""Legacy JSONL format decoding only; live usage is stored in usage.db."""
from app.domain.llm.usage import LlmUsageRecord

USAGE_EVENTS_FILE = "usage_records.jsonl"


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
            request_id=_optional_str(payload.get("request_id")),
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
