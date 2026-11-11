from contextlib import closing
from datetime import UTC, datetime
from uuid import uuid4
from json import dumps, loads
from pathlib import Path
import sqlite3

import pytest

from app.api.routes.project import conversations as routes
from app.core.errors import NotFoundError
from app.domain.project import Project, ProjectKind
from app.infra.database.schema import ensure_database_schema
from app.infra.file_workspace import FileWorkspaceStorage
from app.infra.projects import ProjectStorage
from app.repositories.project.conversation_repository import ProjectConversationRepository
from app.repositories.roles.default_role_repository import DefaultRoleRepository
from app.schemas.project.project_conversations import ProjectConversationCreateRequest
from app.services.application.project_creation import ProjectCreationApplicationService
from app.services.application.role_configuration import RoleConfigurationApplicationService
from app.services.document_conversion import MarkdownDocxService
from app.services.project.project_conversations import ProjectConversationService
from app.services.project.project_files import ProjectFileService
from app.services.project.projects import ProjectService
from tests.project_test_support import make_project_repository


@pytest.fixture
def services(tmp_path, monkeypatch):
    database = tmp_path / "global.db"
    ensure_database_schema(database)
    repository = make_project_repository(database)
    projects = ProjectService(repository, ProjectStorage(
        tmp_path / "projects", **{f"{kind}_root": tmp_path / kind for kind in (
            "roles", "themes", "tools", "knowledge", "experience", "providers",
        )},
    ))
    conversations = ProjectConversationService(ProjectConversationRepository(repository))
    files = ProjectFileService(repository, FileWorkspaceStorage(), MarkdownDocxService())
    defaults = DefaultRoleRepository(database)
    roles = RoleConfigurationApplicationService(projects, conversations, files, defaults)
    creation = ProjectCreationApplicationService(projects, conversations, files, defaults)
    monkeypatch.setattr(routes, "get_project_service", lambda: projects)
    monkeypatch.setattr(routes, "get_project_conversation_service", lambda: conversations)
    monkeypatch.setattr(routes, "get_role_configuration_application_service", lambda: roles)
    original_create = projects.create_project
    def create_project(*, name, project_kind=ProjectKind.PROJECT, **kwargs):
        if project_kind is not ProjectKind.PROVIDER:
            return original_create(name=name, project_kind=project_kind, **kwargs)
        # ProviderWorkspaceRegistryService registers provider directories in this same catalog.
        category = next((item for item in projects.list_project_categories() if item.category_kind is project_kind), None)
        if category is None:
            category = projects.create_project_category(name="供应商", category_kind=project_kind)
        project_id = str(uuid4())
        directory = tmp_path / "providers" / project_id
        directory.mkdir(parents=True)
        now = datetime.now(UTC).isoformat()
        return repository.save_project(Project(project_id, name, str(directory), False, 0, now, now,
            category_id=category.category_id, project_kind=project_kind))
    monkeypatch.setattr(projects, "create_project", create_project)
    return projects, conversations, roles, creation


@pytest.mark.parametrize("kind", list(ProjectKind))
def test_collection_defaults_apply_to_initial_and_new_conversations_only(services, kind):
    projects, conversations, roles, creation = services
    baseline = roles.ensure_default_role()
    chosen = projects.create_role_project(name="用户选择", category_id=None)
    roles.initialize_role_project(chosen.project_id)
    prompt = Path(chosen.root_path) / "prompt.json"
    prompt.write_text(dumps({"system_prompt": "只属于选定的集"}), encoding="utf-8")
    target = projects.create_project(name="目标", project_kind=kind)
    old = routes.create_project_conversation(target.project_id, ProjectConversationCreateRequest())
    roles.set_default_role(kind, chosen.project_id)
    new = routes.create_project_conversation(target.project_id, ProjectConversationCreateRequest())
    assert new.role_project_id == chosen.project_id
    assert new.settings.system_prompt == "只属于选定的集"
    assert conversations.get_session(target.project_id, old.session_id).role_project_id == baseline.project_id
    explicit = routes.create_project_conversation(target.project_id, ProjectConversationCreateRequest(role_project_id=baseline.project_id))
    assert explicit.role_project_id == baseline.project_id
    another = projects.create_project(name="首个会话", project_kind=kind)
    initial = creation.ensure_initial_conversation(another.project_id)
    assert initial.role_project_id == chosen.project_id
    assert creation.ensure_initial_conversation(another.project_id) is None
    defaults = roles.get_default_roles()
    assert defaults[kind.value] == chosen.project_id
    assert all(value == baseline.project_id for key, value in defaults.items() if key != kind.value)


def test_role_author_does_not_become_new_role_content(services):
    projects, conversations, roles, creation = services
    baseline = roles.ensure_default_role()
    creator = projects.create_role_project(name="角色创建者", category_id=None)
    roles.initialize_role_project(creator.project_id)
    (Path(creator.root_path) / "prompt.json").write_text(dumps({"system_prompt": "协助设计角色"}), encoding="utf-8")
    roles.set_default_role(ProjectKind.ROLE, creator.project_id)
    target = creation.create_role_project(name="翻译员")
    first = conversations.list_sessions(target.project_id)[0]
    assert first.role_project_id == creator.project_id
    assert first.settings.system_prompt == "协助设计角色"
    assert loads((Path(target.root_path) / "prompt.json").read_text(encoding="utf-8")) == loads(
        (Path(baseline.root_path) / "prompt.json").read_text(encoding="utf-8")
    )


def test_unknown_role_is_rejected_without_changing_any_collection(services):
    projects, _, roles, _ = services
    before = roles.get_default_roles()
    ordinary = projects.create_project(name="不是角色")
    for role_id in (str(uuid4()), ordinary.project_id):
        with pytest.raises(NotFoundError):
            roles.set_default_role(ProjectKind.TOOL, role_id)
    assert roles.get_default_roles() == before


def make_v49(database, role_payload):
    # Use the actual previous schema shape, retaining an unrelated functional profile.
    ensure_database_schema(database)
    with closing(sqlite3.connect(database)) as db:
        db.execute("DROP TABLE collection_default_roles")
        db.execute("DROP TABLE mobile_records")
        db.execute("DROP TABLE mobile_receipts")
        db.execute("DROP TABLE mobile_connections")
        db.execute("DELETE FROM schema_migrations")
        db.execute("INSERT INTO schema_migrations VALUES (49, 'previous', 'now')")
        db.execute("INSERT INTO llm_functional_model_settings VALUES ('defaultConversation',26,?,'now','now')", (dumps(role_payload),))
        db.commit()


def test_existing_choice_moves_once_and_later_changes_survive_restart(tmp_path):
    database = tmp_path / "global.db"
    make_v49(database, {"roleProjectId": "user-role"})
    ensure_database_schema(database)
    repository = DefaultRoleRepository(database)
    assert repository.get_all() == {kind.value: "user-role" for kind in ProjectKind}
    repository.save(ProjectKind.TOOL, "tool-author")
    repository.save(ProjectKind.THEME, "theme-author")
    ensure_database_schema(database)
    assert repository.get_all()["tool"] == "tool-author"
    assert repository.get_all()["theme"] == "theme-author"
    assert repository.get_all()["project"] == "user-role"
    with closing(sqlite3.connect(database)) as db:
        assert not db.execute("SELECT 1 FROM llm_functional_model_settings WHERE settings_id='defaultConversation'").fetchone()
    assert len(list(tmp_path.glob("*.bak"))) == 1


def test_failed_move_rolls_back_table_and_version_then_can_retry(tmp_path):
    database = tmp_path / "global.db"
    make_v49(database, {"roleProjectId": ["invalid"]})
    with pytest.raises(ValueError):
        ensure_database_schema(database)
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 49
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='collection_default_roles'").fetchone()
        db.execute("UPDATE llm_functional_model_settings SET settings_json=? WHERE settings_id='defaultConversation'", (dumps({"roleProjectId": "fixed"}),))
        db.commit()
    ensure_database_schema(database)
    assert DefaultRoleRepository(database).get_all()["tool"] == "fixed"


def test_public_initial_defaults_do_not_override_saved_choices(tmp_path):
    database = tmp_path / "global.db"
    ensure_database_schema(database)
    template = tmp_path / "initial-defaults.json"
    repository = DefaultRoleRepository(database, initial_defaults_path=template)
    assert repository.get_all() == {}
    template.write_text(dumps({"schemaVersion": 1, "defaults": {
        "tool": "tool-author", "role": "role-author",
    }}), encoding="utf-8")
    assert repository.get_all() == {"tool": "tool-author", "role": "role-author"}
    repository.save(ProjectKind.TOOL, "chosen-by-user")
    assert repository.get_all() == {"tool": "chosen-by-user", "role": "role-author"}
    for kind in ProjectKind:
        repository.save(kind, "migrated-user-choice")
    # A complete set of user choices is independent of the optional install template.
    template.write_text("not valid json", encoding="utf-8")
    assert repository.get_all() == {kind.value: "migrated-user-choice" for kind in ProjectKind}


@pytest.mark.parametrize("payload", [[], {"schemaVersion": 1, "defaults": []},
    {"schemaVersion": 1, "defaults": {"settings": "role"}},
    {"schemaVersion": 1, "defaults": {"tool": 3}}])
def test_invalid_public_initial_defaults_are_reported(tmp_path, payload):
    database = tmp_path / "global.db"
    ensure_database_schema(database)
    template = tmp_path / "initial-defaults.json"
    template.write_text(dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        DefaultRoleRepository(database, initial_defaults_path=template).get_all()
