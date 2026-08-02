from __future__ import annotations

from copy import deepcopy
from json import dumps
from pathlib import Path

from app.domain.project import ProjectKind
from app.infra.database import ensure_database_schema
from app.infra.file_workspace import FileWorkspaceStorage
from app.infra.projects import ProjectStorage
from app.repositories.llm.functional_model_settings_repository import (
    LlmFunctionalModelSettingsRepository,
)
from app.repositories.project import FileProjectCatalog, ProjectRepository
from app.repositories.project.conversation_repository import ProjectConversationRepository
from app.repositories.roles import (
    RoleMarketCacheRepository,
    RoleMarketSettingsRepository,
)
from app.services.application.project_creation import ProjectCreationApplicationService
from app.services.application.role_market import RoleMarketApplicationService
from app.services.document_conversion import MarkdownDocxService
from app.services.llm.functional_model_settings import LlmFunctionalModelSettingsService
from app.services.project.project_conversations import ProjectConversationService
from app.services.project.project_files import ProjectFileService
from app.services.project.projects import ProjectService


class FakeRoleMarketRemoteClient:
    def __init__(self, *, version: str = "1.0.0", fail_index: bool = False) -> None:
        self.version = version
        self.fail_index = fail_index
        self.download_calls = 0

    async def fetch_index(self, _source: str) -> dict[str, object]:
        if self.fail_index:
            from app.infra.role_market import RoleMarketConnectionError

            raise RoleMarketConnectionError("网络失败")
        return role_index(self.version)

    async def download_package(self, *, target: Path, **_kwargs) -> None:
        self.download_calls += 1
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"validated-by-fake")


class FakeRolePackageArchive:
    def __init__(self, *, version: str = "1.0.0") -> None:
        self.version = version

    def validate_and_extract(self, *, staging_root: Path, market_entry, **_kwargs) -> Path:
        root = staging_root / market_entry.id
        root.mkdir(parents=True)
        for name, payload in role_files(self.version).items():
            (root / name).write_text(
                dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return root


def build_role_market_service(
    tmp_path: Path,
    *,
    version: str = "1.0.0",
    fail_index: bool = False,
):
    database_path = tmp_path / "tiance.db"
    roles_root = tmp_path / "roles"
    ensure_database_schema(database_path)
    catalog = FileProjectCatalog(roles_root, project_kind=ProjectKind.ROLE)
    repository = ProjectRepository(database_path, file_catalogs=(catalog,))
    project_service = ProjectService(
        repository,
        ProjectStorage(tmp_path / "projects", roles_root=roles_root),
    )
    conversation_service = ProjectConversationService(
        ProjectConversationRepository(repository),
    )
    settings_service = LlmFunctionalModelSettingsService(
        LlmFunctionalModelSettingsRepository(database_path),
    )
    project_file_service = ProjectFileService(
        repository,
        FileWorkspaceStorage(),
        MarkdownDocxService(),
    )
    creation_service = ProjectCreationApplicationService(
        project_service,
        conversation_service,
        project_file_service,
        settings_service,
    )
    remote = FakeRoleMarketRemoteClient(version=version, fail_index=fail_index)
    service = RoleMarketApplicationService(
        app_version="0.1.0",
        roles_root=roles_root,
        settings_repository=RoleMarketSettingsRepository(
            roles_root / "market-settings.json"
        ),
        cache_repository=RoleMarketCacheRepository(roles_root / ".market-cache"),
        remote_client=remote,
        archive=FakeRolePackageArchive(version=version),
        catalog=catalog,
        project_service=project_service,
        project_creation_service=creation_service,
    )
    return service, project_service, conversation_service, catalog, remote, roles_root


def role_index(version: str = "1.0.0") -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "kind": "tiance-role-market",
        "name": "Test roles",
        "updatedAt": "2026-08-02T00:00:00Z",
        "roles": [{
            "id": "sample-role",
            "name": "示例角色",
            "version": version,
            "author": "LikeMirage",
            "summary": "示例角色。",
            "license": "CC0-1.0",
            "packageUrl": f"packages/sample-role-{version}.zip",
            "sha256": "0" * 64,
            "size": 1,
            "compatibility": {"minTianceVersion": "0.1.0"},
        }],
    }


def role_files(version: str = "1.0.0") -> dict[str, dict[str, object]]:
    files = {
        "manifest.json": {
            "schemaVersion": 1,
            "kind": "tiance-role-package",
            "id": "sample-role",
            "name": "示例角色",
            "version": version,
            "author": {"name": "LikeMirage"},
            "summary": "示例角色。",
            "license": "CC0-1.0",
            "compatibility": {"minTianceVersion": "0.1.0"},
        },
        "profile.json": {"description": f"版本 {version}"},
        "model.json": {"provider_id": "remote", "model_id": "preferred", "reasoning_mode": None},
        "generation.json": {"temperature": 0.5, "top_p": 0.9, "max_output_tokens": 1000},
        "prompt.json": {"system_prompt": f"prompt {version}"},
        "response.json": {
            "return_thinking_content": False,
            "return_cancelled_messages": True,
            "return_user_before_cancelled": False,
            "streaming_enabled": True,
            "auto_collapse_assistant_process": True,
        },
        "context.json": {"inject_message_timestamps": True},
        "memory.json": {
            "global_memory_enabled": True,
            "global_memory_extraction_enabled": True,
            "project_memory_enabled": True,
            "project_memory_extraction_enabled": True,
            "memory_compression_enabled": True,
            "memory_context_token_trigger_threshold": 250000,
            "memory_raw_context_token_reserve": 30000,
        },
        "tools.json": {"tools_enabled": True, "enabled_tool_names": ["missing-tool"], "max_tool_calls": 8},
    }
    return deepcopy(files)
