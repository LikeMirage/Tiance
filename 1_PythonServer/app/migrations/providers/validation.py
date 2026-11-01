"""Validate staged provider files with the current repository contract."""
from app.repositories.llm.provider_file_store import ProviderFileStore, ProviderFileStoreError, PROVIDER_MANIFEST_FILE
from app.repositories.llm.provider_adaptation_rules_repository import ProviderAdaptationRulesRepository

def _validate_rule_files(store: ProviderFileStore) -> None:
    repository = ProviderAdaptationRulesRepository(store)
    for provider_id in store.list_provider_ids():
        manifest = store.read_provider_file(provider_id, PROVIDER_MANIFEST_FILE) or {}
        profile_id = manifest.get("profileId")
        if not isinstance(profile_id, str) or not profile_id:
            raise ProviderFileStoreError(f"Provider profileId is missing: {provider_id}")
        repository.resolve(
            provider_id=provider_id,
            model_id=None,
            expected_profile_id=profile_id,
        )
