from pathlib import Path

from app.domain.llm.usage import LlmUsageRecord
from app.infra.database import database_connection
from app.repositories.llm.usage_file_store import UsageFileStore


def ensure_usage_file_storage(database_path: Path, usage_data_path: Path) -> None:
    """Export the legacy SQLite usage ledger before the tables are removed."""

    store = UsageFileStore(usage_data_path)
    if store.events_path.is_file() and store.events_path.stat().st_size > 0:
        store.list_records()
        return

    with database_connection(database_path) as connection:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'llm_usage_records'"
        ).fetchone()
        if table_exists is None:
            return
        rows = connection.execute(
            """
            SELECT
                usage_id, project_id, session_id, message_id,
                provider_id, model_id, usage_feature_key,
                prompt_tokens, completion_tokens, total_tokens, reasoning_tokens,
                prompt_cache_hit_tokens, prompt_cache_miss_tokens,
                cost_amount, cost_currency, is_estimated, created_at
            FROM llm_usage_records
            ORDER BY created_at, usage_id
            """
        ).fetchall()

    if not rows:
        return
    records = tuple(_row_to_record(row) for row in rows)
    store.replace_records(records)
    exported_ids = {record.usage_id for record in store.list_records()}
    source_ids = {record.usage_id for record in records}
    if exported_ids != source_ids:
        raise RuntimeError("Usage record export verification failed; SQLite tables were preserved.")


def _row_to_record(row) -> LlmUsageRecord:
    return LlmUsageRecord(
        usage_id=str(row["usage_id"]),
        project_id=_optional_str(row["project_id"]),
        session_id=_optional_str(row["session_id"]),
        message_id=_optional_str(row["message_id"]),
        provider_id=str(row["provider_id"]),
        model_id=str(row["model_id"]),
        usage_feature_key=str(row["usage_feature_key"] or "main_chat"),
        prompt_tokens=int(row["prompt_tokens"] or 0),
        completion_tokens=int(row["completion_tokens"] or 0),
        total_tokens=int(row["total_tokens"] or 0),
        reasoning_tokens=int(row["reasoning_tokens"] or 0),
        prompt_cache_hit_tokens=int(row["prompt_cache_hit_tokens"] or 0),
        prompt_cache_miss_tokens=int(row["prompt_cache_miss_tokens"] or 0),
        cost_amount=float(row["cost_amount"]) if row["cost_amount"] is not None else None,
        cost_currency=_optional_str(row["cost_currency"]),
        is_estimated=bool(row["is_estimated"]),
        created_at=str(row["created_at"]),
    )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None
