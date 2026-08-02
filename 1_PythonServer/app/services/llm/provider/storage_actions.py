from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from app.core.errors import BadRequestError, NotFoundError
from app.infra.file_explorer import FileExplorerOpenError, open_directory_in_file_explorer
from app.repositories.llm.provider_file_store import ProviderFileStore, get_provider_file_store


class ProviderStorageActionsService:
    def __init__(
        self,
        store: ProviderFileStore,
        reveal_directory: Callable[[Path], None] = open_directory_in_file_explorer,
    ) -> None:
        self._store = store
        self._reveal_directory = reveal_directory

    def reveal_provider_directory(self, provider_id: str) -> None:
        if not self._store.has_provider(provider_id):
            raise NotFoundError(f"Provider '{provider_id}' was not found.")

        try:
            self._reveal_directory(self._store.provider_dir(provider_id))
        except FileExplorerOpenError as exc:
            raise BadRequestError("无法在资源管理器中打开供应商目录。") from exc


@lru_cache
def get_provider_storage_actions_service() -> ProviderStorageActionsService:
    return ProviderStorageActionsService(get_provider_file_store())
