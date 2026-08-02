# 运行时供应商配置
# 在调用上游 API 时使用的轻量级配置（不含密钥原文）

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderRuntimeConfig:
    """运行时供应商信息：文本生成地址与独立的模型发现地址。"""

    provider_id: str
    display_name: str
    # 历史字段名保留在外部契约中；运行时语义是“完整文本生成地址”。
    api_base_url: str
    model_discovery_url: str | None = None
