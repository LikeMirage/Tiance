from collections import defaultdict
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from app.core.config import get_settings
from app.domain.llm.chat import ChatUsage
from app.domain.llm.usage import LlmSessionUsageSummary, LlmUsageRecord, LlmUsageSummary
from app.repositories.llm.usage_file_store import UsageFileStore


class LlmUsageRepository:
    def __init__(self, usage_data_path: Path) -> None:
        self._store = UsageFileStore(usage_data_path)

    def record_usage(
        self,
        *,
        project_id: str | None,
        session_id: str | None,
        message_id: str | None,
        provider_id: str,
        model_id: str,
        usage_feature_key: str = "main_chat",
        usage: ChatUsage,
        cost_amount: float | None = None,
        cost_currency: str | None = None,
        is_estimated: bool = False,
    ) -> LlmUsageRecord:
        record = LlmUsageRecord(
            usage_id=f"usage_{uuid4().hex[:16]}",
            project_id=project_id,
            session_id=session_id,
            message_id=message_id,
            provider_id=provider_id,
            model_id=model_id,
            usage_feature_key=_normalize_usage_feature_key(usage_feature_key),
            prompt_tokens=_token_value(usage.prompt_tokens),
            completion_tokens=_token_value(usage.completion_tokens),
            total_tokens=_token_value(usage.total_tokens),
            reasoning_tokens=_token_value(usage.reasoning_tokens),
            prompt_cache_hit_tokens=_token_value(usage.prompt_cache_hit_tokens),
            prompt_cache_miss_tokens=_token_value(usage.prompt_cache_miss_tokens),
            cost_amount=cost_amount,
            cost_currency=cost_currency,
            is_estimated=is_estimated,
            created_at=_utc_now(),
        )
        self._store.append_upsert(record)
        return record

    def delete_model_usage(self, *, provider_id: str, model_id: str) -> None:
        self._store.append_delete_model(provider_id=provider_id, model_id=model_id)

    def get_model_summaries(
        self,
        *,
        provider_id: str | None = None,
    ) -> tuple[LlmUsageSummary, ...]:
        records = tuple(
            record
            for record in self._store.list_records()
            if provider_id is None or record.provider_id == provider_id
        )
        model_groups = _group_records(records, lambda record: (record.provider_id, record.model_id))
        feature_groups = _group_records(
            records,
            lambda record: (record.provider_id, record.model_id, record.usage_feature_key),
        )

        features_by_model: dict[tuple[str, str], list[LlmUsageSummary]] = defaultdict(list)
        for (current_provider_id, model_id, feature_key), grouped_records in _ordered_groups(
            feature_groups,
            prefix_key=lambda key: (key[0], key[1]),
        ):
            features_by_model[(current_provider_id, model_id)].append(
                _summarize(
                    grouped_records,
                    provider_id=current_provider_id,
                    model_id=model_id,
                    usage_feature_key=feature_key,
                )
            )

        summaries: list[LlmUsageSummary] = []
        for (current_provider_id, model_id), grouped_records in _ordered_groups(
            model_groups,
            prefix_key=lambda key: (key[0],),
        ):
            summary = _summarize(
                grouped_records,
                provider_id=current_provider_id,
                model_id=model_id,
            )
            summaries.append(
                _summary_with_features(
                    summary,
                    tuple(features_by_model.get((current_provider_id, model_id), ())),
                )
            )
        return tuple(summaries)

    def get_session_summary(self, *, project_id: str, session_id: str) -> LlmSessionUsageSummary:
        records = tuple(
            record
            for record in self._store.list_records()
            if record.project_id == project_id and record.session_id == session_id
        )
        model_feature_groups = _group_records(
            records,
            lambda record: (record.provider_id, record.model_id, record.usage_feature_key),
        )
        return LlmSessionUsageSummary(
            total=_summarize(records),
            by_models=tuple(
                _summarize(
                    grouped_records,
                    provider_id=key[0],
                    model_id=key[1],
                    usage_feature_key=key[2],
                )
                for key, grouped_records in _ordered_groups(model_feature_groups)
            ),
        )

    def get_session_totals(
        self,
        *,
        project_id: str,
        session_ids: tuple[str, ...],
    ) -> dict[str, LlmUsageSummary]:
        if not session_ids:
            return {}
        requested_ids = set(session_ids)
        groups = _group_records(
            tuple(
                record
                for record in self._store.list_records()
                if record.project_id == project_id and record.session_id in requested_ids
            ),
            lambda record: record.session_id,
        )
        return {
            session_id: _summarize(records)
            for session_id, records in groups.items()
            if session_id is not None
        }


def _group_records(records, key_factory):
    groups = defaultdict(list)
    for record in records:
        groups[key_factory(record)].append(record)
    return groups


def _ordered_groups(groups, *, prefix_key=None):
    ordered = list(groups.items())
    ordered.sort(key=lambda item: _latest_created_at(item[1]), reverse=True)
    if prefix_key is not None:
        ordered.sort(key=lambda item: prefix_key(item[0]))
    return ordered


def _latest_created_at(records: list[LlmUsageRecord]) -> str:
    return max((record.created_at for record in records), default="")


def _summarize(
    records,
    *,
    provider_id: str | None = None,
    model_id: str | None = None,
    usage_feature_key: str | None = None,
) -> LlmUsageSummary:
    records = tuple(records)
    currencies = {record.cost_currency for record in records if record.cost_currency is not None}
    has_single_currency = bool(records) and len(currencies) <= 1
    feature_key = (
        _normalize_usage_feature_key(usage_feature_key) if usage_feature_key is not None else None
    )
    return LlmUsageSummary(
        provider_id=provider_id,
        provider_display_name=None,
        model_id=model_id,
        prompt_tokens=sum(record.prompt_tokens for record in records),
        completion_tokens=sum(record.completion_tokens for record in records),
        total_tokens=sum(record.total_tokens for record in records),
        reasoning_tokens=sum(record.reasoning_tokens for record in records),
        prompt_cache_hit_tokens=sum(record.prompt_cache_hit_tokens for record in records),
        prompt_cache_miss_tokens=sum(record.prompt_cache_miss_tokens for record in records),
        cost_amount=(
            sum(record.cost_amount or 0 for record in records) if has_single_currency else None
        ),
        cost_currency=next(iter(currencies), None) if has_single_currency else None,
        record_count=len(records),
        estimated_record_count=sum(1 for record in records if record.is_estimated),
        usage_feature_key=feature_key,
        usage_feature_display_name=(
            _usage_feature_display_name(feature_key) if feature_key is not None else None
        ),
    )


def _summary_with_features(
    summary: LlmUsageSummary,
    features: tuple[LlmUsageSummary, ...],
) -> LlmUsageSummary:
    return LlmUsageSummary(
        provider_id=summary.provider_id,
        provider_display_name=summary.provider_display_name,
        model_id=summary.model_id,
        prompt_tokens=summary.prompt_tokens,
        completion_tokens=summary.completion_tokens,
        total_tokens=summary.total_tokens,
        reasoning_tokens=summary.reasoning_tokens,
        prompt_cache_hit_tokens=summary.prompt_cache_hit_tokens,
        prompt_cache_miss_tokens=summary.prompt_cache_miss_tokens,
        cost_amount=summary.cost_amount,
        cost_currency=summary.cost_currency,
        record_count=summary.record_count,
        estimated_record_count=summary.estimated_record_count,
        usage_feature_key=summary.usage_feature_key,
        usage_feature_display_name=summary.usage_feature_display_name,
        by_features=features,
    )


def _token_value(value: int | None) -> int:
    return value if isinstance(value, int) else 0


def _normalize_usage_feature_key(value: str | None) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if normalized in {
        "conversation_naming",
        "global_memory_management",
        "memory_compression",
        "project_memory_management",
        "provider_web_search",
    }:
        return normalized
    return "main_chat"


def _usage_feature_display_name(value: str) -> str:
    names = {
        "conversation_naming": "会话命名模型",
        "global_memory_management": "全局记忆管理模型",
        "memory_compression": "记忆压缩模型",
        "project_memory_management": "项目记忆管理模型",
        "provider_web_search": "内置网络搜索",
    }
    return names.get(value, "主会话")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@lru_cache
def get_llm_usage_repository() -> LlmUsageRepository:
    return LlmUsageRepository(get_settings().usage_data_path)
