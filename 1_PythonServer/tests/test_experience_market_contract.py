from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil

import pytest

from app.core.errors import BadRequestError, ConflictError
from app.domain.project import ProjectKind
from app.infra.database import ensure_database_schema
from app.infra.project_market.remote_client import ProjectMarketConnectionError
from app.infra.projects import ProjectStorage
from app.repositories.project import FileProjectCatalog, ProjectRepository
from app.repositories.project.project_market_cache_repository import ProjectMarketCacheRepository
from app.repositories.project.project_market_settings_repository import (
    DEFAULT_EXPERIENCE_MARKET_SOURCE,
    ProjectMarketSettingsRepository,
)
from app.services.application.project_market import (
    ProjectMarketApplicationService,
    ProjectMarketPolicy,
)
from app.services.project.projects import ProjectService


OLD_PROJECT_ID = "22222222-2222-4222-8222-222222222222"


class FakeRemoteClient:
    def __init__(self, payload: dict[str, object] | None = None) -> None:
        self.payload = payload or experience_market_index()
        self.fail_index = False
        self.download_started = asyncio.Event()
        self.block_download = False

    async def fetch_index(self, _source: str) -> dict[str, object]:
        if self.fail_index:
            raise ProjectMarketConnectionError("网络失败")
        return self.payload

    async def download_package(self, *, target: Path, **_kwargs) -> str | None:
        self.download_started.set()
        if self.block_download:
            await asyncio.Event().wait()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"validated-by-fake")
        return None


class FakeArchive:
    def __init__(self, template_root: Path) -> None:
        self.template_root = template_root

    def validate_and_extract(self, *, staging_root: Path, **_kwargs) -> Path:
        target = staging_root / "extracted-experience"
        shutil.copytree(self.template_root, target)
        return target


class FakeCreationService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def ensure_initial_conversation(self, _project_id: str) -> None:
        if self.fail:
            raise RuntimeError("初始化失败")


def test_experience_market_settings_use_independent_default_source(tmp_path) -> None:
    path = tmp_path / "experience" / "market-settings.json"
    repository = ProjectMarketSettingsRepository(
        path,
        default_source=DEFAULT_EXPERIENCE_MARKET_SOURCE,
    )

    settings = repository.ensure_settings_file()

    assert settings.source == DEFAULT_EXPERIENCE_MARKET_SOURCE
    assert json.loads(path.read_text(encoding="utf-8"))["source"] == (
        DEFAULT_EXPERIENCE_MARKET_SOURCE
    )


def test_experience_market_accepts_empty_catalog_and_cached_network_fallback(tmp_path) -> None:
    service, remote, *_ = build_experience_market_service(
        tmp_path,
        payload=experience_market_index(projects=[]),
    )

    async def run() -> None:
        first = await service.get_index()
        assert first.kind == "tiance-experience-market"
        assert first.projects == []
        remote.fail_index = True
        cached = await service.get_index()
        assert cached.cached is True
        assert cached.projects == []

    asyncio.run(run())


@pytest.mark.parametrize(
    ("kind", "duplicate"),
    [
        ("tiance-project-market", False),
        ("tiance-knowledge-market", False),
        ("tiance-experience-market", True),
    ],
)
def test_experience_market_rejects_wrong_kind_and_duplicate_ids(
    tmp_path,
    kind: str,
    duplicate: bool,
) -> None:
    projects = [experience_market_entry()]
    if duplicate:
        projects.append(experience_market_entry())
    payload = experience_market_index(projects=projects)
    payload["kind"] = kind
    service, *_ = build_experience_market_service(tmp_path, payload=payload)

    with pytest.raises(BadRequestError):
        asyncio.run(service.get_index())


def test_experience_install_preserves_snapshot_and_rebinds_project_identity(tmp_path) -> None:
    template = tmp_path / "experience-template"
    conversations = template / ".Tiance" / "conversations"
    memory = template / ".Tiance" / "memory"
    conversations.mkdir(parents=True)
    memory.mkdir(parents=True)
    (template / "experience.md").write_text("experience", encoding="utf-8")
    (template / ".Tiance" / "project.json").write_text(json.dumps({
        "schema_version": 1,
        "project_id": OLD_PROJECT_ID,
        "name": "原经验项目",
    }), encoding="utf-8")
    (conversations / "index.json").write_text(json.dumps({
        "active_session_id": "session-1",
        "sessions": [{"session_id": "session-1", "project_id": OLD_PROJECT_ID}],
        "session_states": {
            "session-1": {
                "runtime_status": "running",
                "provider_id": "missing-provider",
                "model_id": "missing-model",
            },
        },
    }), encoding="utf-8")
    (conversations / "branch_graph.json").write_text(json.dumps({
        "nodes": [{"branch_id": "branch-1", "session_id": "session-1"}],
        "variants": [{"message_id": "message-1", "branch_id": "branch-1"}],
    }), encoding="utf-8")
    (memory / "project_memory.jsonl").write_text(
        json.dumps({"id": "memory-1", "project_id": OLD_PROJECT_ID}) + "\n",
        encoding="utf-8",
    )
    service, _, project_service, experience_root, _ = build_experience_market_service(
        tmp_path,
        template_root=template,
    )
    category = project_service.create_project_category(
        name="市场经验",
        category_kind=ProjectKind.EXPERIENCE,
    )

    operation = asyncio.run(install_and_wait(service, category.category_id))

    assert operation.phase == "completed"
    assert operation.result is not None
    project = project_service.get_project(operation.result.project_id)
    assert project is not None
    assert project.project_kind is ProjectKind.EXPERIENCE
    assert Path(project.root_path).parent == experience_root
    root = Path(project.root_path)
    identity = json.loads((root / ".Tiance" / "project.json").read_text())
    index = json.loads((root / ".Tiance" / "conversations" / "index.json").read_text())
    graph = json.loads((root / ".Tiance" / "conversations" / "branch_graph.json").read_text())
    memory_record = json.loads((root / ".Tiance" / "memory" / "project_memory.jsonl").read_text())
    origin = json.loads((root / ".Tiance" / "market.json").read_text())
    assert (root / "experience.md").read_text(encoding="utf-8") == "experience"
    assert identity["project_id"] == project.project_id != OLD_PROJECT_ID
    assert index["sessions"][0]["project_id"] == project.project_id
    assert index["session_states"]["session-1"]["runtime_status"] == "idle"
    assert index["session_states"]["session-1"]["provider_id"] == "missing-provider"
    assert graph["nodes"][0]["branch_id"] == "branch-1"
    assert graph["variants"][0]["message_id"] == "message-1"
    assert memory_record["id"] == "memory-1"
    assert memory_record["project_id"] == project.project_id
    assert origin["project_kind"] == "experience"


def test_experience_install_rejects_other_category_kinds(tmp_path) -> None:
    service, _, project_service, *_ = build_experience_market_service(tmp_path)
    for kind in (ProjectKind.PROJECT, ProjectKind.KNOWLEDGE):
        category = project_service.create_project_category(
            name=f"{kind.value} 分类",
            category_kind=kind,
        )
        with pytest.raises(BadRequestError, match="经验分类"):
            asyncio.run(service.start_install(
                market_project_id="experience-sample",
                category_id=category.category_id,
            ))


def test_experience_install_rejects_duplicate_market_project(tmp_path) -> None:
    service, _, project_service, *_ = build_experience_market_service(tmp_path)
    category = project_service.create_project_category(
        name="重复安装",
        category_kind=ProjectKind.EXPERIENCE,
    )
    assert asyncio.run(install_and_wait(service, category.category_id)).phase == "completed"

    with pytest.raises(ConflictError, match="已经安装"):
        asyncio.run(service.start_install(
            market_project_id="experience-sample",
            category_id=category.category_id,
        ))


def test_experience_install_failure_rolls_back_catalog_and_directory(tmp_path) -> None:
    service, _, project_service, experience_root, catalog = build_experience_market_service(
        tmp_path,
        creation_fails=True,
    )
    category = project_service.create_project_category(
        name="失败测试",
        category_kind=ProjectKind.EXPERIENCE,
    )

    operation = asyncio.run(install_and_wait(service, category.category_id))

    assert operation.phase == "failed"
    assert catalog.list_projects() == ()
    assert not [
        path for path in experience_root.iterdir()
        if path.is_dir() and path.name != ".market-cache"
    ]
    assert not list((experience_root / ".market-cache" / "operations").iterdir())


def test_experience_market_close_cancels_download_and_cleans_temporary_files(tmp_path) -> None:
    service, remote, project_service, experience_root, _ = build_experience_market_service(tmp_path)
    remote.block_download = True
    category = project_service.create_project_category(
        name="取消测试",
        category_kind=ProjectKind.EXPERIENCE,
    )

    async def run() -> None:
        operation = await service.start_install(
            market_project_id="experience-sample",
            category_id=category.category_id,
        )
        await asyncio.wait_for(remote.download_started.wait(), timeout=1)
        await service.close()
        assert service.get_operation(operation.operation_id).phase == "failed"

    asyncio.run(run())
    assert not list((experience_root / ".market-cache" / "operations").iterdir())


async def install_and_wait(service: ProjectMarketApplicationService, category_id: str):
    started = await service.start_install(
        market_project_id="experience-sample",
        category_id=category_id,
    )
    for _ in range(100):
        current = service.get_operation(started.operation_id)
        if current.phase in {"completed", "failed"}:
            return current
        await asyncio.sleep(0.01)
    raise AssertionError("安装任务未结束")


def build_experience_market_service(
    tmp_path: Path,
    *,
    payload: dict[str, object] | None = None,
    template_root: Path | None = None,
    creation_fails: bool = False,
):
    database_path = tmp_path / "tiance.db"
    projects_root = tmp_path / "projects"
    experience_root = tmp_path / "experience"
    ensure_database_schema(database_path)
    catalog = FileProjectCatalog(
        experience_root,
        project_kind=ProjectKind.EXPERIENCE,
    )
    repository = ProjectRepository(database_path, file_catalogs=(catalog,))
    project_service = ProjectService(
        repository,
        ProjectStorage(projects_root, experience_root=experience_root),
    )
    project_service.ensure_builtin_project_categories()
    if template_root is None:
        template_root = tmp_path / "default-template"
        template_root.mkdir(exist_ok=True)
        (template_root / "README.md").write_text("experience", encoding="utf-8")
    remote = FakeRemoteClient(payload)
    service = ProjectMarketApplicationService(
        settings_repository=ProjectMarketSettingsRepository(
            experience_root / "market-settings.json",
            default_source=DEFAULT_EXPERIENCE_MARKET_SOURCE,
        ),
        cache_repository=ProjectMarketCacheRepository(
            experience_root / ".market-cache",
        ),
        remote_client=remote,
        archive=FakeArchive(template_root),
        catalog=catalog,
        project_service=project_service,
        creation_service=FakeCreationService(fail=creation_fails),
        policy=ProjectMarketPolicy(
            project_kind=ProjectKind.EXPERIENCE,
            index_kind="tiance-experience-market",
            default_source=DEFAULT_EXPERIENCE_MARKET_SOURCE,
            preview_api_prefix="/api/experience/market/previews",
            category_error="请选择有效的经验分类。",
        ),
    )
    service.prepare()
    return service, remote, project_service, experience_root, catalog


def experience_market_entry() -> dict[str, object]:
    return {
        "id": "experience-sample",
        "name": "经验示例",
        "summary": "包含文件、会话、分支和记忆的经验项目。",
        "author": "LikeMirage",
        "version": "1.0.0",
        "updatedAt": "2026-08-02T00:00:00Z",
        "download": {
            "kind": "archive",
            "url": "packages/experience-sample.zip",
        },
        "tags": ["experience"],
        "stats": {"fileCount": 4, "conversationCount": 1, "branchCount": 1},
    }


def experience_market_index(
    *,
    projects: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "kind": "tiance-experience-market",
        "name": "Tiance Experience",
        "updatedAt": datetime.now(UTC).isoformat(),
        "defaultRef": "main",
        "projects": [experience_market_entry()] if projects is None else projects,
    }
