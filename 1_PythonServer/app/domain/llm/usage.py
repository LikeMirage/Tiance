from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LlmUsageRecord:
    usage_id: str
    project_id: str | None
    session_id: str | None
    message_id: str | None
    provider_id: str
    model_id: str
    usage_feature_key: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    reasoning_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    cost_amount: float | None
    cost_currency: str | None
    is_estimated: bool
    created_at: str


@dataclass(frozen=True, slots=True)
class LlmUsageSummary:
    provider_id: str | None
    provider_display_name: str | None
    model_id: str | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    reasoning_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    cost_amount: float | None
    cost_currency: str | None
    record_count: int
    estimated_record_count: int = 0
    usage_feature_key: str | None = None
    usage_feature_display_name: str | None = None
    by_features: tuple["LlmUsageSummary", ...] = ()


@dataclass(frozen=True, slots=True)
class LlmSessionUsageSummary:
    total: LlmUsageSummary
    by_models: tuple[LlmUsageSummary, ...]


@dataclass(frozen=True, slots=True)
class LlmProviderUsageSummary:
    provider_id: str
    provider_display_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    reasoning_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    cost_amount: float | None
    cost_currency: str | None
    record_count: int
    estimated_record_count: int
    by_models: tuple[LlmUsageSummary, ...]


@dataclass(frozen=True, slots=True)
class LlmProviderModelUsageSummary:
    providers: tuple[LlmProviderUsageSummary, ...]
