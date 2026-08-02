# 发现的模型领域模型
# 上游供应商模型发现接口返回的模型摘要信息

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DiscoveredModel:
    """发现的模型：ID、显示名称、所属供应商、族群分类和功能标签"""

    model_id: str
    display_name: str
    provider_id: str
    family_group: str = ""
    capability_tags: tuple[str, ...] = ()
    raw_payload: dict[str, object] | None = None
