# 供应商配置 Pydantic 模型
# 请求/响应模型：配置保存、API 密钥管理、云模型缓存、模型探测

from pydantic import BaseModel, Field

from app.domain.llm.provider_cloud_model import ProviderCloudModelCache
from app.domain.llm.provider_config import ProviderApiKeyConfig, ProviderConfig
from app.domain.llm.reasoning_replay import ReasoningReplayMode
from app.domain.llm.provider_catalog import (
    AuthScheme,
    ModelDiscoveryStrategy,
    ProviderProtocolFamily,
    default_generation_auth_scheme,
    default_model_discovery_auth_scheme,
    default_model_discovery_strategy,
)
from app.schemas.llm.discovered_models import DiscoveredModelResponse


class ProviderApiKeyConfigInputRequest(BaseModel):
    """API 密钥输入：新建时传 api_key，更新时传 key_id"""

    key_id: str | None = None
    api_key: str | None = None
    poll_weight: int = Field(default=1, ge=0)


class ProviderConfigSaveRequest(BaseModel):
    """供应商配置保存请求：基础 URL、启用状态、API 密钥列表"""

    api_base_url: str | None = None
    protocol_family: ProviderProtocolFamily
    auth_scheme: AuthScheme
    model_discovery_url: str | None = None
    model_discovery_strategy: ModelDiscoveryStrategy
    model_discovery_auth_scheme: AuthScheme
    enabled: bool = False
    api_keys: list[ProviderApiKeyConfigInputRequest] = Field(default_factory=list)
    reasoning_replay_mode: ReasoningReplayMode


class ProviderApiKeyConfigResponse(BaseModel):
    """API 密钥响应：不返回原文，仅透传是否有密钥和提示信息"""

    key_id: str
    has_api_key: bool
    api_key_hint: str | None = None
    poll_weight: int
    rpm: int = 0

    @classmethod
    def from_domain(
        cls,
        api_key: ProviderApiKeyConfig,
        *,
        has_api_key: bool | None = None,
        rpm: int = 0,
        ) -> "ProviderApiKeyConfigResponse":
        return cls(
            key_id=api_key.key_id,
            has_api_key=bool(api_key.api_key_ciphertext) if has_api_key is None else has_api_key,
            api_key_hint=api_key.api_key_hint,
            poll_weight=api_key.poll_weight,
            rpm=rpm,
        )


class ProviderConfigResponse(BaseModel):
    provider_id: str
    api_base_url: str
    protocol_family: ProviderProtocolFamily
    generation_urls: dict[ProviderProtocolFamily, str] = Field(default_factory=dict)
    auth_scheme: AuthScheme
    generation_auth_schemes: dict[ProviderProtocolFamily, AuthScheme] = Field(
        default_factory=dict
    )
    model_discovery_url: str | None = None
    model_discovery_strategy: ModelDiscoveryStrategy
    model_discovery_auth_scheme: AuthScheme
    enabled: bool
    prompt_cache_retention_seconds: int
    reasoning_replay_mode: ReasoningReplayMode
    api_keys: list[ProviderApiKeyConfigResponse] = Field(default_factory=list)
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(
        cls,
        config: ProviderConfig,
        *,
        api_key_presence_by_id: dict[str, bool] | None = None,
        key_rpm_by_id: dict[str, int] | None = None,
        prompt_cache_retention_seconds: int,
    ) -> "ProviderConfigResponse":
        api_key_presence_by_id = api_key_presence_by_id or {}
        key_rpm_by_id = key_rpm_by_id or {}
        protocol_family = ProviderProtocolFamily(config.protocol_family)
        auth_scheme = AuthScheme(
            config.generation_auth_schemes.get(
                config.protocol_family,
                default_generation_auth_scheme(protocol_family).value,
            )
        )
        model_discovery_strategy = ModelDiscoveryStrategy(
            config.model_discovery_strategy
            or default_model_discovery_strategy(protocol_family)
        )
        model_discovery_auth_scheme = AuthScheme(
            config.model_discovery_auth_scheme
            or default_model_discovery_auth_scheme(model_discovery_strategy)
        )
        return cls(
            provider_id=config.provider_id,
            api_base_url=config.api_base_url,
            protocol_family=protocol_family,
            generation_urls={
                ProviderProtocolFamily(protocol): generation_url
                for protocol, generation_url in config.generation_urls.items()
            },
            auth_scheme=auth_scheme,
            generation_auth_schemes={
                ProviderProtocolFamily(protocol): AuthScheme(auth_scheme)
                for protocol, auth_scheme in config.generation_auth_schemes.items()
            },
            model_discovery_url=config.model_discovery_url,
            model_discovery_strategy=model_discovery_strategy,
            model_discovery_auth_scheme=model_discovery_auth_scheme,
            enabled=config.enabled,
            prompt_cache_retention_seconds=prompt_cache_retention_seconds,
            reasoning_replay_mode=config.reasoning_replay_mode,
            api_keys=[
                ProviderApiKeyConfigResponse.from_domain(
                    api_key,
                    has_api_key=api_key_presence_by_id.get(api_key.key_id),
                    rpm=key_rpm_by_id.get(api_key.key_id, 0),
                )
                for api_key in config.api_keys
            ],
            created_at=config.created_at,
            updated_at=config.updated_at,
        )


class ProviderConfigListResponse(BaseModel):
    count: int
    items: list[ProviderConfigResponse]


class ProviderPromptCachePolicySaveRequest(BaseModel):
    prompt_cache_retention_seconds: int = Field(ge=60)


class ProviderPromptCachePolicyResponse(BaseModel):
    provider_id: str
    prompt_cache_retention_seconds: int


class ProviderCloudModelCacheResponse(BaseModel):
    provider_id: str
    protocol_family: str
    api_base_url: str
    has_cache: bool
    discovered_at: str | None = None
    count: int
    items: list[DiscoveredModelResponse] = Field(default_factory=list)

    @classmethod
    def from_domain(
        cls,
        cache: ProviderCloudModelCache,
    ) -> "ProviderCloudModelCacheResponse":
        return cls(
            provider_id=cache.provider_id,
            protocol_family=cache.protocol_family,
            api_base_url=cache.api_base_url,
            has_cache=cache.discovered_at is not None,
            discovered_at=cache.discovered_at,
            count=len(cache.models),
            items=[
                DiscoveredModelResponse.from_domain(model)
                for model in cache.models
            ],
        )


class ProviderModelCheckRequest(BaseModel):
    model_id: str = Field(min_length=1)


class ProviderModelCheckResponse(BaseModel):
    provider_id: str
    model_id: str
    ok: bool
    checked_url: str
    selected_key_id: str | None = None
    selected_api_key_hint: str | None = None
