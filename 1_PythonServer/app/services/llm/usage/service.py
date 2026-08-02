from functools import lru_cache

from app.domain.llm.chat import ChatUsage
from app.domain.llm.usage import (
    LlmProviderModelUsageSummary,
    LlmProviderUsageSummary,
    LlmSessionUsageSummary,
    LlmUsageRecord,
    LlmUsageSummary,
)
from app.repositories.llm.provider_catalog_repository import (
    ProviderCatalogRepository,
    get_provider_catalog_repository,
)
from app.repositories.llm.provider_custom_model_repository import (
    ProviderCustomModelRepository,
    get_provider_custom_model_repository,
)
from app.repositories.llm.usage_repository import LlmUsageRepository, get_llm_usage_repository
from app.repositories.project.project_repository import ProjectRepository, get_project_repository
from app.core.errors import NotFoundError


class LlmUsageService:
    def __init__(
        self,
        repository: LlmUsageRepository,
        project_repository: ProjectRepository,
        provider_catalog_repository: ProviderCatalogRepository,
        provider_custom_model_repository: ProviderCustomModelRepository,
    ) -> None:
        self._repository = repository
        self._project_repository = project_repository
        self._provider_catalog_repository = provider_catalog_repository
        self._provider_custom_model_repository = provider_custom_model_repository

    def record_message_usage(
        self,
        *,
        project_id: str | None,
        session_id: str | None,
        message_id: str | None,
        provider_id: str,
        model_id: str,
        usage: ChatUsage,
        usage_feature_key: str = "main_chat",
    ) -> LlmUsageRecord:
        cost_amount, cost_currency = self._calculate_usage_cost(
            provider_id=provider_id,
            model_id=model_id,
            usage=usage,
        )
        return self._repository.record_usage(
            project_id=project_id,
            session_id=session_id,
            message_id=message_id,
            provider_id=provider_id,
            model_id=model_id,
            usage_feature_key=usage_feature_key,
            usage=usage,
            cost_amount=cost_amount,
            cost_currency=cost_currency,
            is_estimated=bool(usage.estimated_fields),
        )

    def get_session_summary(self, *, project_id: str, session_id: str) -> LlmSessionUsageSummary:
        self._ensure_project(project_id)
        summary = self._repository.get_session_summary(project_id=project_id, session_id=session_id)
        provider_names = {
            entry.provider_id: entry.display_name
            for entry in self._provider_catalog_repository.list_entries()
        }
        return LlmSessionUsageSummary(
            total=summary.total,
            by_models=tuple(
                _attach_provider_display_name(model_summary, provider_names)
                for model_summary in summary.by_models
            ),
        )

    def get_session_totals(
        self,
        *,
        project_id: str,
        session_ids: tuple[str, ...],
    ) -> dict[str, LlmUsageSummary]:
        self._ensure_project(project_id)
        return self._repository.get_session_totals(
            project_id=project_id,
            session_ids=session_ids,
        )

    def get_provider_model_summary(
        self,
        *,
        provider_id: str | None = None,
    ) -> LlmProviderModelUsageSummary:
        provider_names = {
            entry.provider_id: entry.display_name
            for entry in self._provider_catalog_repository.list_entries()
        }
        models = self._provider_custom_model_repository.list_all_models()
        if provider_id is not None:
            models = tuple(model for model in models if model.provider_id == provider_id)

        summaries_by_model = {
            (summary.provider_id, summary.model_id): _attach_provider_display_name(
                summary,
                provider_names,
            )
            for summary in self._repository.get_model_summaries(provider_id=provider_id)
        }
        provider_model_groups: dict[str, list[LlmUsageSummary]] = {}
        seen_model_keys: set[tuple[str | None, str | None]] = set()
        for model in models:
            summary = summaries_by_model.get(
                (model.provider_id, model.model_id),
                _empty_model_summary(
                    provider_id=model.provider_id,
                    provider_display_name=provider_names.get(model.provider_id)
                    or model.provider_id,
                    model_id=model.model_id,
                    cost_currency=model.price_currency,
                ),
            )
            seen_model_keys.add((summary.provider_id, summary.model_id))
            provider_model_groups.setdefault(model.provider_id, []).append(summary)

        for model_key, summary in summaries_by_model.items():
            if model_key in seen_model_keys:
                continue
            current_provider_id = summary.provider_id or "unknown"
            provider_model_groups.setdefault(current_provider_id, []).append(summary)

        providers = tuple(
            _build_provider_summary(
                provider_id=current_provider_id,
                provider_display_name=provider_names.get(current_provider_id)
                or current_provider_id,
                model_summaries=tuple(model_summaries),
            )
            for current_provider_id, model_summaries in sorted(provider_model_groups.items())
        )
        return LlmProviderModelUsageSummary(providers=providers)

    def _ensure_project(self, project_id: str) -> None:
        if self._project_repository.get_project(project_id) is None:
            raise NotFoundError(f"项目 '{project_id}' 不存在。")

    def _calculate_usage_cost(
        self,
        *,
        provider_id: str,
        model_id: str,
        usage: ChatUsage,
    ) -> tuple[float | None, str | None]:
        model = self._provider_custom_model_repository.get_model(
            provider_id=provider_id,
            model_id=model_id,
        )
        if model is None:
            return None, None

        prompt_tokens = usage.prompt_tokens or 0
        cache_hit_tokens = usage.prompt_cache_hit_tokens or 0
        if cache_hit_tokens > 0 or (usage.prompt_cache_miss_tokens or 0) > 0:
            cache_miss_tokens = usage.prompt_cache_miss_tokens or 0
        else:
            cache_miss_tokens = prompt_tokens

        completion_tokens = usage.completion_tokens or 0
        cost_amount = (
            cache_miss_tokens * (model.input_price_per_million or 0)
            + cache_hit_tokens * (model.cache_hit_price_per_million or 0)
            + completion_tokens * (model.output_price_per_million or 0)
        ) / 1_000_000
        return cost_amount, model.price_currency


@lru_cache
def get_llm_usage_service() -> LlmUsageService:
    return LlmUsageService(
        get_llm_usage_repository(),
        get_project_repository(),
        get_provider_catalog_repository(),
        get_provider_custom_model_repository(),
    )


def _attach_provider_display_name(
    summary: LlmUsageSummary,
    provider_names: dict[str, str],
) -> LlmUsageSummary:
    if summary.provider_id is None:
        return summary
    return LlmUsageSummary(
        provider_id=summary.provider_id,
        provider_display_name=provider_names.get(summary.provider_id) or summary.provider_id,
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
        by_features=tuple(
            _attach_provider_display_name(feature_summary, provider_names)
            for feature_summary in summary.by_features
        ),
    )


def _empty_model_summary(
    *,
    provider_id: str,
    provider_display_name: str,
    model_id: str,
    cost_currency: str,
) -> LlmUsageSummary:
    return LlmUsageSummary(
        provider_id=provider_id,
        provider_display_name=provider_display_name,
        model_id=model_id,
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        reasoning_tokens=0,
        prompt_cache_hit_tokens=0,
        prompt_cache_miss_tokens=0,
        cost_amount=0,
        cost_currency=cost_currency,
        record_count=0,
        estimated_record_count=0,
    )


def _build_provider_summary(
    *,
    provider_id: str,
    provider_display_name: str,
    model_summaries: tuple[LlmUsageSummary, ...],
) -> LlmProviderUsageSummary:
    cost_amount, cost_currency = _sum_costs(model_summaries)
    return LlmProviderUsageSummary(
        provider_id=provider_id,
        provider_display_name=provider_display_name,
        prompt_tokens=sum(summary.prompt_tokens for summary in model_summaries),
        completion_tokens=sum(summary.completion_tokens for summary in model_summaries),
        total_tokens=sum(summary.total_tokens for summary in model_summaries),
        reasoning_tokens=sum(summary.reasoning_tokens for summary in model_summaries),
        prompt_cache_hit_tokens=sum(
            summary.prompt_cache_hit_tokens for summary in model_summaries
        ),
        prompt_cache_miss_tokens=sum(
            summary.prompt_cache_miss_tokens for summary in model_summaries
        ),
        cost_amount=cost_amount,
        cost_currency=cost_currency,
        record_count=sum(summary.record_count for summary in model_summaries),
        estimated_record_count=sum(
            summary.estimated_record_count for summary in model_summaries
        ),
        by_models=model_summaries,
    )


def _sum_costs(summaries: tuple[LlmUsageSummary, ...]) -> tuple[float | None, str | None]:
    if not summaries:
        return 0, None

    priced_summaries = tuple(summary for summary in summaries if summary.record_count > 0)
    if not priced_summaries:
        return 0, summaries[0].cost_currency

    cost_currency: str | None = None
    total = 0.0
    for summary in priced_summaries:
        if summary.cost_amount is None:
            return None, None
        if cost_currency is None:
            cost_currency = summary.cost_currency
        elif summary.cost_currency != cost_currency:
            return None, None
        total += summary.cost_amount
    return total, cost_currency
