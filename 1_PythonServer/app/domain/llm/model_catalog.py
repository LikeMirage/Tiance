# LLM 模型目录领域模型
# 统一表达前端选择器可用的供应商模型条目

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LlmModelCatalogEntry:
    """统一模型目录条目：由供应商配置、供应商目录和用户添加模型组合而来。"""

    provider_id: str
    provider_label: str
    provider_enabled: bool
    protocol_family: str
    model_id: str
    model_label: str
    family_group: str
    capability_tags: tuple[str, ...]
    source: str
    price_currency: str
    input_price_per_million: float | None = None
    cache_hit_price_per_million: float | None = None
    output_price_per_million: float | None = None
    created_at: str | None = None
    updated_at: str | None = None
