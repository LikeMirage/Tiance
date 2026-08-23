# 供应商配置路由
# 保存/读取供应商配置和 API 密钥、模型探测、云模型发现与缓存、自定义模型 CRUD

import httpx
from fastapi import APIRouter

from app.core.errors import (
    AppError,
    NotFoundError,
    UpstreamProviderError,
    local_exception_message,
    to_upstream_provider_error,
)
from app.schemas.llm.discovered_models import (
    DiscoveredModelListResponse,
    DiscoveredModelResponse,
)
from app.schemas.llm.provider_configs import (
    ProviderApiKeyConfigInputRequest,
    ProviderCloudModelCacheResponse,
    ProviderConfigListResponse,
    ProviderConfigLoadErrorResponse,
    ProviderModelCheckRequest,
    ProviderModelCheckResponse,
    ProviderConfigResponse,
    ProviderConfigSaveRequest,
    ProviderPromptCachePolicyResponse,
    ProviderPromptCachePolicySaveRequest,
)
from app.schemas.llm.provider_custom_models import (
    ProviderCustomModelListResponse,
    ProviderCustomModelResponse,
    ProviderCustomModelSaveRequest,
)
from app.services.llm.provider.configs import (
    ProviderApiKeyConfigInput,
    get_provider_config_service,
)
from app.services.llm.provider.api_key_scheduler import get_provider_api_key_scheduler
from app.services.llm.provider.custom_models import (
    ProviderCustomModelSaveInput,
    get_provider_custom_model_service,
)

router = APIRouter(prefix="/llm/provider-configs", tags=["llm"])


@router.get(
    "",
    response_model=ProviderConfigListResponse,
    summary="List saved provider configurations",
)
def list_provider_configs() -> ProviderConfigListResponse:
    service = get_provider_config_service()
    configs, failures = service.list_config_results()
    items = [_provider_config_response(item, service) for item in configs]
    errors = [
        ProviderConfigLoadErrorResponse(
            provider_id=failure.provider_id,
            message=failure.message,
        )
        for failure in failures
    ]
    return ProviderConfigListResponse(count=len(items), items=items, errors=errors)


@router.get(
    "/{provider_id}",
    response_model=ProviderConfigResponse,
    summary="Get a saved provider configuration",
)
def get_provider_config(provider_id: str) -> ProviderConfigResponse:
    service = get_provider_config_service()
    config = service.get_config(provider_id)
    if config is None:
        raise NotFoundError(f"Provider config '{provider_id}' was not found.")
    return _provider_config_response(config, service)


@router.put(
    "/{provider_id}",
    response_model=ProviderConfigResponse,
    summary="Save a provider configuration",
)
def save_provider_config(
    provider_id: str,
    payload: ProviderConfigSaveRequest,
) -> ProviderConfigResponse:
    service = get_provider_config_service()
    config = service.save_config(
        provider_id=provider_id,
        api_base_url=payload.api_base_url,
        protocol_family=payload.protocol_family,
        auth_scheme=payload.auth_scheme,
        model_discovery_url=payload.model_discovery_url,
        model_discovery_strategy=payload.model_discovery_strategy,
        model_discovery_auth_scheme=payload.model_discovery_auth_scheme,
        enabled=payload.enabled,
        api_keys=tuple(_to_api_key_input(api_key) for api_key in payload.api_keys),
        reasoning_replay_mode=payload.reasoning_replay_mode,
    )
    return _provider_config_response(config, service)


@router.put(
    "/{provider_id}/prompt-cache-policy",
    response_model=ProviderPromptCachePolicyResponse,
    summary="Save provider prompt cache retention policy",
)
def save_provider_prompt_cache_policy(
    provider_id: str,
    payload: ProviderPromptCachePolicySaveRequest,
) -> ProviderPromptCachePolicyResponse:
    seconds = get_provider_config_service().save_prompt_cache_retention_seconds(
        provider_id=provider_id,
        seconds=payload.prompt_cache_retention_seconds,
    )
    return ProviderPromptCachePolicyResponse(
        provider_id=provider_id,
        prompt_cache_retention_seconds=seconds,
    )


@router.post(
    "/{provider_id}/model-check",
    response_model=ProviderModelCheckResponse,
    summary="Check a saved provider model with a minimal generation request",
)
async def check_provider_config_model(
    provider_id: str,
    payload: ProviderModelCheckRequest,
) -> ProviderModelCheckResponse:
    normalized_model_id = payload.model_id.strip()
    if not normalized_model_id:
        raise AppError("模型 ID 不能为空。")

    service = get_provider_config_service()
    try:
        result = await service.check_model(provider_id, normalized_model_id)
    except httpx.HTTPStatusError as exc:
        raise to_upstream_provider_error(exc) from exc
    except httpx.RequestError as exc:
        raise UpstreamProviderError(
            local_exception_message(exc),
            code="upstream_connection_error",
        ) from exc

    if result is None:
        raise AppError("先保存 API KEY 后再测试模型。")

    return ProviderModelCheckResponse(
        provider_id=provider_id,
        model_id=str(result.get("model_id", normalized_model_id)),
        ok=bool(result.get("ok", False)),
        checked_url=str(result.get("checked_url", "")),
        selected_key_id=str(result.get("selected_key_id", "")) or None,
        selected_api_key_hint=str(result.get("selected_api_key_hint", "")) or None,
    )


@router.post(
    "/{provider_id}/discover-models",
    response_model=DiscoveredModelListResponse,
    summary="Discover models with a saved provider configuration",
)
async def discover_provider_config_models(provider_id: str) -> DiscoveredModelListResponse:
    service = get_provider_config_service()
    try:
        models = await service.discover_models(provider_id)
    except httpx.HTTPStatusError as exc:
        raise to_upstream_provider_error(exc) from exc
    except httpx.RequestError as exc:
        raise UpstreamProviderError(
            local_exception_message(exc),
            code="upstream_connection_error",
        ) from exc

    if models is None:
        raise AppError(f"Provider config '{provider_id}' has no saved API key.")
    items = [DiscoveredModelResponse.from_domain(model) for model in models]
    return DiscoveredModelListResponse(count=len(items), items=items)


@router.get(
    "/{provider_id}/cloud-models",
    response_model=ProviderCloudModelCacheResponse,
    summary="Get cached cloud models for a saved provider configuration",
)
def get_provider_cloud_models(provider_id: str) -> ProviderCloudModelCacheResponse:
    service = get_provider_config_service()
    cache = service.get_cloud_model_cache(provider_id)
    return ProviderCloudModelCacheResponse.from_domain(cache)


@router.post(
    "/{provider_id}/cloud-models/refresh",
    response_model=ProviderCloudModelCacheResponse,
    summary="Refresh and cache cloud models for a saved provider configuration",
)
async def refresh_provider_cloud_models(provider_id: str) -> ProviderCloudModelCacheResponse:
    service = get_provider_config_service()
    try:
        cache = await service.refresh_cloud_model_cache(provider_id)
    except httpx.HTTPStatusError as exc:
        raise to_upstream_provider_error(exc) from exc
    except httpx.RequestError as exc:
        raise UpstreamProviderError(
            local_exception_message(exc),
            code="upstream_connection_error",
        ) from exc

    if cache is None:
        raise AppError("先保存 API KEY 后再同步云模型。")

    return ProviderCloudModelCacheResponse.from_domain(cache)


@router.get(
    "/{provider_id}/custom-models",
    response_model=ProviderCustomModelListResponse,
    summary="List manually added models for a provider",
)
def list_provider_custom_models(provider_id: str) -> ProviderCustomModelListResponse:
    service = get_provider_custom_model_service()
    models = service.list_models(provider_id)
    items = [ProviderCustomModelResponse.from_domain(model) for model in models]
    return ProviderCustomModelListResponse(count=len(items), items=items)


@router.post(
    "/{provider_id}/custom-models",
    response_model=ProviderCustomModelResponse,
    status_code=201,
    summary="Add or update a manually configured model for a provider",
)
def save_provider_custom_model(
    provider_id: str,
    payload: ProviderCustomModelSaveRequest,
) -> ProviderCustomModelResponse:
    service = get_provider_custom_model_service()
    model = service.save_model(
        ProviderCustomModelSaveInput(
            provider_id=provider_id,
            model_id=payload.model_id,
            display_name=payload.display_name,
            family_group=payload.family_group,
            capability_tags=tuple(payload.capability_tags),
            note=payload.note,
            price_currency=payload.price_currency,
            input_price_per_million=payload.input_price_per_million,
            cache_hit_price_per_million=payload.cache_hit_price_per_million,
            output_price_per_million=payload.output_price_per_million,
        )
    )
    return ProviderCustomModelResponse.from_domain(model)


@router.delete(
    "/{provider_id}/custom-models/{model_id:path}",
    status_code=204,
    summary="Delete a manually configured model from a provider",
)
def delete_provider_custom_model(provider_id: str, model_id: str) -> None:
    service = get_provider_custom_model_service()
    deleted = service.delete_model(provider_id=provider_id, model_id=model_id)

    if not deleted:
        raise NotFoundError(f"Custom model '{model_id}' was not found.")


def _to_api_key_input(
    api_key: ProviderApiKeyConfigInputRequest,
) -> ProviderApiKeyConfigInput:
    """将 Pydantic 请求模型转换为服务层输入模型"""
    return ProviderApiKeyConfigInput(
        key_id=api_key.key_id,
        api_key=api_key.api_key,
        poll_weight=api_key.poll_weight,
    )


def _provider_config_response(config, service) -> ProviderConfigResponse:
    scheduler = get_provider_api_key_scheduler()
    return ProviderConfigResponse.from_domain(
        config,
        api_key_presence_by_id=service.get_api_key_presence_by_id(config),
        key_rpm_by_id={
            api_key.key_id: scheduler.get_rpm(
                provider_id=config.provider_id,
                key_id=api_key.key_id,
            )
            for api_key in config.api_keys
        },
        prompt_cache_retention_seconds=(
            service.get_prompt_cache_retention_seconds(config.provider_id)
        ),
    )
