import asyncio
from dataclasses import asdict, replace
from hashlib import sha256
from json import dumps, loads

import pytest

from app.domain.project.project_conversation import (
    ProjectConversationSessionSettings, conversation_session_configuration_hash,
)
from app.repositories.project.conversation_serialization_settings import (
    _session_settings_from_payload, _session_settings_to_payload, _merge_session_settings,
)
from app.repositories.project.conversation_database import read_document
from app.schemas.project.project_conversations import (
    ProjectConversationSessionSettingsPatch, ProjectConversationSessionSettingsResponse,
)
from tests.test_project_conversation_naming import (
    naming_attempt, _PROJECT_ID, _service, _session, _snapshot, _FakeNamingRepository, _create_naming_attempt,
)
from tests.test_functional_conversation_dispatch import service_for, task_dir
from tests.test_role_configuration_application import _build_services


def set_naming(conversations, session_id, enabled):
    return conversations.update_session(_PROJECT_ID, session_id,
        settings={'automatic_naming_enabled': enabled}, should_update_settings=True)


def test_setting_roundtrip_default_and_partial_patch():
    assert _session_settings_from_payload({}).automatic_naming_enabled is True
    patch = ProjectConversationSessionSettingsPatch(automatic_naming_enabled=False).model_dump(exclude_unset=True)
    settings = _merge_session_settings(ProjectConversationSessionSettings(), patch)
    settings = _merge_session_settings(settings, {'temperature': 0.4})
    restored = _session_settings_from_payload(_session_settings_to_payload(settings))
    assert restored.automatic_naming_enabled is False
    assert restored.temperature == 0.4
    assert ProjectConversationSessionSettingsResponse.from_domain(replace(_session(), settings=restored)).automatic_naming_enabled is False


@pytest.mark.parametrize('model_source', ['session', 'dedicated'])
def test_disabled_session_does_not_create_naming_task(model_source):
    from tests.test_project_conversation_naming import _default_settings
    source = _session()
    source = replace(source, settings=replace(source.settings, automatic_naming_enabled=False))
    repository = _FakeNamingRepository()
    service = _service(repository=repository, session=source, settings={
        **_default_settings(), 'modelSource': model_source, 'modelKey': 'provider/model',
    })
    assert asyncio.run(service._prepare_task_if_needed('project-1', source.session_id, run_snapshot=_snapshot(context_tokens=90000))) is None
    assert repository.create_calls == []


def test_pending_task_waits_for_source_switch_and_never_starts_twice(naming_attempt):
    _, conversations, naming, source, _, created = naming_attempt
    service = service_for(naming_attempt)
    calls = []
    async def run(request):
        calls.append(request)
        naming.apply_title(_PROJECT_ID, request.session_id, title='恢复命名')
    service.set_functional_conversation_runner(run)
    set_naming(conversations, source.session_id, False)
    asyncio.run(service.resume_task(_PROJECT_ID, source.session_id, created.session.session_id))
    assert calls == []
    assert read_document(task_dir(naming_attempt), 'automatic_naming_task')['status'] == 'pending'
    set_naming(conversations, source.session_id, True)
    async def resume():
        await asyncio.gather(*(service.resume_task(_PROJECT_ID, source.session_id, created.session.session_id) for _ in range(5)))
    asyncio.run(resume())
    assert len(calls) == 1
    assert conversations.get_session(_PROJECT_ID, source.session_id).title == '恢复命名'


def test_disabling_during_execution_rejects_late_title_but_allows_manual_rename(naming_attempt):
    _, conversations, naming, source, _, created = naming_attempt
    assert naming.claim_task(_PROJECT_ID, created.session.session_id) is not None
    set_naming(conversations, source.session_id, False)
    result = naming.apply_title(_PROJECT_ID, created.session.session_id, title='迟到的标题')
    assert result['applied'] is False
    assert conversations.get_session(_PROJECT_ID, source.session_id).title == '新对话'
    conversations.update_session(_PROJECT_ID, source.session_id, title='手动标题', should_update_title=True,
                                 manual_title=True, should_update_manual_title=True)
    assert conversations.get_session(_PROJECT_ID, source.session_id).title == '手动标题'


def test_function_session_switch_prevents_recursion_independent_of_title(naming_attempt):
    _, conversations, naming, _, boundary, created = naming_attempt
    child = conversations.update_session(_PROJECT_ID, created.session.session_id, title='新对话', should_update_title=True,
                                        manual_title=False, should_update_manual_title=True)
    assert child.settings.automatic_naming_enabled is False
    repository = _FakeNamingRepository()
    service = _service(repository=repository, session=child)
    assert asyncio.run(service._prepare_task_if_needed(_PROJECT_ID, child.session_id, run_snapshot=_snapshot(context_tokens=90000))) is None
    assert repository.create_calls == []
    # The transaction also checks the latest switch if it changed after planning.
    assert _create_naming_attempt(naming, child, boundary) is None


def test_new_setting_preserves_existing_default_role_fingerprint():
    session = _session()
    settings = asdict(session.settings)
    settings.pop('automatic_naming_enabled')
    payload = {key: getattr(session, key) for key in ('provider_id', 'model_id', 'reasoning_mode')}
    payload['settings'] = settings
    legacy_hash = sha256(dumps(payload, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode()).hexdigest()
    assert conversation_session_configuration_hash(session) == legacy_hash
    assert conversation_session_configuration_hash(replace(session, settings=replace(session.settings, automatic_naming_enabled=False))) != legacy_hash


def test_role_saves_applies_and_seeds_naming_setting(tmp_path):
    projects, conversations, roles, _ = _build_services(tmp_path)
    role = roles.ensure_default_role()
    project = projects.create_project(name='命名开关测试')
    source = conversations.create_session(project.project_id, settings={'automatic_naming_enabled': False})
    roles.write_role_configuration(role.project_id, source)
    response = loads((tmp_path / 'roles' / role.project_id / 'response.json').read_text(encoding='utf-8'))
    assert response['automatic_naming_enabled'] is False
    assert roles.build_new_session_seed(role.project_id).settings['automatic_naming_enabled'] is False
    target = conversations.create_session(project.project_id)
    applied = roles.apply_role(project.project_id, target.session_id, role.project_id)
    assert applied.settings.automatic_naming_enabled is False


@pytest.mark.parametrize('enabled', [False, True])
def test_ordinary_child_and_fork_inherit_naming_choice(tmp_path, enabled):
    from tests.test_project_conversation_branching import _repository, _create_session, _append, PROJECT_ID
    repository = _repository(tmp_path)
    source = _create_session(repository)
    repository.update_session(PROJECT_ID, source.session_id,
        settings={'automatic_naming_enabled': enabled}, should_update_settings=True)
    child = repository.create_session(PROJECT_ID, title=None, provider_id=None, model_id=None,
        reasoning_mode=None, settings={'temperature': 0.4}, parent_session_id=source.session_id,
        created_by='ai', set_active=False)
    boundary = _append(repository, source.session_id, 'user', '创建分支')
    _append(repository, source.session_id, 'assistant', '已完成')
    fork = repository.fork_session(PROJECT_ID, source.session_id,
        source_message_id=boundary.message_id, draft='分支草稿', references=[])
    assert repository.get_session(PROJECT_ID, child.session_id).settings.automatic_naming_enabled is enabled
    assert repository.get_session(PROJECT_ID, fork.session.session_id).settings.automatic_naming_enabled is enabled
