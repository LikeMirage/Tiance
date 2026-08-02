# 发现模型 Pydantic 模型
# 将上游供应商发现的模型序列化为 API 响应

from pydantic import BaseModel, Field

from app.domain.llm.discovered_model import DiscoveredModel


class DiscoveredModelResponse(BaseModel):
    """发现的模型响应：模型 ID、显示名称、所属供应商、族群、功能标签"""

    model_id: str
    display_name: str
    provider_id: str
    family_group: str
    capability_tags: list[str] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, model: DiscoveredModel) -> "DiscoveredModelResponse":
        """将领域对象转换为 Pydantic 响应模型"""

        return cls(
            model_id=model.model_id,
            display_name=model.display_name,
            provider_id=model.provider_id,
            family_group=model.family_group,
            capability_tags=list(model.capability_tags),
        )


class DiscoveredModelListResponse(BaseModel):
    count: int
    items: list[DiscoveredModelResponse] = Field(default_factory=list)
