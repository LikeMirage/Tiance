from dataclasses import asdict
from json import dumps
from pathlib import Path
import asyncio

import pytest

from app.api.routes.project import conversations as routes
from app.core.errors import NotFoundError
from app.schemas.project.project_conversations import ProjectConversationCreateRequest, ProjectConversationSessionUpdateRequest
from app.schemas.project.project_conversations import ProjectConversationCloneRequest
from app.services.application import conversation_configuration
from tests.test_collection_default_roles import services


def prepare(services, monkeypatch):
    projects, conversations, roles, creation = services
    monkeypatch.setattr(conversation_configuration, "get_role_configuration_application_service", lambda: roles)
    role = creation.create_role_project(name="role")
    root = Path(role.root_path)
    (root / "prompt.json").write_text(dumps({"system_prompt": "role prompt"}), encoding="utf-8")
    (root / "model.json").write_text(dumps({"provider_id": "role-provider", "model_id": "role-model", "reasoning_mode": None}), encoding="utf-8")
    project = projects.create_project(name="target")
    parent = conversations.create_session(project.project_id, provider_id="parent-provider", model_id="parent-model",
        reasoning_mode="high", settings={"system_prompt": "parent prompt", "global_memory_enabled": False})
    return project, parent, role


def test_role_is_complete_base_and_explicit_caller_model_is_last(services, monkeypatch):
    project, parent, role = prepare(services, monkeypatch)
    exact = routes.create_project_conversation(project.project_id, ProjectConversationCreateRequest(
        created_by="ai", parent_session_id=parent.session_id, activate=False, role_project_id=role.project_id))
    assert exact.provider_id == "role-provider" and exact.model_id == "role-model"
    assert exact.reasoning_mode is None
    assert exact.settings.system_prompt == "role prompt"
    assert exact.role_project_id == role.project_id
    custom = routes.create_project_conversation(project.project_id, ProjectConversationCreateRequest(
        created_by="ai", parent_session_id=parent.session_id, activate=False, role_project_id=role.project_id,
        provider_id=parent.provider_id, model_id=parent.model_id, reasoning_mode=None,
        settings={"system_prompt": "override"}))
    assert custom.model_id == parent.model_id and custom.reasoning_mode is None
    assert custom.settings.system_prompt == "override"
    assert custom.role_project_id is None
    assert services[1].get_session(project.project_id, parent.session_id).reasoning_mode == "high"


def test_no_model_in_role_does_not_secretly_fall_back_to_parent(services, monkeypatch):
    project, parent, role = prepare(services, monkeypatch)
    (Path(role.root_path) / "model.json").write_text(dumps({"provider_id": None, "model_id": None, "reasoning_mode": None}), encoding="utf-8")
    child = routes.create_project_conversation(project.project_id, ProjectConversationCreateRequest(
        created_by="ai", parent_session_id=parent.session_id, activate=False, role_project_id=role.project_id))
    assert child.provider_id is None and child.model_id is None and child.reasoning_mode is None


def test_configure_role_and_overrides_single_update_and_missing_role_changes_nothing(services, monkeypatch):
    project, parent, role = prepare(services, monkeypatch)
    updated = routes.update_project_conversation(project.project_id, parent.session_id,
        ProjectConversationSessionUpdateRequest(role_project_id=role.project_id, settings={"system_prompt": "custom"}))
    assert updated.model_id == "role-model" and updated.reasoning_mode is None
    assert updated.settings.system_prompt == "custom" and updated.role_project_id is None
    before = asdict(services[1].get_session(project.project_id, parent.session_id))
    with pytest.raises(NotFoundError):
        routes.update_project_conversation(project.project_id, parent.session_id,
            ProjectConversationSessionUpdateRequest(role_project_id="00000000-0000-0000-0000-000000000999", title="should not change"))
    assert asdict(services[1].get_session(project.project_id, parent.session_id)) == before


def test_customized_inherited_child_does_not_keep_stale_role_identity(services, monkeypatch):
    project, _, role = prepare(services, monkeypatch)
    source = routes.create_project_conversation(project.project_id, ProjectConversationCreateRequest(role_project_id=role.project_id))
    child = routes.create_project_conversation(project.project_id, ProjectConversationCreateRequest(
        created_by="ai", parent_session_id=source.session_id, activate=False, settings={"system_prompt": "child override"}))
    assert child.role_project_id is None and child.role_status == "custom"
    assert services[1].get_session(project.project_id, child.session_id).role_configuration_hash is None
    repository = services[1]
    message = repository.append_message(project.project_id, source.session_id, role="user", content="question", status="done", provider_id=None, model_id=None)
    clone = repository.fork_session(project.project_id, source.session_id, source_message_id=message.message_id,
        draft=None, references=None, created_by="ai", configuration={"settings": {"system_prompt": "clone override"}})
    assert clone.session.role_project_id is None and clone.session.role_configuration_hash is None


def test_clone_api_settles_copy_and_returns_draft_without_switching_active_session(services, monkeypatch):
    project, parent, role = prepare(services, monkeypatch)
    services[1].append_message(project.project_id, parent.session_id, role="user", content="task",
        provider_id=None, model_id=None, status="done")
    result = asyncio.run(routes.clone_project_conversation(project.project_id, parent.session_id,
        ProjectConversationCloneRequest(configuration={"role_project_id": role.project_id})))
    assert result["activated"] is False
    assert result["branch"].relation_kind == "child"
    assert result["session"].model_id == "role-model"
    assert result["state"].draft == "task"
