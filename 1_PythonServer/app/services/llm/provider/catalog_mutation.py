# 供应商变更服务
# 所有供应商使用同一套创建、更新和删除规则

from datetime import UTC, datetime
from functools import lru_cache
import re
from uuid import uuid4

from app.core.errors import BadRequestError, NotFoundError
from app.domain.llm.provider_catalog import (
    AuthScheme,
    ProviderCatalogEntry,
    ProviderProtocolFamily,
    default_generation_auth_scheme,
    default_model_discovery_auth_scheme,
    default_model_discovery_strategy,
)
from app.domain.llm.provider_endpoint_templates import (
    build_provider_endpoint_template,
)
from app.repositories.llm.provider_catalog_repository import (
    ProviderCatalogRepository,
    get_provider_catalog_repository,
)
from app.repositories.llm.provider_cloud_model_repository import (
    ProviderCloudModelRepository,
    get_provider_cloud_model_repository,
)
from app.repositories.llm.provider_catalog_deletion_repository import (
    ProviderCatalogDeletionRepository,
    get_provider_catalog_deletion_repository,
)
from app.services.llm.provider.api_base_url_validation import normalize_provider_api_base_url
from app.services.llm.provider.catalog_deletion import ProviderCatalogDeletionService
from app.services.llm.provider.preset_catalog import get_provider_endpoint_preset
from app.services.llm.provider.workspace_registry import (
    ProviderWorkspaceRegistryService,
    get_provider_workspace_registry_service,
)


class ProviderCatalogMutationService:
    def __init__(
        self,
        repository: ProviderCatalogRepository,
        cloud_model_repository: ProviderCloudModelRepository,
        deletion_repository: ProviderCatalogDeletionRepository,
        workspace_registry: ProviderWorkspaceRegistryService | None = None,
    ) -> None:
        self._repository = repository
        self._cloud_model_repository = cloud_model_repository
        self._deletion_service = ProviderCatalogDeletionService(deletion_repository)
        self._workspace_registry = workspace_registry

    def create_provider(
        self,
        *,
        display_name: str,
        api_base_url: str,
        provider_id: str | None,
        protocol_family: ProviderProtocolFamily,
        auth_scheme: AuthScheme,
        category_id: str | None = None,
        model_discovery_url: str | None = None,
    ) -> ProviderCatalogEntry:
        normalized_display_name = display_name.strip()
        raw_api_base_url = api_base_url.strip()
        normalized_api_base_url = (
            normalize_provider_api_base_url(raw_api_base_url)
            if raw_api_base_url
            else ""
        )
        normalized_model_discovery_url = (
            normalize_provider_api_base_url(model_discovery_url)
            if model_discovery_url and model_discovery_url.strip()
            else None
        )
        normalized_provider_id = _normalize_provider_id(provider_id)

        if not normalized_display_name:
            raise BadRequestError("Provider display name is required.")
        if normalized_provider_id is not None and self._repository.get_entry(normalized_provider_id):
            raise BadRequestError(f"Provider id '{normalized_provider_id}' already exists.")

        if normalized_provider_id is None:
            normalized_provider_id = self._generate_provider_id()
        if category_id and self._workspace_registry is not None:
            self._workspace_registry.validate_provider_category(category_id)

        now = _utc_now()
        entry = ProviderCatalogEntry(
            provider_id=normalized_provider_id,
            display_name=normalized_display_name,
            profile_id="generic",
            protocol_family=protocol_family,
            generation_auth_schemes={protocol_family: auth_scheme},
            model_discovery_strategy=(
                model_strategy := default_model_discovery_strategy(protocol_family)
            ),
            model_discovery_auth_scheme=default_model_discovery_auth_scheme(
                model_strategy
            ),
            endpoints=build_provider_endpoint_template(
                api_base_url=normalized_api_base_url,
                model_discovery_url=normalized_model_discovery_url,
                generation_urls={protocol_family: normalized_api_base_url},
            ),
            created_at=now,
        )
        saved_entry = self._repository.save_entry(entry, updated_at=now)
        self._synchronize_workspace_registry()
        if category_id and self._workspace_registry is not None:
            self._workspace_registry.move_provider_to_category(
                saved_entry.provider_id,
                category_id,
            )
        return saved_entry

    def update_provider(
        self,
        provider_id: str,
        *,
        display_name: str | None,
        protocol_family: ProviderProtocolFamily | None,
    ) -> ProviderCatalogEntry:
        provider_template = self._repository.get_entry(provider_id)
        if provider_template is None:
            raise NotFoundError(f"Provider template '{provider_id}' was not found.")
        normalized_display_name = (
            provider_template.display_name
            if display_name is None
            else display_name.strip()
        )
        if not normalized_display_name:
            raise BadRequestError("Provider display name is required.")

        next_protocol_family = protocol_family or provider_template.protocol_family
        generation_urls = dict(provider_template.endpoints.generation_urls)
        endpoint_preset = get_provider_endpoint_preset(provider_id)
        next_generation_url = generation_urls.get(next_protocol_family)
        if (
            next_generation_url is None
            and endpoint_preset is not None
            and next_protocol_family in endpoint_preset.generation_urls
        ):
            next_generation_url = endpoint_preset.generation_urls[next_protocol_family]
            generation_urls[next_protocol_family] = next_generation_url
        if next_generation_url is None:
            next_generation_url = ""
        generation_auth_schemes = dict(provider_template.generation_auth_schemes)
        if next_protocol_family not in generation_auth_schemes:
            preset_auth_scheme = (
                endpoint_preset.generation_auth_schemes.get(next_protocol_family)
                if endpoint_preset is not None
                else None
            )
            generation_auth_schemes[next_protocol_family] = (
                preset_auth_scheme
                or default_generation_auth_scheme(next_protocol_family)
            )
        now = _utc_now()
        updated_entry = ProviderCatalogEntry(
            provider_id=provider_template.provider_id,
            display_name=normalized_display_name,
            profile_id=provider_template.profile_id,
            protocol_family=next_protocol_family,
            generation_auth_schemes=generation_auth_schemes,
            model_discovery_strategy=provider_template.model_discovery_strategy,
            model_discovery_auth_scheme=(
                provider_template.model_discovery_auth_scheme
            ),
            endpoints=build_provider_endpoint_template(
                api_base_url=next_generation_url,
                model_discovery_url=provider_template.endpoints.model_discovery_url,
                generation_urls=generation_urls,
            ),
            created_at=provider_template.created_at,
        )
        saved_entry = self._repository.save_entry(updated_entry, updated_at=now)
        if provider_template.protocol_family != saved_entry.protocol_family:
            self._cloud_model_repository.delete_provider_cache(saved_entry.provider_id)
        self._synchronize_workspace_registry()
        return saved_entry

    def delete_provider(self, provider_id: str) -> None:
        provider_template = self._repository.get_entry(provider_id)
        if provider_template is None:
            raise NotFoundError(f"Provider template '{provider_id}' was not found.")
        self._deletion_service.delete_provider(provider_template)
        self._synchronize_workspace_registry()

    def delete_providers(self, provider_ids: tuple[str, ...]) -> None:
        providers = []
        for provider_id in provider_ids:
            provider = self._repository.get_entry(provider_id)
            if provider is None:
                raise NotFoundError(f"Provider template '{provider_id}' was not found.")
            providers.append(provider)
        for provider in providers:
            self._deletion_service.delete_provider(provider)
        self._synchronize_workspace_registry()

    def _synchronize_workspace_registry(self) -> None:
        if self._workspace_registry is not None:
            self._workspace_registry.synchronize()

    def _generate_provider_id(self) -> str:
        for _ in range(20):
            provider_id = f"provider_{uuid4().hex}"
            if self._repository.get_entry(provider_id) is None:
                return provider_id
        raise RuntimeError("Failed to generate a unique provider id.")


_PROVIDER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


def _normalize_provider_id(provider_id: str | None) -> str | None:
    normalized_provider_id = (provider_id or "").strip().lower()
    if not normalized_provider_id:
        return None
    if not _PROVIDER_ID_PATTERN.fullmatch(normalized_provider_id):
        raise BadRequestError("Provider id must use lowercase letters, numbers, '-' or '_'.")
    return normalized_provider_id


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@lru_cache
def get_provider_catalog_mutation_service() -> ProviderCatalogMutationService:
    return ProviderCatalogMutationService(
        get_provider_catalog_repository(),
        get_provider_cloud_model_repository(),
        get_provider_catalog_deletion_repository(),
        get_provider_workspace_registry_service(),
    )
