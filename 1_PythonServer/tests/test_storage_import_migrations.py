"""Storage-boundary upgrades preserve both historical facts and newer edits."""

from contextlib import closing
from dataclasses import asdict, replace
import json
from pathlib import Path
import sqlite3

import pytest

from app.infra.database.schema import ensure_database_schema
from app.migrations.catalogs.database import migrate_project_catalogs
from app.migrations.catalogs.workspace import upgrade_workspace_selection
from app.migrations.usage_db.storage import upgrade_usage_storage
from app.repositories.llm.provider_file_store import ProviderFileStore
from app.repositories.llm.usage_sqlite_store import UsageSqliteStore
from app.repositories.project.project_repository import ProjectRepository, COLLECTION_DIRECTORIES
from app.repositories.project.file_project_catalog import FileProjectCatalog
from app.services.llm.provider.storage_bootstrap import ensure_provider_file_storage
from tests.test_migration_history import GLOBAL_HISTORY
from tests.test_usage_batch_overview import _record


def _event(record):
    return json.dumps({"version": 1, "operation": "upsert", "record": asdict(record)}) + "\n"


def test_usage_import_replays_old_deletions_without_deleting_new_usage(tmp_path):
    old = _record()
    deleted = _record(usage_id="deleted", message_id="deleted", model_id="deleted-model")
    source = tmp_path / "usage_records.jsonl"
    content = _event(old) + _event(deleted) + json.dumps({
        "version": 1, "operation": "delete_model", "provider_id": "provider", "model_id": "deleted-model"}) + "\n"
    source.write_text(content, encoding="utf-8")
    store = UsageSqliteStore(tmp_path)
    newer = replace(deleted, usage_id="new", message_id="new", total_tokens=70)
    store.append_upsert(newer)
    upgrade_usage_storage(tmp_path)
    assert set(store.iter_records()) == {old, newer}
    with store.transaction() as db:
        store._verify_totals(db)
    assert source.read_text(encoding="utf-8") == content
    backups = list(tmp_path.glob("*.bak"))
    upgrade_usage_storage(tmp_path)
    assert list(tmp_path.glob("*.bak")) == backups
    assert set(store.iter_records()) == {old, newer}


def test_usage_import_failure_leaves_current_usage_and_retries(tmp_path):
    source = tmp_path / "usage_records.jsonl"
    source.write_text(_event(_record()) + "invalid\n", encoding="utf-8")
    store = UsageSqliteStore(tmp_path)
    newer = _record(usage_id="new", message_id="new")
    store.append_upsert(newer)
    with pytest.raises(ValueError, match="Invalid usage event"):
        upgrade_usage_storage(tmp_path)
    assert tuple(store.iter_records()) == (newer,)
    source.write_text(_event(_record()), encoding="utf-8")
    upgrade_usage_storage(tmp_path)
    assert set(store.iter_records()) == {newer, _record()}


def test_legacy_usage_database_rows_survive_global_upgrade_and_import(tmp_path):
    path = tmp_path / "global.db"
    with closing(sqlite3.connect(path)) as db:
        db.executescript(GLOBAL_HISTORY["45"])
        payload = asdict(_record(project_id=None, session_id=None))
        columns = {row[1] for row in db.execute("PRAGMA table_info(llm_usage_records)")}
        payload = {key: value for key, value in payload.items() if key in columns}
        db.execute(f"INSERT INTO llm_usage_records({','.join(payload)}) VALUES ({','.join('?' for _ in payload)})", tuple(payload.values()))
        db.commit()
    ensure_database_schema(path)
    upgrade_usage_storage(tmp_path / "usage", path)
    assert tuple(UsageSqliteStore(tmp_path / "usage").iter_records()) == (_record(project_id=None, session_id=None),)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT COUNT(*) FROM llm_usage_records").fetchone()[0] == 1


def test_all_seven_project_kinds_and_external_root_import_once(tmp_path):
    path = tmp_path / "global.db"
    catalogs = tuple(FileProjectCatalog(tmp_path / name, project_kind=kind,
                    allow_external_roots=kind.value == "project") for kind, name in COLLECTION_DIRECTORIES.items())
    repository = ProjectRepository(path, file_catalogs=catalogs)
    with closing(sqlite3.connect(path)) as db:
        db.executescript(GLOBAL_HISTORY["48"])
        for kind, name in COLLECTION_DIRECTORIES.items():
            identifier = f"p-{kind.value}"
            root = tmp_path / ("external" if kind.value == "project" else name) / identifier
            db.execute("INSERT INTO project_categories(category_id,name,category_kind,is_default,sort_order,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                       (f"c-{kind.value}", name, kind.value, 0, 0, "2026-01-01", "2026-01-01"))
            db.execute("INSERT INTO projects(project_id,name,root_path,category_id,project_kind,is_default,sort_order,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                       (identifier, name, str(root), f"c-{kind.value}", kind.value, 0, 0, "2026-01-01", "2026-01-01"))
        db.execute("INSERT INTO app_metadata VALUES ('workspace.last_opened',?,'2026-01-01')",
                   (json.dumps({"project_id": "p-project", "session_id": "session", "updated_at": "2026-01-01"}),))
        db.commit()
    ensure_database_schema(path)
    migrate_project_catalogs(path, repository)
    assert len(repository.list_projects()) == 7
    assert {f"c-{kind.value}" for kind in COLLECTION_DIRECTORIES} <= {row.category_id for row in repository.list_project_categories()}
    project = repository.get_project("p-project")
    assert Path(project.root_path).parent.name == "external"
    repository.save_project(replace(project, name="edited after import"))
    migrate_project_catalogs(path, repository)
    assert repository.get_project("p-project").name == "edited after import"
    upgrade_workspace_selection(path, repository)
    payload = json.loads(repository.get_metadata_value("workspace.last_opened"))
    assert payload["active_category_id"] == "c-project"
    assert payload["category_selections"]["c-project"]["session_id"] == "session"
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 7


def test_old_provider_files_keep_custom_endpoints_auth_and_credentials(tmp_path):
    store = ProviderFileStore(tmp_path)
    manifest = {"schemaVersion": 1, "id": "custom", "displayName": "Custom", "profileId": "generic",
                "protocolFamily": "openai_compatible", "apiBaseUrl": "https://custom.example/api/chat/completions",
                "authScheme": "x_api_key", "enabled": True, "createdAt": "old", "updatedAt": "old"}
    store.write_provider_file("custom", "provider.json", manifest)
    credentials = {"schemaVersion": 1, "items": [{"ciphertext": "test-only-ciphertext"}]}
    store.write_provider_file("custom", "credentials.json", credentials)
    store.write_provider_file("custom", "provider-rules.json", {"schemaVersion": 1, "capabilities": {}, "request": {}})
    store.write_provider_file("custom", "model-rules.json", {"schemaVersion": 1, "families": {}, "models": {}})
    store.write_settings({"schemaVersion": 1, "providerOrder": ["custom"], "providerPresetCatalogVersion": 2})
    ensure_provider_file_storage(tmp_path)
    upgraded = store.read_provider_file("custom", "provider.json")
    assert upgraded["generationUrls"]["openai_compatible"] == manifest["apiBaseUrl"]
    assert upgraded["generationAuthSchemes"]["openai_compatible"] == "x_api_key"
    assert upgraded["modelDiscoveryUrl"] == "https://custom.example/api/models"
    assert store.read_provider_file("custom", "credentials.json") == credentials
    assert len(list((tmp_path / "custom").glob("provider.json.*.bak"))) == 1
    before = (tmp_path / "custom/provider.json").read_bytes()
    ensure_provider_file_storage(tmp_path)
    assert (tmp_path / "custom/provider.json").read_bytes() == before


def test_deleted_default_project_is_not_recreated_by_catalog_import(tmp_path):
    from app.domain.project import ProjectKind
    path = tmp_path / "global.db"
    ensure_database_schema(path)
    repository = ProjectRepository(path)
    repository.set_metadata_value(key="projects.default_project_bootstrapped", value="1", updated_at="old")
    migrate_project_catalogs(path, repository)
    assert repository.list_projects() == ()
    assert repository.get_catalog_metadata_value(ProjectKind.PROJECT, "projects.default_project_bootstrapped") == "1"


def test_legacy_provider_database_export_after_cross_version_upgrade(tmp_path):
    path = tmp_path / "global.db"
    with closing(sqlite3.connect(path)) as db:
        db.executescript(GLOBAL_HISTORY["27"])
        db.execute("INSERT INTO custom_provider_catalog(provider_id,display_name,upstream_key,protocol_family,auth_scheme,supports_custom_base_url,api_base_url,created_at,updated_at) VALUES ('custom','Custom','generic','openai_compatible','bearer_token',1,'https://custom.example/chat/completions','old','old')")
        db.execute("INSERT INTO provider_configs VALUES ('custom','https://custom.example/chat/completions',1,'old','old')")
        db.execute("INSERT INTO provider_configs VALUES ('openai','https://proxy.example/v1/responses',1,'old','old')")
        columns = {row[1] for row in db.execute("PRAGMA table_info(provider_config_api_keys)")}
        values = {"key_id": "key", "provider_id": "custom", "api_key_hint": "test", "api_key_ciphertext": "ciphertext",
                  "poll_weight": 2, "sort_order": 0, "created_at": "old", "updated_at": "old"}
        assert columns == values.keys()
        db.execute(f"INSERT INTO provider_config_api_keys({','.join(values)}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))
        db.commit()
    ensure_database_schema(path)
    ensure_provider_file_storage(tmp_path / "providers", path)
    store = ProviderFileStore(tmp_path / "providers")
    assert store.read_provider_file("custom", "provider.json")["generationUrls"]["openai_compatible"] == "https://custom.example/chat/completions"
    assert store.read_provider_file("custom", "credentials.json")["items"][0]["ciphertext"] == "ciphertext"
    preset = store.read_provider_file("openai", "provider.json")
    assert preset["generationUrls"][preset["protocolFamily"]] == "https://proxy.example/v1/responses"
    assert preset["modelDiscoveryUrl"] == "https://proxy.example/v1/models"
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT COUNT(*) FROM provider_config_api_keys").fetchone()[0] == 1


def test_fresh_provider_files_need_no_migration_on_second_start(tmp_path):
    from app.migrations.providers.endpoints import provider_endpoint_storage_version_fields
    from app.repositories.llm.provider_file_store import PROVIDER_FORMAT_VERSIONS
    assert PROVIDER_FORMAT_VERSIONS == provider_endpoint_storage_version_fields()
    ensure_provider_file_storage(tmp_path)
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*.json")}
    ensure_provider_file_storage(tmp_path)
    assert before == {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*.json")}
    assert not list(tmp_path.rglob("*.bak"))


def test_current_endpoint_takes_precedence_over_leftover_legacy_field():
    from app.migrations.providers.endpoints import initialize_provider_manifest_endpoints
    manifest = {"protocolFamily": "openai_compatible", "apiBaseUrl": "https://old.example/chat/completions",
                "generationUrls": {"openai_compatible": "https://new.example/chat/completions"}}
    initialize_provider_manifest_endpoints(manifest, preset_manifest=None, updated_at="now")
    assert manifest["generationUrls"]["openai_compatible"] == "https://new.example/chat/completions"


@pytest.mark.skipif(not hasattr(Path, "is_junction"), reason="Project path checks use the bundled Python 3.13")
def test_legacy_theme_import_resumes_initialization_without_duplicate_project(tmp_path):
    from app.migrations.catalogs.themes import LegacyCollectionProjectMigrationService
    from app.infra.projects.project_storage import ProjectStorage
    from app.services.project.projects import ProjectService
    from tests.test_theme_workspace_reconciliation import _write_theme
    path = tmp_path / "global.db"
    ensure_database_schema(path)
    repository = ProjectRepository(path)
    root = tmp_path / "themes"
    _write_theme(root / "custom", theme_id="custom", name="Keep theme")
    storage = ProjectStorage(tmp_path / "projects", themes_root=root)
    calls = []
    def initialize(identifier):
        calls.append(identifier)
        if len(calls) == 1:
            raise RuntimeError("interrupted after registration")
    service = LegacyCollectionProjectMigrationService(
        project_service=ProjectService(repository, storage), project_repository=repository,
        project_storage=storage, themes_root=root, conversation_initializer=initialize,
    )
    with pytest.raises(RuntimeError, match="interrupted"):
        service.migrate_once()
    service.migrate_once()
    service.migrate_once()
    assert len(repository.list_projects()) == 1
    assert len(calls) == 2 and calls[0] == calls[1]
    assert (root / "custom/theme.json").is_file()
