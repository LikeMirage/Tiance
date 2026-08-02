# LLM 模型目录 Pydantic 模型
# 前端模型选择器的统一列表响应

from pydantic import BaseModel, Field

from app.domain.llm.model_catalog import LlmModelCatalogEntry


class LlmModelCatalogEntryResponse(BaseModel):
    provider_id: str
    provider_label: str
    provider_enabled: bool
    protocol_family: str
    model_id: str
    model_label: str
    family_group: str
    capability_tags: list[str] = Field(default_factory=list)
    source: str
    price_currency: str = "CNY"
    input_price_per_million: float | None = None
    cache_hit_price_per_million: float | None = None
    output_price_per_million: float | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_domain(cls, model: LlmModelCatalogEntry) -> "LlmModelCatalogEntryResponse":
        return cls(
            provider_id=model.provider_id,
            provider_label=model.provider_label,
            provider_enabled=model.provider_enabled,
            protocol_family=model.protocol_family,
            model_id=model.model_id,
            model_label=model.model_label,
            family_group=model.family_group,
            capability_tags=list(model.capability_tags),
            source=model.source,
            price_currency=model.price_currency,
            input_price_per_million=model.input_price_per_million,
            cache_hit_price_per_million=model.cache_hit_price_per_million,
            output_price_per_million=model.output_price_per_million,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class LlmModelCatalogListResponse(BaseModel):
    count: int
    items: list[LlmModelCatalogEntryResponse] = Field(default_factory=list)
