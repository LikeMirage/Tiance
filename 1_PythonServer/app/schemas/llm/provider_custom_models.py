# 自定义模型 Pydantic 模型
# 用户手动添加的模型：请求保存、响应序列化

from pydantic import BaseModel, Field

from app.domain.llm.provider_custom_model import ProviderCustomModel


class ProviderCustomModelSaveRequest(BaseModel):
    """自定义模型保存请求：模型 ID、显示名称、功能标签、定价"""

    model_id: str
    display_name: str = ""
    family_group: str = ""
    capability_tags: list[str] = Field(default_factory=list)
    note: str = ""
    price_currency: str = "CNY"
    input_price_per_million: float | None = Field(default=None, ge=0)
    cache_hit_price_per_million: float | None = Field(default=None, ge=0)
    output_price_per_million: float | None = Field(default=None, ge=0)


class ProviderCustomModelResponse(BaseModel):
    provider_id: str
    model_id: str
    display_name: str
    family_group: str
    capability_tags: list[str] = Field(default_factory=list)
    note: str = ""
    price_currency: str = "CNY"
    input_price_per_million: float | None = None
    cache_hit_price_per_million: float | None = None
    output_price_per_million: float | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_domain(cls, model: ProviderCustomModel) -> "ProviderCustomModelResponse":
        """将领域对象转换为 Pydantic 响应模型"""

        return cls(
            provider_id=model.provider_id,
            model_id=model.model_id,
            display_name=model.display_name,
            family_group=model.family_group,
            capability_tags=list(model.capability_tags),
            note=model.note,
            price_currency=model.price_currency,
            input_price_per_million=model.input_price_per_million,
            cache_hit_price_per_million=model.cache_hit_price_per_million,
            output_price_per_million=model.output_price_per_million,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class ProviderCustomModelListResponse(BaseModel):
    count: int
    items: list[ProviderCustomModelResponse] = Field(default_factory=list)
