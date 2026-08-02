from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.domain.github_sync import GithubSyncBinding
from app.domain.project import ProjectKind


class GithubSyncBindingRepository:
    def __init__(self, settings_path: Path) -> None:
        self._settings_path = settings_path

    def list_bindings(self) -> tuple[GithubSyncBinding, ...]:
        payload = self._read_payload()
        bindings: list[GithubSyncBinding] = []
        for raw_collection, raw_binding in payload.get("bindings", {}).items():
            try:
                collection = ProjectKind(raw_collection)
            except ValueError:
                continue
            if not isinstance(raw_binding, dict):
                continue
            repository = raw_binding.get("repository")
            branch = raw_binding.get("branch")
            remote_path = raw_binding.get("remotePath")
            updated_at = raw_binding.get("updatedAt")
            if not all(isinstance(value, str) for value in (
                repository, branch, remote_path, updated_at,
            )):
                continue
            bindings.append(GithubSyncBinding(
                collection=collection,
                repository=repository,
                branch=branch,
                remote_path=remote_path,
                updated_at=updated_at,
            ))
        return tuple(sorted(bindings, key=lambda item: item.collection.value))

    def get_binding(self, collection: ProjectKind) -> GithubSyncBinding | None:
        return next(
            (item for item in self.list_bindings() if item.collection is collection),
            None,
        )

    def save_binding(
        self,
        *,
        collection: ProjectKind,
        repository: str,
        branch: str,
        remote_path: str,
    ) -> GithubSyncBinding:
        binding = GithubSyncBinding(
            collection=collection,
            repository=repository,
            branch=branch,
            remote_path=remote_path,
            updated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )
        payload = self._read_payload()
        bindings = payload.setdefault("bindings", {})
        bindings[collection.value] = {
            "repository": repository,
            "branch": branch,
            "remotePath": remote_path,
            "updatedAt": binding.updated_at,
        }
        self._write_payload(payload)
        return binding

    def delete_binding(self, collection: ProjectKind) -> None:
        payload = self._read_payload()
        bindings = payload.setdefault("bindings", {})
        bindings.pop(collection.value, None)
        self._write_payload(payload)

    def _read_payload(self) -> dict:
        try:
            payload = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {"schemaVersion": 1, "bindings": {}}
        if (
            not isinstance(payload, dict)
            or payload.get("schemaVersion") != 1
            or not isinstance(payload.get("bindings"), dict)
        ):
            return {"schemaVersion": 1, "bindings": {}}
        return payload

    def _write_payload(self, payload: dict) -> None:
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._settings_path.with_name(
            f".{self._settings_path.name}.{uuid4().hex}.tmp"
        )
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            atomic_replace_path(temporary, self._settings_path)
        finally:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)

