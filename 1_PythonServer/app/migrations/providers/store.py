"""A provider store that backs up existing files before migration writes."""

from app.migrations.files import backup_file
from app.repositories.llm.provider_file_store import ProviderFileStore, PROVIDER_SETTINGS_FILE


class MigrationProviderStore(ProviderFileStore):
    def write_provider_file(self, provider_id, filename, payload):
        backup_file(self.provider_file(provider_id, filename))
        super().write_provider_file(provider_id, filename, payload)

    def write_settings(self, payload):
        backup_file(self.root_path / PROVIDER_SETTINGS_FILE)
        super().write_settings(payload)
