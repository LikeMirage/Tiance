# 运行时配置解析器
# 将保存的 ProviderConfig 解析为运行时可用的配置（含调度器选择的 API Key）

from app.domain.llm.provider_catalog import ProviderCatalogEntry
from app.domain.llm.provider_config import ProviderConfig
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.services.llm.provider.api_key_scheduler import (
    ProviderApiKeyScheduler,
    ProviderRuntimeApiKey,
)
from app.services.llm.provider.api_key_secrets import resolve_api_key_secret


class ProviderConfigRuntimeResolver:
    def __init__(
        self,
        api_key_scheduler: ProviderApiKeyScheduler,
    ) -> None:
        self._api_key_scheduler = api_key_scheduler

    def resolve_runtime_credentials(
        self,
        provider_template: ProviderCatalogEntry,
        config: ProviderConfig,
    ) -> tuple[ProviderRuntimeConfig, ProviderRuntimeApiKey] | None:
        active_api_keys = self._resolve_active_api_keys(config)
        selected_api_key = (
            _anonymous_api_key()
            if not config.api_keys
            else self._api_key_scheduler.select_next(
                provider_template.provider_id,
                active_api_keys,
            )
        )
        if selected_api_key is None:
            return None

        return (
            ProviderRuntimeConfig(
                provider_id=config.provider_id,
                display_name=provider_template.display_name,
                api_base_url=config.api_base_url,
                model_discovery_url=config.model_discovery_url,
            ),
            selected_api_key,
        )

    def _resolve_active_api_keys(
        self,
        config: ProviderConfig,
    ) -> tuple[ProviderRuntimeApiKey, ...]:
        resolved_keys: list[ProviderRuntimeApiKey] = []
        for api_key_config in config.api_keys:
            if api_key_config.poll_weight <= 0:
                continue

            api_key = resolve_api_key_secret(api_key_config)

            resolved_keys.append(
                ProviderRuntimeApiKey(
                    key_id=api_key_config.key_id,
                    api_key=api_key,
                    api_key_hint=api_key_config.api_key_hint,
                    poll_weight=api_key_config.poll_weight,
                )
            )

        return tuple(resolved_keys)


def _anonymous_api_key() -> ProviderRuntimeApiKey:
    return ProviderRuntimeApiKey(
        key_id="",
        api_key="",
        api_key_hint=None,
        poll_weight=1,
    )
