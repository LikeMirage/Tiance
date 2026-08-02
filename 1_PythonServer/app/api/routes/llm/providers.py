# 供应商目录路由
# 管理统一供应商：列表、查询、创建、更新、删除、排序、模型发现预览

import httpx
from fastapi import APIRouter, Response, status

from app.core.errors import NotFoundError, UpstreamProviderError, to_upstream_provider_error
from app.domain.llm.provider_catalog import ProviderCatalogEntry
from app.schemas.llm.provider_catalog import (
    ProviderCatalogCreateRequest,
    ProviderCatalogEntryResponse,
    ProviderCatalogListResponse,
    ProviderCatalogOrderResponse,
    ProviderCatalogOrderSaveRequest,
    ProviderCatalogUpdateRequest,
    ProviderModelDiscoveryRequest,
)
from app.schemas.llm.discovered_models import DiscoveredModelListResponse, DiscoveredModelResponse
from app.services.llm.provider.catalog import get_provider_catalog_service
from app.services.llm.provider.catalog_discovery import get_provider_catalog_discovery_service
from app.services.llm.provider.catalog_mutation import get_provider_catalog_mutation_service
from app.services.llm.provider.preset_catalog import get_provider_endpoint_preset
from app.services.llm.provider.storage_actions import get_provider_storage_actions_service

router = APIRouter(prefix="/llm/catalog/providers", tags=["llm"])


def _provider_response(entry: ProviderCatalogEntry) -> ProviderCatalogEntryResponse:
    endpoint_preset = get_provider_endpoint_preset(entry.provider_id)
    return ProviderCatalogEntryResponse.from_domain(
        entry,
        preset_generation_urls=(
            endpoint_preset.generation_urls if endpoint_preset else None
        ),
        preset_generation_auth_schemes=(
            endpoint_preset.generation_auth_schemes if endpoint_preset else None
        ),
        preset_model_discovery_strategy=(
            endpoint_preset.model_discovery_strategy if endpoint_preset else None
        ),
        preset_model_discovery_auth_scheme=(
            endpoint_preset.model_discovery_auth_scheme
            if endpoint_preset
            else None
        ),
        preset_model_discovery_url=(
            endpoint_preset.model_discovery_url if endpoint_preset else None
        ),
    )


@router.get("", response_model=ProviderCatalogListResponse, summary="List supported LLM providers")
def list_llm_providers() -> ProviderCatalogListResponse:
    service = get_provider_catalog_service()
    items = [_provider_response(entry) for entry in service.list_provider_templates()]
    return ProviderCatalogListResponse(count=len(items), items=items)


@router.post(
    "",
    response_model=ProviderCatalogEntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an LLM provider",
)
def create_llm_provider(payload: ProviderCatalogCreateRequest) -> ProviderCatalogEntryResponse:
    service = get_provider_catalog_mutation_service()
    entry = service.create_provider(
        display_name=payload.display_name,
        api_base_url=payload.api_base_url,
        model_discovery_url=payload.model_discovery_url,
        provider_id=payload.provider_id,
        protocol_family=payload.protocol_family,
        auth_scheme=payload.auth_scheme,
        category_id=payload.category_id,
    )
    return _provider_response(entry)


@router.get(
    "/order",
    response_model=ProviderCatalogOrderResponse,
    summary="Get persisted provider catalog order",
)
def get_llm_provider_order() -> ProviderCatalogOrderResponse:
    service = get_provider_catalog_service()
    provider_ids = list(service.get_provider_order())
    return ProviderCatalogOrderResponse(count=len(provider_ids), provider_ids=provider_ids)


@router.put(
    "/order",
    response_model=ProviderCatalogOrderResponse,
    summary="Save provider catalog order",
)
def save_llm_provider_order(
    payload: ProviderCatalogOrderSaveRequest,
) -> ProviderCatalogOrderResponse:
    service = get_provider_catalog_service()
    provider_ids = list(service.save_provider_order(tuple(payload.provider_ids)))
    return ProviderCatalogOrderResponse(count=len(provider_ids), provider_ids=provider_ids)


@router.patch(
    "/{provider_id}",
    response_model=ProviderCatalogEntryResponse,
    summary="Update an LLM provider",
)
def update_llm_provider(
    provider_id: str,
    payload: ProviderCatalogUpdateRequest,
) -> ProviderCatalogEntryResponse:
    service = get_provider_catalog_mutation_service()
    entry = service.update_provider(
        provider_id=provider_id,
        display_name=payload.display_name,
        protocol_family=payload.protocol_family,
    )
    return _provider_response(entry)


@router.delete(
    "/{provider_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an LLM provider",
)
def delete_llm_provider(provider_id: str) -> Response:
    service = get_provider_catalog_mutation_service()
    service.delete_provider(provider_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{provider_id}/reveal",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Open an LLM provider directory in file explorer",
)
def reveal_llm_provider_directory(provider_id: str) -> Response:
    service = get_provider_storage_actions_service()
    service.reveal_provider_directory(provider_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{provider_id}",
    response_model=ProviderCatalogEntryResponse,
    summary="Get a single LLM provider template",
)
def get_llm_provider(provider_id: str) -> ProviderCatalogEntryResponse:
    service = get_provider_catalog_service()
    entry = service.get_provider_template(provider_id)
    if entry is None:
        raise NotFoundError(f"Provider template '{provider_id}' was not found.")
    return _provider_response(entry)


@router.post(
    "/{provider_id}/discover-models",
    response_model=DiscoveredModelListResponse,
    summary="Discover models for a provider template without saving an instance",
)
async def discover_provider_models(
    provider_id: str,
    payload: ProviderModelDiscoveryRequest,
) -> DiscoveredModelListResponse:
    service = get_provider_catalog_discovery_service()
    try:
        models = await service.discover_models(
            provider_id=provider_id,
            api_base_url=payload.api_base_url,
            model_discovery_url=payload.model_discovery_url,
            api_key=payload.api_key,
        )
    except httpx.HTTPStatusError as exc:
        raise to_upstream_provider_error(exc) from exc
    except httpx.RequestError as exc:
        raise UpstreamProviderError(f"上游供应商连接失败：{exc}") from exc

    items = [DiscoveredModelResponse.from_domain(model) for model in models]
    return DiscoveredModelListResponse(count=len(items), items=items)
