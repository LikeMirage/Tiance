# 供应商目录 Pydantic 模型
# 请求/响应模型：供应商、列表、排序、创建和更新

from collections.abc import Mapping

from pydantic import BaseModel, Field

from app.domain.llm.provider_catalog import (
    AuthScheme,
    ModelDiscoveryStrategy,
    ProviderCatalogEntry,
    ProviderProtocolFamily,
)


class ProviderCatalogEntryResponse(BaseModel):
    provider_id: str
    display_name: str
    protocol_family: ProviderProtocolFamily
    auth_scheme: AuthScheme
    generation_auth_schemes: dict[ProviderProtocolFamily, AuthScheme] = Field(
        default_factory=dict
    )
    api_base_url: str
    generation_urls: dict[ProviderProtocolFamily, str] = Field(default_factory=dict)
    text_generation_url_template: str
    model_discovery_strategy: ModelDiscoveryStrategy
    model_discovery_auth_scheme: AuthScheme
    model_discovery_url: str | None = None
    preset_generation_urls: dict[ProviderProtocolFamily, str] = Field(default_factory=dict)
    preset_generation_auth_schemes: dict[ProviderProtocolFamily, AuthScheme] = Field(
        default_factory=dict
    )
    preset_model_discovery_strategy: ModelDiscoveryStrategy | None = None
    preset_model_discovery_auth_scheme: AuthScheme | None = None
    preset_model_discovery_url: str | None = None
    created_at: str | None = None

    @classmethod
    def from_domain(
        cls,
        entry: ProviderCatalogEntry,
        *,
        preset_generation_urls: Mapping[ProviderProtocolFamily, str] | None = None,
        preset_generation_auth_schemes: Mapping[
            ProviderProtocolFamily, AuthScheme
        ] | None = None,
        preset_model_discovery_strategy: ModelDiscoveryStrategy | None = None,
        preset_model_discovery_auth_scheme: AuthScheme | None = None,
        preset_model_discovery_url: str | None = None,
    ) -> "ProviderCatalogEntryResponse":
        """将领域对象转换为 Pydantic 响应模型"""

        return cls(
            provider_id=entry.provider_id,
            display_name=entry.display_name,
            protocol_family=entry.protocol_family,
            auth_scheme=entry.auth_scheme,
            generation_auth_schemes=dict(entry.generation_auth_schemes),
            api_base_url=entry.endpoints.api_base_url,
            generation_urls=dict(entry.endpoints.generation_urls),
            text_generation_url_template=entry.endpoints.text_generation_url_template,
            model_discovery_strategy=entry.model_discovery_strategy,
            model_discovery_auth_scheme=entry.model_discovery_auth_scheme,
            model_discovery_url=entry.endpoints.model_discovery_url,
            preset_generation_urls=dict(preset_generation_urls or {}),
            preset_generation_auth_schemes=dict(
                preset_generation_auth_schemes or {}
            ),
            preset_model_discovery_strategy=preset_model_discovery_strategy,
            preset_model_discovery_auth_scheme=preset_model_discovery_auth_scheme,
            preset_model_discovery_url=preset_model_discovery_url,
            created_at=entry.created_at,
        )


class ProviderCatalogListResponse(BaseModel):
    count: int
    items: list[ProviderCatalogEntryResponse]


class ProviderCatalogOrderResponse(BaseModel):
    count: int
    provider_ids: list[str] = Field(default_factory=list)


class ProviderCatalogOrderSaveRequest(BaseModel):
    provider_ids: list[str] = Field(default_factory=list)


class ProviderModelDiscoveryRequest(BaseModel):
    api_base_url: str | None = None
    model_discovery_url: str | None = None
    api_key: str | None = None


class ProviderCatalogCreateRequest(BaseModel):
    display_name: str
    api_base_url: str
    model_discovery_url: str | None = None
    provider_id: str | None = None
    category_id: str | None = None
    protocol_family: ProviderProtocolFamily = ProviderProtocolFamily.OPENAI_COMPATIBLE
    auth_scheme: AuthScheme = AuthScheme.BEARER_TOKEN


class ProviderCatalogUpdateRequest(BaseModel):
    display_name: str | None = None
    protocol_family: ProviderProtocolFamily | None = None
