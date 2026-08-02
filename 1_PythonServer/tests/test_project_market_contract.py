from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
from stat import S_IFLNK
from zipfile import ZipFile, ZipInfo

import pytest

from app.core.errors import BadRequestError, ConflictError
from app.domain.project import ProjectKind
from app.infra.database import ensure_database_schema
from app.infra.project_market.package_archive import ProjectPackageArchive
from app.infra.project_market.remote_client import (
    ProjectMarketConnectionError,
    ProjectMarketRemoteClient,
    normalize_project_market_source,
    resolve_project_download,
)
from app.infra.projects import ProjectStorage
from app.repositories.project import FileProjectCatalog, ProjectRepository
from app.repositories.project.project_market_cache_repository import (
    ProjectMarketCacheRepository,
)
from app.repositories.project.project_market_settings_repository import (
    DEFAULT_PROJECT_MARKET_SOURCE,
    ProjectMarketSettingsRepository,
)
from app.schemas.project.project_market import (
    ProjectMarketDownload,
    ProjectMarketFilterSettings,
)
from app.services.application.project_market import (
    ProjectMarketApplicationService,
    ProjectMarketPolicy,
)
from app.services.application.project_market_snapshot import (
    prepare_project_market_snapshot,
)
from app.services.project.projects import ProjectService


OLD_PROJECT_ID = "11111111-1111-4111-8111-111111111111"
GITHUB_PROJECT_SOURCE = "https://github.com/LikeMirage/Tiance-projects.git"


class FakeRemoteClient:
    def __init__(self, *, fail_index: bool = False) -> None:
        self.fail_index = fail_index
        self.sources: list[str] = []
        self.download_calls = 0

    async def fetch_index(self, source: str) -> dict[str, object]:
        self.sources.append(source)
        if self.fail_index:
            raise ProjectMarketConnectionError("网络失败")
        return project_market_index()

    async def download_package(self, *, target: Path, **_kwargs) -> str | None:
        self.download_calls += 1
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"validated-by-fake")
        return None


class FakeArchive:
    def __init__(self, template_root: Path) -> None:
        self.template_root = template_root

    def validate_and_extract(self, *, staging_root: Path, **_kwargs) -> Path:
        root = staging_root / "extracted-project"
        shutil.copytree(self.template_root, root)
        return root


class FakeCreationService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    def ensure_initial_conversation(self, project_id: str) -> None:
        self.calls.append(project_id)
        if self.fail:
            raise RuntimeError("初始化失败")


def test_project_market_settings_are_created_and_saved(tmp_path) -> None:
    settings_path = tmp_path / "projects" / "market-settings.json"
    repository = ProjectMarketSettingsRepository(settings_path)

    initial = repository.ensure_settings_file()
    saved = repository.save_filters(ProjectMarketFilterSettings(
        authors=["LikeMirage"],
        tags=["workflow"],
        statuses=["not-installed"],
    ))

    assert initial.source == DEFAULT_PROJECT_MARKET_SOURCE
    assert saved.filters.tags == ["workflow"]
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert payload["source"] == DEFAULT_PROJECT_MARKET_SOURCE
    assert payload["filters"]["authors"] == ["LikeMirage"]


def test_project_market_custom_and_default_source_switch(tmp_path) -> None:
    service, remote, *_ = build_market_service(tmp_path)

    async def run() -> None:
        custom = await service.connect("https://example.com/projects")
        assert custom.source == "https://example.com/projects"
        restored = await service.restore_default_source()
        assert restored.source == DEFAULT_PROJECT_MARKET_SOURCE

    asyncio.run(run())
    assert remote.sources == ["https://example.com/projects", DEFAULT_PROJECT_MARKET_SOURCE]


def test_project_market_download_inherits_index_default_ref() -> None:
    url, subdirectory = resolve_project_download(
        GITHUB_PROJECT_SOURCE,
        ProjectMarketDownload(kind="github-directory", path="projects/example"),
        default_ref="release",
    )

    assert url.endswith("/zip/release")
    assert subdirectory == "projects/example"


def test_project_market_remote_client_uses_repository_default_branch(monkeypatch) -> None:
    client = ProjectMarketRemoteClient()
    payload = project_market_index()
    payload.pop("defaultRef")
    calls: list[tuple[str, str | None]] = []

    class FakeGithubClient:
        async def get_repository_default_branch(self, repository) -> str:
            assert repository.repository == "Tiance-projects"
            return "master"

        async def fetch_repository_file(self, _repository, path: str, *, ref: str, **_kwargs):
            calls.append((path, ref))
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(
        "app.infra.project_market.remote_client.get_github_client",
        lambda: FakeGithubClient(),
    )
    result = asyncio.run(client.fetch_index(GITHUB_PROJECT_SOURCE))

    assert calls == [("index.json", "master")]
    assert result["defaultRef"] == "master"


def test_project_market_pages_source_uses_shared_index_contract() -> None:
    source = normalize_project_market_source(
        "https://example.com/markets/projects/index.json"
    )

    assert source == "https://example.com/markets/projects"


def test_project_market_rejects_parent_directory_download_path() -> None:
    with pytest.raises(BadRequestError, match="项目目录路径无效"):
        resolve_project_download(
            GITHUB_PROJECT_SOURCE,
            ProjectMarketDownload(kind="github-directory", path="../private"),
            default_ref="main",
        )


def test_project_market_uses_cached_index_only_for_network_failure(tmp_path) -> None:
    service, remote, *_ = build_market_service(tmp_path)

    async def run() -> None:
        first = await service.get_index()
        assert first.cached is False
        remote.fail_index = True
        cached = await service.get_index()
        assert cached.cached is True
        assert cached.projects[0].id == "sample-project"

    asyncio.run(run())


def test_project_archive_accepts_direct_files_and_single_outer_directory(tmp_path) -> None:
    direct_archive = tmp_path / "direct.zip"
    with ZipFile(direct_archive, "w") as archive:
        archive.writestr("README.md", "direct")
        archive.writestr("src/main.py", "print('ok')")
    direct_root = ProjectPackageArchive().validate_and_extract(
        archive_path=direct_archive,
        staging_root=tmp_path / "direct-stage",
    )
    assert (direct_root / "README.md").read_text() == "direct"

    outer_archive = tmp_path / "outer.zip"
    with ZipFile(outer_archive, "w") as archive:
        archive.writestr("shared-project/README.md", "outer")
    outer_root = ProjectPackageArchive().validate_and_extract(
        archive_path=outer_archive,
        staging_root=tmp_path / "outer-stage",
    )
    assert outer_root.name == "shared-project"


def test_project_archive_rejects_path_traversal_and_links(tmp_path) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.txt", "unsafe")

    with pytest.raises(BadRequestError, match="越界路径"):
        ProjectPackageArchive().validate_and_extract(
            archive_path=archive_path,
            staging_root=tmp_path / "stage",
        )
    assert not (tmp_path / "outside.txt").exists()

    link_archive_path = tmp_path / "link.zip"
    link = ZipInfo("shared-project/link")
    link.create_system = 3
    link.external_attr = (S_IFLNK | 0o777) << 16
    with ZipFile(link_archive_path, "w") as archive:
        archive.writestr(link, "README.md")

    with pytest.raises(BadRequestError, match="链接"):
        ProjectPackageArchive().validate_and_extract(
            archive_path=link_archive_path,
            staging_root=tmp_path / "link-stage",
        )


def test_snapshot_rebinds_only_project_identity_and_stops_runtime(tmp_path) -> None:
    root = tmp_path / "snapshot"
    conversations = root / ".Tiance" / "conversations"
    memory = root / ".Tiance" / "memory"
    conversations.mkdir(parents=True)
    memory.mkdir(parents=True)
    (root / ".Tiance" / "project.json").write_text(json.dumps({
        "schema_version": 1,
        "project_id": OLD_PROJECT_ID,
        "name": "原项目",
    }), encoding="utf-8")
    (conversations / "index.json").write_text(json.dumps({
        "active_session_id": "session-1",
        "sessions": [{"session_id": "session-1", "project_id": OLD_PROJECT_ID}],
        "session_states": {
            "session-1": {"runtime_status": "running", "provider_id": "missing-provider"},
        },
    }), encoding="utf-8")
    (conversations / "branch_graph.json").write_text(json.dumps({
        "nodes": [{"branch_id": "branch-1", "session_id": "session-1"}],
        "variants": [{"message_id": "message-1", "branch_id": "branch-1"}],
    }), encoding="utf-8")
    (memory / "project_memory.jsonl").write_text(
        json.dumps({"id": "memory-1", "project_id": OLD_PROJECT_ID}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    task_path = conversations / "memory_compaction_task.json"
    task_path.write_text(json.dumps({"status": "running", "project_id": OLD_PROJECT_ID}), encoding="utf-8")
    new_project_id = "22222222-2222-4222-8222-222222222222"

    prepare_project_market_snapshot(
        root,
        project_id=new_project_id,
        project_name="导入项目",
        market_project_id="sample-project",
        source=DEFAULT_PROJECT_MARKET_SOURCE,
        version="1.0.0",
        installed_at="2026-08-02T00:00:00+00:00",
        project_kind=ProjectKind.PROJECT,
    )

    index = json.loads((conversations / "index.json").read_text(encoding="utf-8"))
    graph = json.loads((conversations / "branch_graph.json").read_text(encoding="utf-8"))
    memory_record = json.loads((memory / "project_memory.jsonl").read_text(encoding="utf-8"))
    task = json.loads(task_path.read_text(encoding="utf-8"))
    assert index["sessions"][0]["project_id"] == new_project_id
    assert index["session_states"]["session-1"]["runtime_status"] == "idle"
    assert index["session_states"]["session-1"]["provider_id"] == "missing-provider"
    assert graph["nodes"][0]["branch_id"] == "branch-1"
    assert graph["variants"][0]["message_id"] == "message-1"
    assert memory_record["id"] == "memory-1"
    assert memory_record["project_id"] == new_project_id
    assert task["status"] == "failed"


def test_plain_folder_installs_as_new_managed_project_in_selected_category(tmp_path) -> None:
    template = tmp_path / "plain-template"
    template.mkdir()
    (template / "README.md").write_text("shared project", encoding="utf-8")
    service, remote, project_service, creation, projects_root, _ = build_market_service(
        tmp_path,
        template_root=template,
    )
    category = project_service.create_project_category(name="下载项目")

    operation = asyncio.run(install_and_wait(service, category.category_id))

    assert operation.phase == "completed"
    assert operation.result is not None
    project = project_service.get_project(operation.result.project_id)
    assert project is not None
    assert project.category_id == category.category_id
    assert Path(project.root_path).parent == projects_root
    assert (Path(project.root_path) / "README.md").read_text(encoding="utf-8") == "shared project"
    assert (Path(project.root_path) / ".Tiance" / "project.json").is_file()
    assert creation.calls == [project.project_id]
    assert remote.download_calls == 1


def test_duplicate_install_is_rejected_while_operation_is_active(tmp_path) -> None:
    service, _, project_service, _, _, _ = build_market_service(tmp_path)
    category = project_service.create_project_category(name="市场")

    async def run() -> None:
        started = await service.start_install(
            market_project_id="sample-project",
            category_id=category.category_id,
        )
        with pytest.raises(ConflictError):
            await service.start_install(
                market_project_id="sample-project",
                category_id=category.category_id,
            )
        for _ in range(100):
            if service.get_operation(started.operation_id).phase in {"completed", "failed"}:
                return
            await asyncio.sleep(0.01)
        raise AssertionError("安装任务未结束")

    asyncio.run(run())


def test_snapshot_old_project_id_never_conflicts_with_new_local_identity(tmp_path) -> None:
    template = tmp_path / "snapshot-template"
    (template / ".Tiance").mkdir(parents=True)
    (template / ".Tiance" / "project.json").write_text(json.dumps({
        "schema_version": 1,
        "project_id": OLD_PROJECT_ID,
        "name": "原项目",
    }), encoding="utf-8")
    service, _, project_service, _, _, _ = build_market_service(tmp_path, template_root=template)
    category = project_service.create_project_category(name="市场")

    operation = asyncio.run(install_and_wait(service, category.category_id))

    assert operation.result is not None
    assert operation.result.project_id != OLD_PROJECT_ID


def test_install_failure_rolls_back_catalog_and_formal_directory(tmp_path) -> None:
    template = tmp_path / "plain-template"
    template.mkdir()
    (template / "README.md").write_text("shared project", encoding="utf-8")
    service, _, project_service, _, projects_root, catalog = build_market_service(
        tmp_path,
        template_root=template,
        creation_fails=True,
    )
    category = project_service.create_project_category(name="失败测试")
    before = {project.project_id for project in catalog.list_projects()}

    operation = asyncio.run(install_and_wait(service, category.category_id))

    after = {project.project_id for project in catalog.list_projects()}
    assert operation.phase == "failed"
    assert after == before
    assert not list((projects_root / ".market-cache" / "operations").iterdir())
    assert all(path.name in {"catalog.json", "market-settings.json", ".market-cache"} or path.name in before
               for path in projects_root.iterdir())


async def install_and_wait(
    service: ProjectMarketApplicationService,
    category_id: str,
):
    started = await service.start_install(
        market_project_id="sample-project",
        category_id=category_id,
    )
    for _ in range(100):
        current = service.get_operation(started.operation_id)
        if current.phase in {"completed", "failed"}:
            return current
        await asyncio.sleep(0.01)
    raise AssertionError("安装任务未结束")


def build_market_service(
    tmp_path: Path,
    *,
    template_root: Path | None = None,
    creation_fails: bool = False,
):
    database_path = tmp_path / "tiance.db"
    projects_root = tmp_path / "projects"
    ensure_database_schema(database_path)
    catalog = FileProjectCatalog(
        projects_root,
        project_kind=ProjectKind.PROJECT,
        allow_external_roots=True,
    )
    repository = ProjectRepository(database_path, file_catalogs=(catalog,))
    project_service = ProjectService(repository, ProjectStorage(projects_root))
    if template_root is None:
        template_root = tmp_path / "default-template"
        template_root.mkdir(exist_ok=True)
        (template_root / "README.md").write_text("project", encoding="utf-8")
    remote = FakeRemoteClient()
    creation = FakeCreationService(fail=creation_fails)
    service = ProjectMarketApplicationService(
        settings_repository=ProjectMarketSettingsRepository(
            projects_root / "market-settings.json"
        ),
        cache_repository=ProjectMarketCacheRepository(
            projects_root / ".market-cache"
        ),
        remote_client=remote,
        archive=FakeArchive(template_root),
        catalog=catalog,
        project_service=project_service,
        creation_service=creation,
        policy=ProjectMarketPolicy(
            project_kind=ProjectKind.PROJECT,
            index_kind="tiance-project-market",
            default_source=DEFAULT_PROJECT_MARKET_SOURCE,
            preview_api_prefix="/api/projects/market/previews",
            category_error="请选择有效的普通项目分类。",
        ),
    )
    service.prepare()
    return service, remote, project_service, creation, projects_root, catalog


def project_market_index() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "kind": "tiance-project-market",
        "name": "Test projects",
        "updatedAt": datetime.now(UTC).isoformat(),
        "defaultRef": "main",
        "projects": [{
            "id": "sample-project",
            "name": "示例项目",
            "summary": "完整项目快照。",
            "author": "LikeMirage",
            "version": "1.0.0",
            "updatedAt": "2026-08-02T00:00:00Z",
            "download": {
                "kind": "archive",
                "url": "packages/sample-project.zip",
                "ref": "main",
            },
            "tags": ["workflow"],
            "stats": {"fileCount": 3, "conversationCount": 1, "branchCount": 2},
        }],
    }
