from pydantic import BaseModel, Field

from app.domain.llm.usage import (
    LlmProviderModelUsageSummary,
    LlmProviderUsageSummary,
    LlmSessionUsageSummary,
    LlmUsageSummary,
)


class LlmUsageSummaryResponse(BaseModel):
    provider_id: str | None = None
    provider_display_name: str | None = None
    model_id: str | None = None
    usage_feature_key: str | None = None
    usage_feature_display_name: str | None = None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    reasoning_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    cost_amount: float | None = None
    cost_currency: str | None = None
    record_count: int
    estimated_record_count: int = 0
    by_features: list["LlmUsageSummaryResponse"] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, summary: LlmUsageSummary) -> "LlmUsageSummaryResponse":
        return cls(
            provider_id=summary.provider_id,
            provider_display_name=summary.provider_display_name,
            model_id=summary.model_id,
            usage_feature_key=summary.usage_feature_key,
            usage_feature_display_name=summary.usage_feature_display_name,
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
            by_features=[
                LlmUsageSummaryResponse.from_domain(feature_summary)
                for feature_summary in summary.by_features
            ],
        )


class LlmSessionUsageSummaryResponse(BaseModel):
    provider_id: str | None = None
    provider_display_name: str | None = None
    model_id: str | None = None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    reasoning_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    cost_amount: float | None = None
    cost_currency: str | None = None
    record_count: int
    estimated_record_count: int = 0
    by_models: list[LlmUsageSummaryResponse]

    @classmethod
    def from_domain(cls, summary: LlmSessionUsageSummary) -> "LlmSessionUsageSummaryResponse":
        total = summary.total
        return cls(
            provider_id=total.provider_id,
            provider_display_name=total.provider_display_name,
            model_id=total.model_id,
            prompt_tokens=total.prompt_tokens,
            completion_tokens=total.completion_tokens,
            total_tokens=total.total_tokens,
            reasoning_tokens=total.reasoning_tokens,
            prompt_cache_hit_tokens=total.prompt_cache_hit_tokens,
            prompt_cache_miss_tokens=total.prompt_cache_miss_tokens,
            cost_amount=total.cost_amount,
            cost_currency=total.cost_currency,
            record_count=total.record_count,
            estimated_record_count=total.estimated_record_count,
            by_models=[
                LlmUsageSummaryResponse.from_domain(model_summary)
                for model_summary in summary.by_models
            ],
        )


class LlmProviderUsageSummaryResponse(BaseModel):
    provider_id: str
    provider_display_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    reasoning_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    cost_amount: float | None = None
    cost_currency: str | None = None
    record_count: int
    estimated_record_count: int = 0
    by_models: list[LlmUsageSummaryResponse]

    @classmethod
    def from_domain(cls, summary: LlmProviderUsageSummary) -> "LlmProviderUsageSummaryResponse":
        return cls(
            provider_id=summary.provider_id,
            provider_display_name=summary.provider_display_name,
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
            by_models=[
                LlmUsageSummaryResponse.from_domain(model_summary)
                for model_summary in summary.by_models
            ],
        )


class LlmProviderModelUsageSummaryResponse(BaseModel):
    providers: list[LlmProviderUsageSummaryResponse]

    @classmethod
    def from_domain(
        cls,
        summary: LlmProviderModelUsageSummary,
    ) -> "LlmProviderModelUsageSummaryResponse":
        return cls(
            providers=[
                LlmProviderUsageSummaryResponse.from_domain(provider_summary)
                for provider_summary in summary.providers
            ],
        )
