from datetime import UTC, datetime
from json import dumps, loads

from app.domain.project import Project
from app.domain.project.conversation_branch_overview import (
    build_conversation_branch_group_detail,
    build_conversation_branch_groups,
)
from app.core.errors import ConflictError
from app.repositories.project.conversation_repository import ProjectConversationRepository
from app.repositories.project.conversation_database import (
    read_document,
    read_events,
    read_meta,
    replace_events,
    write_document,
    write_meta,
)
from app.services.project.conversation_memory_delivery_state import (
    GLOBAL_MEMORY_SCOPE,
    prepare_memory_delivery_state,
)


PROJECT_ID = "00000000-0000-0000-0000-000000000777"


class FakeProjectRepository:
    def __init__(self, root_path: str) -> None:
        now = datetime.now(UTC).isoformat()
        self.project = Project(
            project_id=PROJECT_ID,
            name="branch-test",
            root_path=root_path,
            is_default=False,
            sort_order=0,
            created_at=now,
            updated_at=now,
        )

    def get_project(self, project_id: str) -> Project | None:
        return self.project if project_id == PROJECT_ID else None


def _repository(tmp_path) -> ProjectConversationRepository:
    return ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))


def _create_session(repository: ProjectConversationRepository, title: str = "新会话"):
    return repository.create_session(
        PROJECT_ID,
        title=title,
        provider_id="provider-a",
        model_id="model-a",
        reasoning_mode="high",
        settings={"system_prompt": "stable system prompt", "memory_compression_enabled": True},
    )


def _append(repository, session_id: str, role: str, content: str):
    return repository.append_message(
        PROJECT_ID,
        session_id,
        role=role,
        content=content,
        provider_id="provider-a",
        model_id="model-a",
        status="done",
    )


def test_session_and_overview_order_stays_fixed_when_older_session_is_updated(tmp_path):
    repository = _repository(tmp_path)
    older = _create_session(repository, "较早创建")
    newer = _create_session(repository, "较晚创建")

    _append(repository, older.session_id, "user", "更新较早会话")

    sessions = repository.list_sessions(PROJECT_ID)
    assert [session.session_id for session in sessions] == [
        newer.session_id,
        older.session_id,
    ]
    groups = build_conversation_branch_groups(sessions, ())
    assert [group.root_session_id for group in groups] == [
        newer.session_id,
        older.session_id,
    ]

    repository.set_session_pinned(PROJECT_ID, older.session_id, pinned=True)
    pinned_sessions = repository.list_sessions(PROJECT_ID)
    assert [session.session_id for session in pinned_sessions] == [
        older.session_id,
        newer.session_id,
    ]
    pinned_groups = build_conversation_branch_groups(pinned_sessions, ())
    assert [group.root_session_id for group in pinned_groups] == [
        older.session_id,
        newer.session_id,
    ]


def test_fork_uses_complete_backend_history_and_not_a_frontend_page(tmp_path):
    repository = _repository(tmp_path)
    source = _create_session(repository)
    messages = []
    for index in range(51):
        messages.append(_append(repository, source.session_id, "user", f"user-{index}"))
        messages.append(_append(repository, source.session_id, "assistant", f"assistant-{index}"))
    branch_point = _append(repository, source.session_id, "user", "edit this message")
    _append(repository, source.session_id, "assistant", "answer after branch point")

    result = repository.fork_session(
        PROJECT_ID,
        source.session_id,
        source_message_id=branch_point.message_id,
        draft="edited message",
        references=[],
    )

    copied = repository.list_messages(PROJECT_ID, result.session.session_id)
    assert len(copied) == 102
    assert result.session.message_count == 102
    assert [message.content for message in copied] == [message.content for message in messages]
    assert len({message.message_id for message in copied}) == 102
    assert {message.message_id for message in copied}.isdisjoint(
        {message.message_id for message in messages}
    )
    assert [message.origin_message_id for message in copied] == [
        message.message_id for message in messages
    ]
    assert result.state.draft == "edited message"
    assert result.session.settings.system_prompt == "stable system prompt"

    visible_page = repository.list_messages_page(
        PROJECT_ID,
        result.session.session_id,
        limit=28,
    )
    assert len(visible_page.items) == 28
    assert len(repository.list_messages(PROJECT_ID, result.session.session_id)) == 102


def test_fork_inherits_memory_delivery_and_replays_changes_at_new_request(tmp_path):
    repository = _repository(tmp_path)
    source = _create_session(repository)
    source_user = _append(repository, source.session_id, "user", "已有请求")
    _append(repository, source.session_id, "assistant", "已有回复")
    branch_point = _append(repository, source.session_id, "user", "从这里创建分支")
    _append(repository, source.session_id, "assistant", "分支点原回复")

    global_events = [
        {
            "memory_id": "gm_1",
            "operation": "add",
            "target_memory_id": None,
            "content": "初始记忆",
            "keywords": [],
            "reason": "初始事实",
            "created_at": "2026-07-14T00:00:00+00:00",
        }
    ]
    state = prepare_memory_delivery_state(
        None,
        user_message_id=source_user.message_id,
        created_at="2026-07-14T00:00:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
    )
    global_events.append(
        {
            "memory_id": None,
            "operation": "update",
            "target_memory_id": "gm_1",
            "content": "分支点更新后的记忆",
            "keywords": [],
            "reason": "分支点更新",
            "created_at": "2026-07-14T00:01:00+00:00",
        }
    )
    state = prepare_memory_delivery_state(
        state,
        user_message_id=branch_point.message_id,
        created_at="2026-07-14T00:01:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
    )
    source_dir = (
        tmp_path
        / ".Tiance"
        / "conversations"
        / "sessions"
        / source.session_id
    )
    write_document(source_dir, "memory_delivery", state)

    result = repository.fork_session(
        PROJECT_ID,
        source.session_id,
        source_message_id=branch_point.message_id,
        draft="分支的新请求",
        references=[],
    )

    target_dir = (
        tmp_path
        / ".Tiance"
        / "conversations"
        / "sessions"
        / result.session.session_id
    )
    inherited = read_document(target_dir, "memory_delivery")
    assert inherited is not None
    assert inherited["cursors"][GLOBAL_MEMORY_SCOPE] == 1
    assert inherited["deliveries"] == []

    continued = prepare_memory_delivery_state(
        inherited,
        user_message_id="child-user",
        created_at="2026-07-14T00:02:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
    )
    assert [
        (change["operation"], change["memory_id"])
        for change in continued["deliveries"][-1][GLOBAL_MEMORY_SCOPE]
    ] == [("update", "gm_1")]


def test_nested_branch_names_and_message_variants_do_not_depend_on_titles(tmp_path):
    repository = _repository(tmp_path)
    root = _create_session(repository)
    root_user = _append(repository, root.session_id, "user", "root direction")
    _append(repository, root.session_id, "assistant", "root answer")

    first = repository.fork_session(
        PROJECT_ID,
        root.session_id,
        source_message_id=root_user.message_id,
        draft="first alternative",
        references=[],
    )
    first_user = _append(repository, first.session.session_id, "user", "first alternative")
    _append(repository, first.session.session_id, "assistant", "first answer")

    nested = repository.fork_session(
        PROJECT_ID,
        first.session.session_id,
        source_message_id=first_user.message_id,
        draft="nested alternative",
        references=[],
    )
    second_root = repository.fork_session(
        PROJECT_ID,
        root.session_id,
        source_message_id=root_user.message_id,
        draft="second root alternative",
        references=[],
    )

    assert first.session.title == "新会话_1"
    assert nested.session.title == "新会话_1_1"
    assert second_root.session.title == "新会话_2"
    assert repository.get_cache_affinity_id(
        PROJECT_ID,
        root.session_id,
    ) == root.session_id
    assert repository.get_cache_affinity_id(
        PROJECT_ID,
        first.session.session_id,
    ) == root.session_id
    assert repository.get_cache_affinity_id(
        PROJECT_ID,
        nested.session.session_id,
    ) == root.session_id
    assert repository.get_cache_affinity_id(
        PROJECT_ID,
        second_root.session.session_id,
    ) == root.session_id

    nodes, variants = repository.list_branch_graph(PROJECT_ID)
    node_by_session = {node.session_id: node for node in nodes}
    assert node_by_session[nested.session.session_id].parent_branch_id == first.branch.branch_id
    assert node_by_session[nested.session.session_id].created_by == "user"
    assert node_by_session[nested.session.session_id].history_mode == "fork"
    assert (
        node_by_session[nested.session.session_id].source_message_id
        == first_user.message_id
    )
    assert node_by_session[second_root.session.session_id].parent_branch_id == first.branch.parent_branch_id
    root_variants = sorted(
        variant.variant_index
        for variant in variants
        if variant.variant_group_id == root_user.variant_group_id
    )
    assert root_variants == [1, 2, 3, 4]


def test_ai_created_child_keeps_lineage_without_joining_parent_history_tree(tmp_path):
    repository = _repository(tmp_path)
    root = _create_session(repository, "主会话")
    child = repository.create_session(
        PROJECT_ID,
        title="AI 子会话",
        provider_id=None,
        model_id=None,
        reasoning_mode=None,
        settings={"temperature": 0.4},
        parent_session_id=root.session_id,
        created_by="ai",
        set_active=False,
    )

    nodes, _variants = repository.list_branch_graph(PROJECT_ID)
    node_by_session = {node.session_id: node for node in nodes}
    root_node = node_by_session[root.session_id]
    child_node = node_by_session[child.session_id]

    assert child_node.parent_branch_id == root_node.branch_id
    assert child_node.parent_session_id == root.session_id
    assert child_node.relation_kind == "child"
    assert child_node.created_by == "ai"
    assert child_node.history_mode == "empty"
    assert child_node.source_message_id is None
    assert child_node.tree_id != root_node.tree_id
    assert child.provider_id == root.provider_id
    assert child.model_id == root.model_id
    assert child.reasoning_mode == root.reasoning_mode
    assert child.settings.system_prompt == root.settings.system_prompt
    assert child.settings.memory_compression_enabled is True
    assert child.settings.temperature == 0.4
    assert repository.get_cache_affinity_id(
        PROJECT_ID,
        child.session_id,
    ) == child.session_id

    groups = build_conversation_branch_groups(
        repository.list_sessions(PROJECT_ID),
        nodes,
    )
    assert len(groups) == 2
    assert all(group.is_branched is False for group in groups)


def test_old_branch_graph_version_is_rejected_without_compatibility_upgrade(tmp_path):
    import pytest

    repository = _repository(tmp_path)
    root = _create_session(repository, "旧版根会话")
    conversations_dir = tmp_path / ".Tiance" / "conversations"
    write_meta(
        conversations_dir,
        "branch_graph",
        {
                "version": 1,
                "nodes": [
                    {
                        "branch_id": "branch_legacy_root",
                        "tree_id": "tree_legacy",
                        "session_id": root.session_id,
                        "parent_branch_id": None,
                        "sibling_index": 0,
                        "created_at": root.created_at,
                        "deleted_at": None,
                    }
                ],
                "variants": [],
        },
    )

    with pytest.raises(ConflictError, match="格式无效"):
        repository.create_session(
            PROJECT_ID,
            title="AI 子会话",
            provider_id="provider-a",
            model_id="model-a",
            reasoning_mode="high",
            settings={},
            parent_session_id=root.session_id,
            created_by="ai",
            set_active=False,
        )


def test_old_relation_shape_is_rejected_without_compatibility_upgrade(tmp_path):
    import pytest

    from app.repositories.project.conversation_branch_store import ConversationBranchStore

    write_meta(
        tmp_path,
        "branch_graph",
        {
                "version": 2,
                "nodes": [
                    {
                        "branch_id": "branch_root",
                        "tree_id": "tree_root",
                        "session_id": "session_root",
                        "parent_branch_id": None,
                        "created_by": "user",
                        "history_mode": "empty",
                        "source_message_id": None,
                        "sibling_index": 0,
                        "created_at": "2026-07-29T00:00:00+00:00",
                    },
                    {
                        "branch_id": "branch_child",
                        "tree_id": "tree_child",
                        "session_id": "session_child",
                        "parent_branch_id": "branch_root",
                        "created_by": "ai",
                        "history_mode": "empty",
                        "source_message_id": None,
                        "sibling_index": 1,
                        "created_at": "2026-07-29T00:01:00+00:00",
                    },
                ],
                "variants": [],
        },
    )

    store = ConversationBranchStore()
    with pytest.raises(ConflictError, match="格式无效"):
        store.read_graph(tmp_path)


def test_child_and_fork_sibling_numbers_are_independent(tmp_path):
    repository = _repository(tmp_path)
    root = _create_session(repository, "主会话")
    root_user = _append(repository, root.session_id, "user", "创建分支")
    _append(repository, root.session_id, "assistant", "原回答")

    child = repository.create_session(
        PROJECT_ID,
        title="AI 子会话",
        provider_id=None,
        model_id=None,
        reasoning_mode=None,
        settings=None,
        parent_session_id=root.session_id,
        created_by="ai",
        set_active=False,
    )
    fork = repository.fork_session(
        PROJECT_ID,
        root.session_id,
        source_message_id=root_user.message_id,
        draft="分支回答",
        references=[],
    )

    nodes, _variants = repository.list_branch_graph(PROJECT_ID)
    node_by_session = {node.session_id: node for node in nodes}
    assert node_by_session[child.session_id].sibling_index == 1
    assert node_by_session[fork.session.session_id].sibling_index == 1
    assert node_by_session[fork.session.session_id].relation_kind == "fork"
    assert fork.session.title == "主会话_1"


def test_child_model_override_requires_provider_and_model_together(tmp_path):
    import pytest

    repository = _repository(tmp_path)
    root = _create_session(repository, "主会话")

    with pytest.raises(ConflictError, match="同时指定供应商和模型"):
        repository.create_session(
            PROJECT_ID,
            title="错误配置的子会话",
            provider_id="provider-b",
            model_id=None,
            reasoning_mode=None,
            settings=None,
            parent_session_id=root.session_id,
            created_by="ai",
            set_active=False,
        )

    assert [session.session_id for session in repository.list_sessions(PROJECT_ID)] == [
        root.session_id
    ]


def test_ai_child_creation_rolls_back_if_relation_write_fails(tmp_path):
    import pytest

    from app.repositories.project.conversation_branch_store import ConversationBranchStore

    class FailingBranchStore(ConversationBranchStore):
        def write_graph(self, conversations_dir, graph) -> None:
            raise OSError("simulated relation write failure")

    initial_repository = _repository(tmp_path)
    root = _create_session(initial_repository, "主会话")
    repository = ProjectConversationRepository(
        FakeProjectRepository(str(tmp_path)),
        branch_store=FailingBranchStore(),
    )

    with pytest.raises(OSError, match="relation write failure"):
        repository.create_session(
            PROJECT_ID,
            title="不应残留的 AI 子会话",
            provider_id=None,
            model_id=None,
            reasoning_mode=None,
            parent_session_id=root.session_id,
            created_by="ai",
            set_active=False,
        )

    sessions = repository.list_sessions(PROJECT_ID)
    assert [session.session_id for session in sessions] == [root.session_id]
    session_dirs = (
        tmp_path
        / ".Tiance"
        / "conversations"
        / "sessions"
    )
    assert sorted(path.name for path in session_dirs.iterdir()) == [root.session_id]


def test_fork_creation_rolls_back_if_index_write_fails(tmp_path, monkeypatch):
    import pytest

    repository = _repository(tmp_path)
    root = _create_session(repository, "主会话")
    root_user = _append(repository, root.session_id, "user", "创建分支")
    _append(repository, root.session_id, "assistant", "原回答")

    def fail_index_write(_conversations_dir, _payload):
        raise OSError("simulated index write failure")

    monkeypatch.setattr(repository._session_store, "write_index", fail_index_write)
    with pytest.raises(OSError, match="index write failure"):
        repository.fork_session(
            PROJECT_ID,
            root.session_id,
            source_message_id=root_user.message_id,
            draft="分支回答",
            references=[],
        )

    assert [session.session_id for session in repository.list_sessions(PROJECT_ID)] == [
        root.session_id
    ]
    nodes, _variants = repository.list_branch_graph(PROJECT_ID)
    assert nodes == ()
    session_dirs = tmp_path / ".Tiance" / "conversations" / "sessions"
    assert sorted(path.name for path in session_dirs.iterdir()) == [root.session_id]


def test_fork_creation_restores_index_if_relation_write_fails(tmp_path):
    import pytest

    from app.repositories.project.conversation_branch_store import ConversationBranchStore

    class FailingBranchStore(ConversationBranchStore):
        def write_graph(self, conversations_dir, graph) -> None:
            raise OSError("simulated relation write failure")

    initial_repository = _repository(tmp_path)
    root = _create_session(initial_repository, "主会话")
    root_user = _append(initial_repository, root.session_id, "user", "创建分支")
    _append(initial_repository, root.session_id, "assistant", "原回答")
    repository = ProjectConversationRepository(
        FakeProjectRepository(str(tmp_path)),
        branch_store=FailingBranchStore(),
    )

    with pytest.raises(OSError, match="relation write failure"):
        repository.fork_session(
            PROJECT_ID,
            root.session_id,
            source_message_id=root_user.message_id,
            draft="分支回答",
            references=[],
        )

    assert [session.session_id for session in repository.list_sessions(PROJECT_ID)] == [
        root.session_id
    ]
    session_dirs = tmp_path / ".Tiance" / "conversations" / "sessions"
    assert sorted(path.name for path in session_dirs.iterdir()) == [root.session_id]


def test_deleting_middle_session_promotes_child_to_nearest_live_ancestor(tmp_path):
    repository = _repository(tmp_path)
    root = _create_session(repository)
    root_user = _append(repository, root.session_id, "user", "root")
    _append(repository, root.session_id, "assistant", "root answer")
    middle = repository.fork_session(
        PROJECT_ID,
        root.session_id,
        source_message_id=root_user.message_id,
        draft="middle",
        references=[],
    )
    middle_user = _append(repository, middle.session.session_id, "user", "middle")
    _append(repository, middle.session.session_id, "assistant", "middle answer")
    child = repository.fork_session(
        PROJECT_ID,
        middle.session.session_id,
        source_message_id=middle_user.message_id,
        draft="child",
        references=[],
    )

    repository.delete_session(
        PROJECT_ID,
        middle.session.session_id,
        session_ids=(middle.session.session_id,),
    )

    nodes, _variants = repository.list_branch_graph(PROJECT_ID)
    node_by_session = {node.session_id: node for node in nodes}
    assert node_by_session[middle.session.session_id].deleted_at is not None
    assert node_by_session[child.session.session_id].deleted_at is None
    assert node_by_session[child.session.session_id].parent_branch_id == node_by_session[root.session_id].branch_id
    assert node_by_session[child.session.session_id].parent_session_id == root.session_id
    assert node_by_session[child.session.session_id].source_message_id is None
    assert repository.get_session(PROJECT_ID, child.session.session_id) is not None


def test_deleting_branch_root_promotes_a_live_session_in_branch_overview(tmp_path):
    repository = _repository(tmp_path)
    root = _create_session(repository, "主会话")
    root_user = _append(repository, root.session_id, "user", "创建分支")
    _append(repository, root.session_id, "assistant", "原回答")
    branch = repository.fork_session(
        PROJECT_ID,
        root.session_id,
        source_message_id=root_user.message_id,
        draft="分支回答",
        references=[],
    )

    repository.delete_session(
        PROJECT_ID,
        root.session_id,
        session_ids=(root.session_id,),
    )

    sessions = repository.list_sessions(PROJECT_ID)
    nodes, _variants = repository.list_branch_graph(PROJECT_ID)
    groups = build_conversation_branch_groups(sessions, nodes)
    assert len(groups) == 1
    assert groups[0].root_session_id == branch.session.session_id
    assert groups[0].session_ids == (branch.session.session_id,)
    live_branch = next(
        node
        for node in nodes
        if node.session_id == branch.session.session_id
    )
    assert live_branch.parent_session_id is None
    assert live_branch.parent_branch_id is None
    assert live_branch.source_message_id is None


def test_deleting_inactive_session_preserves_active_session(tmp_path):
    repository = _repository(tmp_path)
    inactive = _create_session(repository, "非活动会话")
    active = _create_session(repository, "活动会话")

    repository.delete_session(
        PROJECT_ID,
        inactive.session_id,
        session_ids=(inactive.session_id,),
    )

    active_session_id, _states = repository.get_state(PROJECT_ID)
    assert active_session_id == active.session_id


def test_deleting_active_session_selects_latest_remaining_root(tmp_path):
    repository = _repository(tmp_path)
    older_root = _create_session(repository, "较早顶层会话")
    newer_root = _create_session(repository, "较新顶层会话")
    older_root_user = _append(repository, older_root.session_id, "user", "创建下级")
    _append(repository, older_root.session_id, "assistant", "原回答")
    newest_non_root = repository.fork_session(
        PROJECT_ID,
        older_root.session_id,
        source_message_id=older_root_user.message_id,
        draft="最新下级会话",
        references=[],
    )
    active_root = _create_session(repository, "待删除活动会话")

    repository.delete_session(
        PROJECT_ID,
        active_root.session_id,
        session_ids=(active_root.session_id,),
    )

    active_session_id, _states = repository.get_state(PROJECT_ID)
    assert repository.get_session(
        PROJECT_ID,
        newest_non_root.session.session_id,
    ) is not None
    assert active_session_id == newer_root.session_id


def test_selective_tree_deletion_keeps_unselected_descendant_and_repairs_parent(tmp_path):
    repository = _repository(tmp_path)
    root = _create_session(repository, "主会话")
    root_user = _append(repository, root.session_id, "user", "root")
    _append(repository, root.session_id, "assistant", "root answer")
    middle = repository.fork_session(
        PROJECT_ID,
        root.session_id,
        source_message_id=root_user.message_id,
        draft="middle",
        references=[],
    )
    middle_user = _append(repository, middle.session.session_id, "user", "middle")
    _append(repository, middle.session.session_id, "assistant", "middle answer")
    child = repository.fork_session(
        PROJECT_ID,
        middle.session.session_id,
        source_message_id=middle_user.message_id,
        draft="child",
        references=[],
    )
    child_user = _append(repository, child.session.session_id, "user", "child")
    _append(repository, child.session.session_id, "assistant", "child answer")
    grandchild = repository.fork_session(
        PROJECT_ID,
        child.session.session_id,
        source_message_id=child_user.message_id,
        draft="grandchild",
        references=[],
    )

    repository.delete_session(
        PROJECT_ID,
        middle.session.session_id,
        session_ids=(middle.session.session_id, child.session.session_id),
    )

    nodes, _variants = repository.list_branch_graph(PROJECT_ID)
    node_by_session = {node.session_id: node for node in nodes}
    assert node_by_session[middle.session.session_id].deleted_at is not None
    assert node_by_session[child.session.session_id].deleted_at is not None
    assert node_by_session[grandchild.session.session_id].deleted_at is None
    assert node_by_session[grandchild.session.session_id].parent_session_id == root.session_id
    assert node_by_session[grandchild.session.session_id].parent_branch_id == node_by_session[root.session_id].branch_id
    assert repository.get_session(PROJECT_ID, grandchild.session.session_id) is not None


def test_selective_tree_deletion_rejects_unrelated_session(tmp_path):
    import pytest

    from app.core.errors import BadRequestError

    repository = _repository(tmp_path)
    target = _create_session(repository, "待删除会话")
    unrelated = _create_session(repository, "无关会话")

    with pytest.raises(BadRequestError, match="只能删除当前会话及其下级会话"):
        repository.delete_session(
            PROJECT_ID,
            target.session_id,
            session_ids=(target.session_id, unrelated.session_id),
        )

    assert repository.get_session(PROJECT_ID, target.session_id) is not None
    assert repository.get_session(PROJECT_ID, unrelated.session_id) is not None


def test_parent_deletion_preserves_functional_session_without_special_lifecycle_rule():
    from app.repositories.project.conversation_branch_store import ConversationBranchStore

    graph = {
        "version": 4,
        "nodes": [
            {
                "branch_id": "branch-root",
                "tree_id": "tree-root",
                "session_id": "session-root",
                "parent_branch_id": None,
                "parent_session_id": None,
                "relation_kind": "root",
                "function_type": None,
                "created_by": "user",
                "history_mode": "empty",
                "source_message_id": None,
                "sibling_index": 0,
                "created_at": "2026-08-18T00:00:00+00:00",
                "deleted_at": None,
            },
            {
                "branch_id": "branch-function",
                "tree_id": "tree-function",
                "session_id": "session-function",
                "parent_branch_id": "branch-root",
                "parent_session_id": "session-root",
                "relation_kind": "functional",
                "function_type": "memory_compaction",
                "created_by": "system",
                "history_mode": "copy",
                "source_message_id": "msg-source",
                "sibling_index": 1,
                "created_at": "2026-08-18T00:01:00+00:00",
                "deleted_at": None,
            },
        ],
        "variants": [],
    }
    store = ConversationBranchStore()

    store.delete_sessions_and_reparent(
        graph,
        frozenset({"session-root"}),
        deleted_at="2026-08-18T00:02:00+00:00",
    )

    function_node = store.node_for_session(graph, "session-function")
    assert function_node is not None
    assert function_node.deleted_at is None
    assert function_node.parent_session_id is None
    assert function_node.parent_branch_id is None
    assert function_node.relation_kind == "functional"
    assert function_node.function_type == "memory_compaction"


def test_fork_only_inherits_completed_compressions_fully_before_branch_point(tmp_path):
    repository = _repository(tmp_path)
    source = _create_session(repository)
    first_user = _append(repository, source.session_id, "user", "first")
    first_assistant = _append(repository, source.session_id, "assistant", "first answer")
    branch_point = _append(repository, source.session_id, "user", "branch here")
    _append(repository, source.session_id, "assistant", "branch answer")
    source_dir = (
        tmp_path
        / ".Tiance"
        / "conversations"
        / "sessions"
        / source.session_id
    )
    records = [
        {
            "compression_id": "cmp_safe",
            "status": "completed",
            "source_type": "conversation_context",
            "session_id": source.session_id,
            "source_message_ids": [first_user.message_id, first_assistant.message_id],
            "result": {
                "items": [{"content": "safe summary", "keywords": []}],
                "handoff": "continue",
            },
        },
        {
            "compression_id": "cmp_crosses_branch",
            "status": "completed",
            "source_type": "conversation_context",
            "session_id": source.session_id,
            "source_message_ids": [first_assistant.message_id, branch_point.message_id],
            "result": {
                "items": [{"content": "future leak", "keywords": []}],
                "handoff": "future",
            },
        },
        {
            "compression_id": "cmp_failed",
            "status": "failed",
            "session_id": source.session_id,
            "source_message_ids": [first_user.message_id],
        },
    ]
    replace_events(source_dir, "compressions", records)

    result = repository.fork_session(
        PROJECT_ID,
        source.session_id,
        source_message_id=branch_point.message_id,
        draft="branch here edited",
        references=[],
    )
    target_dir = (
        tmp_path
        / ".Tiance"
        / "conversations"
        / "sessions"
        / result.session.session_id
    )
    inherited = read_events(target_dir, "compressions")

    assert len(inherited) == 1
    assert inherited[0]["result"]["items"][0]["content"] == "safe summary"
    assert inherited[0]["result"]["handoff"] == "continue"
    copied_ids = {
        message.message_id
        for message in repository.list_messages(PROJECT_ID, result.session.session_id)
    }
    assert set(inherited[0]["source_message_ids"]).issubset(copied_ids)


def test_user_content_parts_are_persisted_for_branch_history(tmp_path):
    from app.domain.llm.chat import ChatImageRef, ChatMessageContentPart, ChatMessageContentPartType

    repository = _repository(tmp_path)
    session = _create_session(repository)
    message = repository.append_message(
        PROJECT_ID,
        session.session_id,
        role="user",
        content="image",
        content_parts=(
            ChatMessageContentPart(
                type=ChatMessageContentPartType.IMAGE_REF,
                image_ref=ChatImageRef(path="image.png", mime_type="image/png"),
            ),
        ),
        provider_id="provider-a",
        model_id="model-a",
    )

    restored = repository.list_messages(PROJECT_ID, session.session_id)[0]
    assert restored.message_id == message.message_id
    assert len(restored.content_parts) == 1
    assert restored.content_parts[0].image_ref is not None
    assert restored.content_parts[0].image_ref.path == "image.png"


def test_invalid_branch_graph_is_not_silently_overwritten(tmp_path):
    import pytest

    repository = _repository(tmp_path)
    session = _create_session(repository)
    user = _append(repository, session.session_id, "user", "question")
    _append(repository, session.session_id, "assistant", "answer")
    write_meta(
        tmp_path / ".Tiance" / "conversations",
        "branch_graph",
        "broken",
    )

    with pytest.raises(ConflictError, match="避免覆盖"):
        repository.fork_session(
            PROJECT_ID,
            session.session_id,
            source_message_id=user.message_id,
            draft="changed",
            references=[],
        )

    assert read_meta(
        tmp_path / ".Tiance" / "conversations",
        "branch_graph",
    ) == "broken"


def test_branch_overview_groups_standalone_sessions_and_deduplicates_shared_turns(tmp_path):
    repository = _repository(tmp_path)
    root = _create_session(repository, "主会话")
    first_user = _append(repository, root.session_id, "user", "第一条问题")
    _append(repository, root.session_id, "assistant", "第一条回答")
    second_user = _append(repository, root.session_id, "user", "第二条问题")
    _append(repository, root.session_id, "assistant", "准备调用工具")
    _append(repository, root.session_id, "tool", "工具结果")
    _append(repository, root.session_id, "assistant", "第二条最终回答")

    branch = repository.fork_session(
        PROJECT_ID,
        root.session_id,
        source_message_id=second_user.message_id,
        draft="第二条问题的新方向",
        references=[],
    )
    branch_user = _append(
        repository,
        branch.session.session_id,
        "user",
        "第二条问题的新方向",
    )
    _append(repository, branch.session.session_id, "assistant", "新方向回答")

    standalone = _create_session(repository, "独立会话")
    _append(repository, standalone.session_id, "user", "独立问题")
    _append(repository, standalone.session_id, "assistant", "独立回答")

    sessions = repository.list_sessions(PROJECT_ID)
    branch_nodes, _variants = repository.list_branch_graph(PROJECT_ID)
    groups = build_conversation_branch_groups(sessions, branch_nodes)
    assert len(groups) == 2
    branched_group = next(group for group in groups if root.session_id in group.session_ids)
    standalone_group = next(group for group in groups if standalone.session_id in group.session_ids)
    assert branched_group.is_branched is True
    assert branched_group.title == "主会话"
    assert standalone_group.is_branched is False
    assert standalone_group.session_ids == (standalone.session_id,)

    sessions_by_id = {session.session_id: session for session in sessions}
    detail = build_conversation_branch_group_detail(
        branched_group,
        tuple(
            (
                sessions_by_id[session_id],
                repository.list_messages(PROJECT_ID, session_id),
            )
            for session_id in branched_group.session_ids
        ),
    )
    nodes_by_id = {node.node_id: node for node in detail.nodes}
    assert set(nodes_by_id) == {
        first_user.message_id,
        second_user.message_id,
        branch_user.message_id,
    }
    assert len(nodes_by_id[first_user.message_id].targets) == 2
    assert nodes_by_id[second_user.message_id].assistant_preview == "第二条最终回答"
    assert {
        (edge.source_node_id, edge.target_node_id)
        for edge in detail.edges
    } == {
        (first_user.message_id, second_user.message_id),
        (first_user.message_id, branch_user.message_id),
    }
