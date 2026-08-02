from app.domain.llm.chat import ChatCompletionRequest, ChatMessage, ChatMessageRole
from app.infra.database import database_transaction, ensure_database_schema, run_database_migrations
from app.infra.database.schema import MIGRATIONS
from app.infra.projects import ProjectStorage
from app.repositories.project import ProjectRepository
from app.repositories.project.conversation_repository import ProjectConversationRepository
from app.repositories.workspace_activity_repository import WorkspaceActivityRepository
from app.services.project.conversation_stream_persistence import ConversationStreamPersistence
from app.services.project.project_conversations import ProjectConversationService
from app.services.project.projects import ProjectService
from app.services.workspace_activity import (
    WorkspaceActivityManagementService,
    WorkspaceActivityService,
)


def test_workspace_activity_migration_seeds_existing_session_index(tmp_path):
    database_path = tmp_path / "tiance.db"
    run_database_migrations(
        database_path,
        tuple(migration for migration in MIGRATIONS if migration.version <= 25),
    )
    with database_transaction(database_path) as connection:
        connection.execute(
            """
            INSERT INTO projects (
                project_id, name, root_path, category_id, is_default,
                sort_order, created_at, updated_at
            ) VALUES ('project-1', '项目', 'C:/work', 'daily-project', 0, 0, 'now', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO llm_conversation_session_index (
                project_id, session_id, title, provider_id, model_id,
                message_count, created_at, updated_at, indexed_at, sequence_number
            ) VALUES ('project-1', 'session-1', '空会话', NULL, NULL, 0, 'created', 'created', 'now', 1)
            """
        )

    ensure_database_schema(database_path)

    repository = WorkspaceActivityRepository(database_path)
    assert repository.count_conversations_created() == 1


def test_conversation_creation_activity_is_idempotent_and_survives_deletion(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    project_repository = ProjectRepository(database_path)
    project_service = ProjectService(
        project_repository,
        ProjectStorage(tmp_path / "managed-projects"),
    )
    activity_repository = WorkspaceActivityRepository(database_path)
    activity_service = WorkspaceActivityService(activity_repository)
    conversation_service = ProjectConversationService(
        ProjectConversationRepository(project_repository),
        activity_service,
    )
    project = project_service.create_project(name="统计测试")

    original = conversation_service.create_session(project.project_id)
    activity_service.record_conversation_created(original)
    user_message = conversation_service.append_message(
        project.project_id,
        original.session_id,
        role="user",
        content="创建分支",
    )
    conversation_service.save_session_runtime_status(
        project.project_id,
        original.session_id,
        "idle",
    )
    forked = conversation_service.fork_session(
        project.project_id,
        original.session_id,
        source_message_id=user_message.message_id,
        draft="分支草稿",
        references=[],
    )

    assert activity_service.get_conversation_count() == 2

    conversation_service.delete_session(project.project_id, forked.session.session_id)
    conversation_service.delete_session(project.project_id, original.session_id)

    remaining = conversation_service.list_sessions(project.project_id)
    assert len(remaining) == 1
    assert activity_service.get_conversation_count() == 3


def test_conversation_count_can_clear_and_continue_from_zero(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    repository = WorkspaceActivityRepository(database_path)
    service = WorkspaceActivityService(repository)

    repository.record_conversation_created(
        session_id="old-session",
        created_at="2026-01-01T00:00:00+00:00",
    )
    assert service.get_conversation_count() == 1
    assert service.clear_conversation_count() == 0

    repository.record_conversation_created(
        session_id="old-session",
        created_at="2026-01-01T00:00:00+00:00",
    )
    assert service.get_conversation_count() == 0

    repository.record_conversation_created(
        session_id="new-session",
        created_at="2999-01-01T00:00:00+00:00",
    )
    assert service.get_conversation_count() == 1


def test_sent_user_message_activity_is_idempotent_and_survives_session_deletion(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    project_repository = ProjectRepository(database_path)
    project_service = ProjectService(
        project_repository,
        ProjectStorage(tmp_path / "managed-projects"),
    )
    activity_service = WorkspaceActivityService(
        WorkspaceActivityRepository(database_path),
    )
    conversation_service = ProjectConversationService(
        ProjectConversationRepository(project_repository),
        activity_service,
    )
    project = project_service.create_project(name="发送统计")
    session = conversation_service.create_session(project.project_id)
    persistence = ConversationStreamPersistence(
        conversation_service=conversation_service,
        usage_service=None,
        naming_service=None,
        memory_service=None,
        background_task_registry=None,
    )
    request = ChatCompletionRequest(
        provider_id="provider",
        model_id="model",
        project_id=project.project_id,
        session_id=session.session_id,
        messages=(
            ChatMessage(
                role=ChatMessageRole.USER,
                content="统计这次发送",
                message_id="user-message-1",
            ),
        ),
    )

    message = persistence.append_user_message(request)
    assert message is not None
    assert persistence.existing_request_turn(request) is not None

    assert activity_service.get_sent_message_count() == 1

    conversation_service.delete_session(project.project_id, session.session_id)
    assert activity_service.get_sent_message_count() == 1


def test_ai_runtime_activity_is_idempotent_and_sums_elapsed_milliseconds(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    repository = WorkspaceActivityRepository(database_path)
    service = WorkspaceActivityService(repository)

    assert service.record_ai_run_elapsed(
        user_message_id="user-message-1",
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:02.500000+00:00",
        elapsed_ms=None,
    )
    assert service.record_ai_run_elapsed(
        user_message_id="user-message-1",
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:09+00:00",
        elapsed_ms=None,
    )
    assert service.record_ai_run_elapsed(
        user_message_id="user-message-2",
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:01+00:00",
        elapsed_ms=1_250,
    )

    assert service.get_ai_runtime_ms() == 3_750


def test_conversation_count_can_sync_to_current_sessions(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    project_repository = ProjectRepository(database_path)
    project_service = ProjectService(
        project_repository,
        ProjectStorage(tmp_path / "managed-projects"),
    )
    activity_service = WorkspaceActivityService(
        WorkspaceActivityRepository(database_path),
    )
    conversation_service = ProjectConversationService(
        ProjectConversationRepository(project_repository),
        activity_service,
    )
    management_service = WorkspaceActivityManagementService(
        activity_service,
        project_service,
        conversation_service,
    )
    project = project_service.create_project(name="同步测试")

    first = conversation_service.create_session(project.project_id)
    conversation_service.delete_session(project.project_id, first.session_id)
    conversation_service.create_session(project.project_id)

    assert activity_service.get_conversation_count() == 3
    assert management_service.synchronize_conversation_count() == 2
    assert activity_service.get_conversation_count() == 2
