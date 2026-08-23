from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
import shutil
from threading import RLock
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.core.config import get_settings


PROVIDER_MANIFEST_FILE = "provider.json"
PROVIDER_CREDENTIALS_FILE = "credentials.json"
PROVIDER_MODELS_FILE = "models.json"
PROVIDER_CLOUD_CACHE_FILE = "cloud-model-cache.json"
PROVIDER_RULES_FILE = "provider-rules.json"
PROVIDER_MODEL_RULES_FILE = "model-rules.json"
PROVIDER_SETTINGS_FILE = "provider-settings.json"
PROVIDER_SCHEMA_VERSION = 1
_PROVIDER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


class ProviderFileStoreError(RuntimeError):
    pass


class ProviderFileStore:
    def __init__(self, root_path: Path) -> None:
        self.root_path = root_path
        self._lock = RLock()

    def list_provider_ids(self) -> tuple[str, ...]:
        if not self.root_path.exists():
            return ()
        provider_ids: list[str] = []
        for item in self.root_path.iterdir():
            if not item.is_dir() or not _PROVIDER_ID_PATTERN.fullmatch(item.name):
                continue
            if (item / PROVIDER_MANIFEST_FILE).is_file():
                provider_ids.append(item.name)
        return tuple(sorted(provider_ids))

    def has_provider(self, provider_id: str) -> bool:
        try:
            return self.provider_file(provider_id, PROVIDER_MANIFEST_FILE).is_file()
        except ProviderFileStoreError:
            return False

    def has_provider_directory(self, provider_id: str) -> bool:
        try:
            return self.provider_dir(provider_id).is_dir()
        except ProviderFileStoreError:
            return False

    def read_provider_file(
        self,
        provider_id: str,
        file_name: str,
        *,
        required: bool = True,
    ) -> dict[str, Any] | None:
        path = self.provider_file(provider_id, file_name)
        return self._read_json(path, required=required)

    def write_provider_file(
        self,
        provider_id: str,
        file_name: str,
        payload: dict[str, Any],
    ) -> None:
        path = self.provider_file(provider_id, file_name)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._write_json_atomic(path, payload)

    def update_provider_file(
        self,
        provider_id: str,
        file_name: str,
        update: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        path = self.provider_file(provider_id, file_name)
        with self._lock:
            current = self._read_json(path, required=True)
            if current is None:  # pragma: no cover - required read cannot return None
                raise ProviderFileStoreError(f"Provider data file not found: {file_name}")
            updated = update(dict(current))
            self._write_json_atomic(path, updated)
            return updated

    def ensure_provider_sidecars(self, provider_id: str) -> None:
        defaults = {
            PROVIDER_CREDENTIALS_FILE: {
                "schemaVersion": PROVIDER_SCHEMA_VERSION,
                "items": [],
            },
            PROVIDER_MODELS_FILE: {
                "schemaVersion": PROVIDER_SCHEMA_VERSION,
                "items": [],
            },
            PROVIDER_CLOUD_CACHE_FILE: {
                "schemaVersion": PROVIDER_SCHEMA_VERSION,
                "cache": None,
            },
            PROVIDER_RULES_FILE: {
                "schemaVersion": PROVIDER_SCHEMA_VERSION,
                "capabilities": {},
                "request": {},
                "behavior": {},
            },
            PROVIDER_MODEL_RULES_FILE: {
                "schemaVersion": PROVIDER_SCHEMA_VERSION,
                "families": {},
                "models": {},
            },
        }
        for file_name, payload in defaults.items():
            path = self.provider_file(provider_id, file_name)
            if not path.exists():
                self.write_provider_file(provider_id, file_name, payload)

    def read_settings(self, *, required: bool = True) -> dict[str, Any] | None:
        return self._read_json(self.root_path / PROVIDER_SETTINGS_FILE, required=required)

    def write_settings(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.root_path.mkdir(parents=True, exist_ok=True)
            self._write_json_atomic(self.root_path / PROVIDER_SETTINGS_FILE, payload)

    def delete_provider(self, provider_id: str) -> bool:
        provider_dir = self.provider_dir(provider_id)
        if not provider_dir.exists():
            return False
        with self._lock:
            resolved_root = self.root_path.resolve()
            resolved_provider = provider_dir.resolve()
            if resolved_provider.parent != resolved_root:
                raise ProviderFileStoreError("Provider directory is outside the provider data root.")
            shutil.rmtree(resolved_provider)
        return True

    def provider_dir(self, provider_id: str) -> Path:
        self.validate_provider_id(provider_id)
        return self.root_path / provider_id

    def provider_file(self, provider_id: str, file_name: str) -> Path:
        if Path(file_name).name != file_name:
            raise ProviderFileStoreError("Provider file name is invalid.")
        return self.provider_dir(provider_id) / file_name

    @staticmethod
    def validate_provider_id(provider_id: str) -> None:
        if not _PROVIDER_ID_PATTERN.fullmatch(provider_id):
            raise ProviderFileStoreError(f"Invalid provider id: {provider_id}")

    @staticmethod
    def _read_json(path: Path, *, required: bool) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            if not required:
                return None
            raise ProviderFileStoreError(f"Provider data file not found: {path.name}")
        except (OSError, json.JSONDecodeError) as exc:
            raise ProviderFileStoreError(f"Unable to read provider data file: {path.name}") from exc
        if not isinstance(payload, dict):
            raise ProviderFileStoreError(f"Provider data file must contain an object: {path.name}")
        return payload

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
        temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            atomic_replace_path(temporary_path, path)
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            raise ProviderFileStoreError(f"Unable to save provider data file: {path.name}") from exc


@lru_cache
def get_provider_file_store() -> ProviderFileStore:
    return ProviderFileStore(get_settings().providers_data_path)
