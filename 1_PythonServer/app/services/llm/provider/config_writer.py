# 供应商配置写入服务
# API Key 由 secret_codec 统一加密后写入供应商文件包

from dataclasses import dataclass
from datetime import UTC, datetime
import re
from uuid import uuid4

from app.core.errors import BadRequestError
from app.domain.llm.provider_catalog import (
    AuthScheme,
    ModelDiscoveryStrategy,
    ProviderCatalogEntry,
    ProviderProtocolFamily,
)
from app.domain.llm.provider_config import ProviderApiKeyConfig, ProviderConfig
from app.infra.secrets.secret_codec import encrypt_secret
from app.repositories.llm.provider_cloud_model_repository import ProviderCloudModelRepository
from app.repositories.llm.provider_config_repository import ProviderConfigRepository
from app.services.llm.provider.api_base_url_validation import normalize_provider_api_base_url


@dataclass(frozen=True, slots=True)

class ProviderApiKeyConfigInput:
    key_id: str | None
    api_key: str | None
    poll_weight: int


class ProviderConfigWriter:
    def __init__(
        self,
        config_repository: ProviderConfigRepository,
        cloud_model_repository: ProviderCloudModelRepository,
    ) -> None:
        self._config_repository = config_repository
        self._cloud_model_repository = cloud_model_repository

    def save_config(
        self,
        *,
        provider_template: ProviderCatalogEntry,
        api_base_url: str | None,
        protocol_family: ProviderProtocolFamily | None = None,
        auth_scheme: AuthScheme | None = None,
        enabled: bool,
        api_keys: tuple[ProviderApiKeyConfigInput, ...],
        model_discovery_url: str | None = None,
        model_discovery_strategy: ModelDiscoveryStrategy | None = None,
        model_discovery_auth_scheme: AuthScheme | None = None,
    ) -> ProviderConfig:
        """保存供应商配置：API Key 以带模式前缀的安全载荷写入文件。"""
        target_protocol = protocol_family or provider_template.protocol_family
        existing_keys = {
            api_key.key_id: api_key
            for api_key in self._config_repository.list_api_keys(provider_template.provider_id)
        }
        now = _utc_now()
        next_api_keys: list[ProviderApiKeyConfig] = []
        seen_key_ids: set[str] = set()

        for sort_order, api_key_input in enumerate(api_keys):
            normalized_key_value = (api_key_input.api_key or "").strip()
            key_id = _resolve_key_id(api_key_input.key_id, seen_key_ids)
            seen_key_ids.add(key_id)
            existing_key = existing_keys.get(key_id)

            if not normalized_key_value and existing_key is None:
                continue

            api_key_hint = existing_key.api_key_hint if existing_key is not None else None
            api_key_ciphertext = (
                existing_key.api_key_ciphertext
                if existing_key is not None
                else None
            )
            created_at = existing_key.created_at if existing_key is not None else now

            if normalized_key_value:
                api_key_hint = _mask_api_key(normalized_key_value)
                api_key_ciphertext = encrypt_secret(normalized_key_value)
                if api_key_ciphertext is None:
                    raise RuntimeError("API Key 保存失败。")

            next_api_keys.append(
                ProviderApiKeyConfig(
                    key_id=key_id,
                    provider_id=provider_template.provider_id,
                    api_key_hint=api_key_hint,
                    api_key_ciphertext=api_key_ciphertext,
                    poll_weight=max(0, api_key_input.poll_weight),
                    sort_order=sort_order,
                    created_at=created_at,
                    updated_at=now,
                )
            )

        existing_config = self._config_repository.get_config(provider_template.provider_id)
        if api_base_url is None:
            normalized_api_base_url = (
                existing_config.generation_urls.get(target_protocol.value)
                if existing_config is not None
                else provider_template.endpoints.generation_urls.get(target_protocol)
            ) or ""
        elif api_base_url.strip():
            normalized_api_base_url = normalize_provider_api_base_url(api_base_url)
        else:
            normalized_api_base_url = ""
        if enabled and not normalized_api_base_url:
            raise BadRequestError("当前协议未配置完整生成 API 地址，不能启用供应商。")
        requested_model_discovery_url = (
            normalize_provider_api_base_url(model_discovery_url)
            if model_discovery_url and model_discovery_url.strip()
            else None
        )
        normalized_model_discovery_url = requested_model_discovery_url
        generation_urls = dict(
            existing_config.generation_urls
            if existing_config is not None
            else {
                protocol.value: generation_url
                for protocol, generation_url in provider_template.endpoints.generation_urls.items()
            }
        )
        if normalized_api_base_url:
            generation_urls[target_protocol.value] = normalized_api_base_url
        else:
            generation_urls.pop(target_protocol.value, None)
        generation_auth_schemes = dict(
            existing_config.generation_auth_schemes
            if existing_config is not None
            else {
                protocol.value: scheme.value
                for protocol, scheme in provider_template.generation_auth_schemes.items()
            }
        )
        selected_auth_scheme = auth_scheme or provider_template.generation_auth_schemes.get(
            target_protocol,
            provider_template.auth_scheme,
        )
        generation_auth_schemes[target_protocol.value] = selected_auth_scheme.value
        active_protocol = provider_template.protocol_family
        active_api_base_url = generation_urls.get(
            active_protocol.value,
            "",
        )
        config = ProviderConfig(
            provider_id=provider_template.provider_id,
            api_base_url=active_api_base_url,
            enabled=enabled,
            api_keys=tuple(next_api_keys),
            created_at=existing_config.created_at if existing_config is not None else now,
            updated_at=now,
            model_discovery_url=normalized_model_discovery_url,
            protocol_family=active_protocol.value,
            generation_urls=generation_urls,
            generation_auth_schemes=generation_auth_schemes,
            model_discovery_strategy=(
                model_discovery_strategy or provider_template.model_discovery_strategy
            ).value,
            model_discovery_auth_scheme=(
                model_discovery_auth_scheme
                or provider_template.model_discovery_auth_scheme
            ).value,
            updated_generation_protocol=target_protocol.value,
        )
        saved_config = self._config_repository.save_config(config)

        if existing_config is not None and (
            existing_config.api_base_url != saved_config.api_base_url
            or existing_config.model_discovery_url != saved_config.model_discovery_url
            or existing_config.model_discovery_strategy
            != saved_config.model_discovery_strategy
            or existing_config.model_discovery_auth_scheme
            != saved_config.model_discovery_auth_scheme
            or existing_config.generation_auth_schemes
            != saved_config.generation_auth_schemes
        ):
            self._cloud_model_repository.delete_provider_cache(saved_config.provider_id)

        return saved_config

def _resolve_key_id(key_id: str | None, seen_key_ids: set[str]) -> str:
    """解析或生成密钥 ID（保证不重复）"""
    normalized_key_id = (key_id or "").strip()
    if not re.fullmatch(r"[a-z0-9_-]+", normalized_key_id):
        normalized_key_id = uuid4().hex

    while normalized_key_id in seen_key_ids:
        normalized_key_id = uuid4().hex

    return normalized_key_id


def _mask_api_key(api_key: str) -> str | None:
    """对 API Key 脱敏（仅保留最后 4 位，其余用 * 代替）"""
    if not api_key:
        return None
    if len(api_key) <= 4:
        return "*" * len(api_key)
    return f"{'*' * max(len(api_key) - 4, 4)}{api_key[-4:]}"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
