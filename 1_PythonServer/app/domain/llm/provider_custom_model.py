# 用户自定义模型领域模型
# 用户为特定供应商手动添加的模型条目，含价格信息和功能标签

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderCustomModel:
    """用户自定义模型：用户为供应商添加的私有模型记录，含定价"""

    provider_id: str
    model_id: str
    display_name: str
    family_group: str
    capability_tags: tuple[str, ...] = ()
    note: str = ""
    price_currency: str = "CNY"
    input_price_per_million: float | None = None
    cache_hit_price_per_million: float | None = None
    output_price_per_million: float | None = None
    created_at: str | None = None
    updated_at: str | None = None
