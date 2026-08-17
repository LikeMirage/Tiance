# 供应商配置领域模型
# 保存的用户配置（API 密钥列表、自定义基础 URL 等）

from collections.abc import Mapping
from dataclasses import dataclass, field

from app.domain.llm.reasoning_replay import ReasoningReplayMode


@dataclass(frozen=True, slots=True)
class ProviderApiKeyConfig:
    """单条 API 密钥配置：密钥引用、提示（脱敏）、轮询权重"""

    key_id: str
    provider_id: str
    api_key_hint: str | None
    poll_weight: int
    sort_order: int
    created_at: str
    updated_at: str
    api_key_ciphertext: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """供应商配置：完整生成地址、模型发现地址和 API 密钥列表。"""

    provider_id: str
    api_base_url: str
    enabled: bool
    api_keys: tuple[ProviderApiKeyConfig, ...]
    created_at: str
    updated_at: str
    model_discovery_url: str | None = None
    protocol_family: str | None = None
    generation_urls: Mapping[str, str] = field(default_factory=dict)
    generation_auth_schemes: Mapping[str, str] = field(default_factory=dict)
    model_discovery_strategy: str | None = None
    model_discovery_auth_scheme: str | None = None
    updated_generation_protocol: str | None = None
    reasoning_replay_mode: ReasoningReplayMode = ReasoningReplayMode.TOOL_CALL_ROUNDS
