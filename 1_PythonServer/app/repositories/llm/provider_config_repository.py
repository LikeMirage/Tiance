from functools import lru_cache
from dataclasses import dataclass
from typing import Any

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
from app.domain.llm.provider_endpoint_templates import normalize_generation_urls
from app.repositories.llm.provider_file_store import (
    PROVIDER_CREDENTIALS_FILE,
    PROVIDER_MANIFEST_FILE,
    PROVIDER_SCHEMA_VERSION,
    ProviderFileStore,
    ProviderFileStoreError,
    get_provider_file_store,
)


class ProviderConfigRepository:
    def __init__(self, store: ProviderFileStore) -> None:
        self._store = store

    def list_configs(self) -> tuple[ProviderConfig, ...]:
        configs, _ = self.list_config_results()
        return configs

    def list_config_results(
        self,
    ) -> tuple[tuple[ProviderConfig, ...], tuple["ProviderConfigLoadFailure", ...]]:
        configs: list[ProviderConfig] = []
        failures: list[ProviderConfigLoadFailure] = []
        for provider_id in self._store.list_provider_ids():
            try:
                config = self.get_config(provider_id)
            except (ProviderFileStoreError, ValueError) as exc:
                failures.append(
                    ProviderConfigLoadFailure(
                        provider_id=provider_id,
                        message=str(exc),
                    )
                )
                continue
            if config is not None:
                configs.append(config)
        return tuple(configs), tuple(failures)

    def get_config(self, provider_id: str) -> ProviderConfig | None:
        manifest = self._store.read_provider_file(
            provider_id,
            PROVIDER_MANIFEST_FILE,
            required=False,
        )
        if manifest is None:
            return None
        credentials = self._store.read_provider_file(
            provider_id,
            PROVIDER_CREDENTIALS_FILE,
            required=False,
        ) or {"items": []}
        raw_items = credentials.get("items")
        if not isinstance(raw_items, list):
            raise ProviderFileStoreError("Provider credentials items must be a list.")
        api_keys = tuple(
            self._to_api_key_domain(provider_id, item)
            for item in raw_items
            if isinstance(item, dict)
        )
        protocol_family = ProviderProtocolFamily(_required_text(manifest, "protocolFamily"))
        generation_urls = normalize_generation_urls(
            manifest.get("generationUrls")
            if isinstance(manifest.get("generationUrls"), dict)
            else {}
        )
        api_base_url = generation_urls.get(protocol_family, "")
        generation_auth_schemes = _read_generation_auth_schemes(manifest)
        return ProviderConfig(
            provider_id=provider_id,
            api_base_url=api_base_url,
            enabled=bool(manifest.get("enabled", False)),
            api_keys=api_keys,
            created_at=_required_text(manifest, "createdAt"),
            updated_at=_required_text(manifest, "updatedAt"),
            model_discovery_url=_optional_text(manifest, "modelDiscoveryUrl"),
            protocol_family=protocol_family.value,
            generation_urls={
                protocol.value: generation_url
                for protocol, generation_url in generation_urls.items()
            },
            generation_auth_schemes={
                protocol.value: auth_scheme.value
                for protocol, auth_scheme in generation_auth_schemes.items()
            },
            model_discovery_strategy=_required_text(
                manifest,
                "modelDiscoveryStrategy",
            ),
            model_discovery_auth_scheme=_required_text(
                manifest,
                "modelDiscoveryAuthScheme",
            ),
            reasoning_replay_mode=ReasoningReplayMode(
                _required_text(manifest, "reasoningReplayMode")
            ),
        )

    def list_api_keys(self, provider_id: str) -> tuple[ProviderApiKeyConfig, ...]:
        config = self.get_config(provider_id)
        return () if config is None else config.api_keys

    def save_config(self, config: ProviderConfig) -> ProviderConfig:
        credentials = {
            "schemaVersion": PROVIDER_SCHEMA_VERSION,
            "items": [self._from_api_key_domain(item) for item in config.api_keys],
        }
        self._store.write_provider_file(config.provider_id, PROVIDER_CREDENTIALS_FILE, credentials)

        def update_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
            protocol_family = ProviderProtocolFamily(
                config.protocol_family or _required_text(manifest, "protocolFamily")
            )
            generation_urls = normalize_generation_urls(
                manifest.get("generationUrls")
                if isinstance(manifest.get("generationUrls"), dict)
                else {}
            )
            incoming_generation_urls = normalize_generation_urls(config.generation_urls)
            if config.updated_generation_protocol is not None:
                updated_protocol = ProviderProtocolFamily(config.updated_generation_protocol)
                updated_url = incoming_generation_urls.get(updated_protocol)
                if updated_url is None:
                    generation_urls.pop(updated_protocol, None)
                else:
                    generation_urls[updated_protocol] = updated_url
            else:
                generation_urls.update(incoming_generation_urls)
            if config.api_base_url.strip():
                generation_urls[protocol_family] = config.api_base_url
            else:
                generation_urls.pop(protocol_family, None)
            existing_auth_schemes = _read_optional_generation_auth_schemes(manifest)
            generation_auth_schemes = {
                **{
                    protocol.value: auth_scheme.value
                    for protocol, auth_scheme in existing_auth_schemes.items()
                },
                **dict(config.generation_auth_schemes),
            }
            generation_auth_schemes.setdefault(
                protocol_family.value,
                default_generation_auth_scheme(protocol_family).value,
            )
            strategy = ModelDiscoveryStrategy(
                config.model_discovery_strategy
                or _optional_text(manifest, "modelDiscoveryStrategy")
                or default_model_discovery_strategy(protocol_family).value
            )
            model_auth_scheme = (
                config.model_discovery_auth_scheme
                or _optional_text(manifest, "modelDiscoveryAuthScheme")
                or default_model_discovery_auth_scheme(strategy).value
            )
            manifest.update(
                {
                    "generationUrls": {
                        protocol.value: generation_url
                        for protocol, generation_url in generation_urls.items()
                    },
                    "generationAuthSchemes": generation_auth_schemes,
                    "modelDiscoveryStrategy": strategy.value,
                    "modelDiscoveryAuthScheme": model_auth_scheme,
                    "modelDiscoveryUrl": config.model_discovery_url,
                    "enabled": config.enabled and bool(config.api_base_url.strip()),
                    "createdAt": config.created_at,
                    "updatedAt": config.updated_at,
                    "reasoningReplayMode": config.reasoning_replay_mode.value,
                }
            )
            return manifest

        self._store.update_provider_file(
            config.provider_id,
            PROVIDER_MANIFEST_FILE,
            update_manifest,
        )
        saved = self.get_config(config.provider_id)
        if saved is None:
            raise ProviderFileStoreError(f"Provider config save failed: {config.provider_id}")
        return saved

    def delete_config(self, provider_id: str) -> tuple[ProviderApiKeyConfig, ...]:
        existing_keys = self.list_api_keys(provider_id)
        config = self.get_config(provider_id)
        if config is None:
            return existing_keys
        self.save_config(
            ProviderConfig(
                provider_id=config.provider_id,
                api_base_url=config.api_base_url,
                enabled=False,
                api_keys=(),
                created_at=config.created_at,
                updated_at=config.updated_at,
                model_discovery_url=config.model_discovery_url,
                protocol_family=config.protocol_family,
                generation_urls=config.generation_urls,
                generation_auth_schemes=config.generation_auth_schemes,
                model_discovery_strategy=config.model_discovery_strategy,
                model_discovery_auth_scheme=config.model_discovery_auth_scheme,
                updated_generation_protocol=config.updated_generation_protocol,
                reasoning_replay_mode=config.reasoning_replay_mode,
            )
        )
        return existing_keys

    @staticmethod
    def _from_api_key_domain(api_key: ProviderApiKeyConfig) -> dict[str, Any]:
        return {
            "keyId": api_key.key_id,
            "hint": api_key.api_key_hint,
            "ciphertext": api_key.api_key_ciphertext,
            "pollWeight": api_key.poll_weight,
            "sortOrder": api_key.sort_order,
            "createdAt": api_key.created_at,
            "updatedAt": api_key.updated_at,
        }

    @staticmethod
    def _to_api_key_domain(provider_id: str, payload: dict[str, Any]) -> ProviderApiKeyConfig:
        return ProviderApiKeyConfig(
            key_id=_required_text(payload, "keyId"),
            provider_id=provider_id,
            api_key_hint=_optional_text(payload, "hint"),
            api_key_ciphertext=_optional_text(payload, "ciphertext"),
            poll_weight=int(payload.get("pollWeight", 1)),
            sort_order=int(payload.get("sortOrder", 0)),
            created_at=_required_text(payload, "createdAt"),
            updated_at=_required_text(payload, "updatedAt"),
        )


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = _optional_text(payload, key)
    if value is None:
        raise ProviderFileStoreError(f"Provider config field is required: {key}")
    return value


def _optional_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _read_generation_auth_schemes(
    manifest: dict[str, Any],
) -> dict[ProviderProtocolFamily, AuthScheme]:
    raw_value = manifest.get("generationAuthSchemes")
    if not isinstance(raw_value, dict):
        raise ProviderFileStoreError("Provider generation auth schemes must be an object.")
    return {
        ProviderProtocolFamily(str(protocol)): AuthScheme(str(auth_scheme))
        for protocol, auth_scheme in raw_value.items()
    }


def _read_optional_generation_auth_schemes(
    manifest: dict[str, Any],
) -> dict[ProviderProtocolFamily, AuthScheme]:
    raw_value = manifest.get("generationAuthSchemes")
    if raw_value is None:
        return {}
    return _read_generation_auth_schemes(manifest)


@dataclass(frozen=True, slots=True)
class ProviderConfigLoadFailure:
    provider_id: str
    message: str


@lru_cache
def get_provider_config_repository() -> ProviderConfigRepository:
    return ProviderConfigRepository(get_provider_file_store())
