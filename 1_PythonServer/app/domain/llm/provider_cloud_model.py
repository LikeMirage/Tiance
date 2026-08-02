# 云模型缓存领域模型
# 从上游供应商发现到的模型列表快照，缓存在本地

from dataclasses import dataclass

from app.domain.llm.discovered_model import DiscoveredModel


@dataclass(frozen=True, slots=True)
class ProviderCloudModelCache:
    """云模型缓存：供应商发现结果快照，包含发现时间和模型列表"""

    provider_id: str
    protocol_family: str
    api_base_url: str
    discovered_at: str | None
    models: tuple[DiscoveredModel, ...]
