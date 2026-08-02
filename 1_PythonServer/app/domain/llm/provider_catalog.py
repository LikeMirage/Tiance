# 供应商目录核心类型
# 定义协议族、认证方式、发现策略等枚举，以及供应商目录条目数据类

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class ProviderProtocolFamily(StrEnum):
    """供应商支持的 API 协议族：OpenAI 兼容 / OpenAI Responses / Anthropic Messages / Gemini"""

    OPENAI_COMPATIBLE = "openai_compatible"
    OPENAI_RESPONSES = "openai_responses"
    ANTHROPIC_MESSAGES = "anthropic_messages"
    GEMINI_GENERATE_CONTENT = "gemini_generate_content"


class AuthScheme(StrEnum):
    """API 认证方式。"""

    BEARER_TOKEN = "bearer_token"
    X_API_KEY = "x_api_key"
    X_GOOG_API_KEY = "x_goog_api_key"
    API_KEY_QUERY = "api_key_query"


class ModelDiscoveryStrategy(StrEnum):
    """模型发现策略：根据协议族选择不同的发现接口"""

    OPENAI_MODELS = "openai_models"
    ANTHROPIC_MODELS = "anthropic_models"
    GEMINI_MODELS = "gemini_models"


def default_model_discovery_strategy(
    protocol_family: ProviderProtocolFamily,
) -> ModelDiscoveryStrategy:
    if protocol_family == ProviderProtocolFamily.ANTHROPIC_MESSAGES:
        return ModelDiscoveryStrategy.ANTHROPIC_MODELS
    if protocol_family == ProviderProtocolFamily.GEMINI_GENERATE_CONTENT:
        return ModelDiscoveryStrategy.GEMINI_MODELS
    return ModelDiscoveryStrategy.OPENAI_MODELS


def default_generation_auth_scheme(
    protocol_family: ProviderProtocolFamily,
) -> AuthScheme:
    if protocol_family == ProviderProtocolFamily.ANTHROPIC_MESSAGES:
        return AuthScheme.X_API_KEY
    if protocol_family == ProviderProtocolFamily.GEMINI_GENERATE_CONTENT:
        return AuthScheme.X_GOOG_API_KEY
    return AuthScheme.BEARER_TOKEN


def default_model_discovery_auth_scheme(
    strategy: ModelDiscoveryStrategy,
) -> AuthScheme:
    if strategy == ModelDiscoveryStrategy.ANTHROPIC_MODELS:
        return AuthScheme.X_API_KEY
    if strategy == ModelDiscoveryStrategy.GEMINI_MODELS:
        return AuthScheme.X_GOOG_API_KEY
    return AuthScheme.BEARER_TOKEN


@dataclass(frozen=True, slots=True)
class ProviderEndpointTemplate:
    """供应商 API 端点模板：基础 URL、文本生成路径、模型发现路径"""

    api_base_url: str
    text_generation_url_template: str
    model_discovery_url: str | None
    generation_urls: Mapping[ProviderProtocolFamily, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderCatalogEntry:
    """供应商目录条目：包含供应商标识、协议族、认证方式、端点模板等信息"""

    provider_id: str
    display_name: str
    profile_id: str
    protocol_family: ProviderProtocolFamily
    generation_auth_schemes: Mapping[ProviderProtocolFamily, AuthScheme]
    model_discovery_strategy: ModelDiscoveryStrategy
    model_discovery_auth_scheme: AuthScheme
    endpoints: ProviderEndpointTemplate
    created_at: str | None = None

    @property
    def auth_scheme(self) -> AuthScheme:
        """当前生成协议使用的鉴权；未保存时采用协议默认值。"""
        return self.generation_auth_schemes.get(
            self.protocol_family,
            default_generation_auth_scheme(self.protocol_family),
        )
