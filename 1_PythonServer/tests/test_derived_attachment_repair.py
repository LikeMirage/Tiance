import importlib.util
from pathlib import Path
import sqlite3

import pytest

from app.domain.llm.chat import ChatImageRef, ChatMessageContentPart, ChatMessageContentPartType
from app.repositories.project.conversation_attachment_repository import ConversationAttachmentRepository
from app.repositories.project.conversation_compaction_repository import ProjectConversationCompactionRepository
from app.repositories.project.conversation_long_term_memory_repository import (
    ProjectConversationLongTermMemoryRepository, PROJECT_MEMORY_REPOSITORY_DEFINITION, GLOBAL_MEMORY_REPOSITORY_DEFINITION,
)
from app.repositories.project.conversation_naming_repository import ProjectConversationNamingRepository
from app.repositories.project.conversation_repository import ProjectConversationRepository
from tests.test_project_conversation_naming import _FakeProjectRepository, _PROJECT_ID


@pytest.fixture
def derived_images(tmp_path):
    projects = _FakeProjectRepository(str(tmp_path))
    repo = ProjectConversationRepository(projects)
    source = repo.create_session(_PROJECT_ID, title='新对话', provider_id='provider', model_id='vision', reasoning_mode=None)
    attachments = ConversationAttachmentRepository(projects)
    record = attachments.save_bytes(_PROJECT_ID, source.session_id, content=b'\x89PNG\r\n\x1a\nimage',
        suffix='.png', display_name='image.png', mime_type='image/png', source_kind='upload', source_path=None, created_at='now')
    user = repo.append_message(_PROJECT_ID, source.session_id, role='user', content='image', content_parts=(
        ChatMessageContentPart(type=ChatMessageContentPartType.IMAGE_REF,
            image_ref=ChatImageRef(path=record.uri, mime_type='image/png')),))
    boundary = repo.append_message(_PROJECT_ID, source.session_id, role='assistant', content='reply')
    arguments = dict(snapshot_boundary_message_id=boundary.message_id, target_provider_id='provider',
        target_model_id='vision', target_reasoning_mode=None, target_settings=source.settings,
        mode='session', trigger={})
    children = [ProjectConversationNamingRepository(projects).create_task(
        _PROJECT_ID, source.session_id, **arguments, task_prompt='name')]
    children.append(ProjectConversationCompactionRepository(projects).create_task(
        _PROJECT_ID, source.session_id, **arguments, compression_id='cmp_test',
        source_boundary_message_id=boundary.message_id, source_message_ids=(user.message_id, boundary.message_id),
        newly_covered_message_ids=(user.message_id, boundary.message_id), supersedes_compression_id=None,
        configuration_fingerprint='test'))
    for definition in (PROJECT_MEMORY_REPOSITORY_DEFINITION, GLOBAL_MEMORY_REPOSITORY_DEFINITION):
        children.append(ProjectConversationLongTermMemoryRepository(projects, definition).create_task(
            _PROJECT_ID, source.session_id, **arguments, task_id='task_'+definition.scope,
            previous_boundary_message_id=None, newly_covered_message_ids=(user.message_id, boundary.message_id)))
    return projects, repo, source, record, children


def load_repair():
    script = Path(__file__).resolve().parents[2] / 'scripts/repair_derived_attachments.py'
    spec = importlib.util.spec_from_file_location('repair_derived_attachments', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_function_kinds_inherit_uri_only_image_and_can_read_without_parent(derived_images):
    projects, repo, source, record, children = derived_images
    attachments = ConversationAttachmentRepository(projects)
    _, original = attachments.read(_PROJECT_ID, source.session_id, record.uri)
    original.unlink()
    for child in children:
        copied, path = attachments.read(_PROJECT_ID, child.session.session_id, record.uri)
        assert copied == record
        assert path.read_bytes() == b'\x89PNG\r\n\x1a\nimage'
        assert repo.list_messages(_PROJECT_ID, child.session.session_id)[0].content_parts[0].image_ref.attachment_id is None


@pytest.mark.parametrize('corrupt_source', [False, True])
def test_explicit_repair_restores_only_attachments_and_is_repeatable(derived_images, corrupt_source):
    projects, repo, source, record, children = derived_images
    root = Path(projects.project.root_path)
    attachments = ConversationAttachmentRepository(projects)
    ids = [c.session.session_id for c in children]
    for sid in ids:
        attachments.read(_PROJECT_ID, sid, record.uri)[1].unlink()
    db_path = root / '.Tiance/tiance.db'
    with sqlite3.connect(db_path) as db:
        db.executemany("DELETE FROM conversation_session_events WHERE session_id = ? AND kind = 'attachments'", [(s,) for s in ids])
        before = db.execute('SELECT * FROM conversation_messages').fetchall()
        documents = db.execute('SELECT * FROM conversation_session_documents').fetchall()
    script = load_repair()
    if corrupt_source:
        attachments.read(_PROJECT_ID, source.session_id, record.uri)[1].write_bytes(b'corrupted')
        with pytest.raises(ValueError, match='integrity'):
            script.repair(root, apply=True)
        assert not (root / '.Tiance/repair-backups').exists()
        return
    plan = script.repair(root)
    assert plan['sessions'] == plan['new_records'] == 4
    assert not plan['applied']
    applied = script.repair(root, apply=True)
    assert Path(applied['backup']).is_file()
    assert applied['applied']
    assert script.repair(root)['attachments'] == 0
    for sid in ids:
        assert attachments.read(_PROJECT_ID, sid, record.uri)[1].read_bytes() == b'\x89PNG\r\n\x1a\nimage'
    with sqlite3.connect(db_path) as db:
        assert db.execute('SELECT * FROM conversation_messages').fetchall() == before
        assert db.execute('SELECT * FROM conversation_session_documents').fetchall() == documents
