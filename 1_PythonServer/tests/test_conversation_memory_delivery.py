from json import dumps, loads

import pytest

from app.domain.llm.chat import ChatCompletionRequest, ChatMessage, ChatMessageRole
from app.repositories.project.conversation_branch_copy import (
    MEMORY_DELIVERY_FILE,
    write_inherited_memory_delivery_state,
)
from app.services.project.conversation_memory_delivery_context import (
    GLOBAL_MEMORY_HEADER,
    MEMORY_UPDATE_END,
    MEMORY_UPDATE_HEADER,
    PROJECT_MEMORY_HEADER,
    USER_MESSAGE_HEADER,
    inject_memory_delivery_context,
)
from app.services.project.conversation_memory_delivery_state import (
    GLOBAL_MEMORY_SCOPE,
    PROJECT_MEMORY_SCOPE,
    fold_missing_leading_memory_deliveries,
    prepare_memory_delivery_state,
)
from app.services.project.conversation_request_provenance import tag_conversation_message


def test_branch_memory_delivery_keeps_prefix_and_replays_changes_after_branch_point(
    tmp_path,
):
    global_events = [_add_event("gm_1", "初始记忆", reason="初始事实")]
    state = prepare_memory_delivery_state(
        None,
        user_message_id="user-0",
        created_at="2026-07-14T00:00:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
    )
    global_events.append(
        _update_event("gm_1", "分支点记忆", reason="分支点前更新")
    )
    state = prepare_memory_delivery_state(
        state,
        user_message_id="user-1",
        created_at="2026-07-14T00:01:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
    )
    global_events.extend(
        (
            _update_event("gm_1", "最新记忆", reason="分支点后更新"),
            _add_event("gm_2", "新增记忆", reason="分支点后新增"),
        )
    )
    state = prepare_memory_delivery_state(
        state,
        user_message_id="user-2",
        created_at="2026-07-14T00:02:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
    )

    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir()
    target_dir.mkdir()
    (source_dir / MEMORY_DELIVERY_FILE).write_text(
        dumps(state, ensure_ascii=False),
        encoding="utf-8",
    )

    write_inherited_memory_delivery_state(
        source_dir,
        target_dir,
        message_id_map={
            "user-0": "child-user-0",
            "user-1": "child-user-1",
        },
    )

    inherited = loads(
        (target_dir / MEMORY_DELIVERY_FILE).read_text(encoding="utf-8")
    )
    assert inherited["last_prepared_user_message_id"] == "child-user-1"
    assert inherited["cursors"][GLOBAL_MEMORY_SCOPE] == 2
    assert [
        delivery["user_message_id"]
        for delivery in inherited["deliveries"]
    ] == ["child-user-1"]

    continued = prepare_memory_delivery_state(
        inherited,
        user_message_id="child-task",
        created_at="2026-07-14T00:03:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
    )
    replayed = continued["deliveries"][-1]
    assert replayed["user_message_id"] == "child-task"
    assert [
        (change["operation"], change["memory_id"])
        for change in replayed[GLOBAL_MEMORY_SCOPE]
    ] == [
        ("update", "gm_1"),
        ("add", "gm_2"),
    ]


def test_branch_memory_delivery_at_latest_point_does_not_repeat_changes(tmp_path):
    global_events = [_add_event("gm_1", "初始记忆", reason="初始事实")]
    state = prepare_memory_delivery_state(
        None,
        user_message_id="user-0",
        created_at="2026-07-14T00:00:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
    )
    global_events.append(
        _update_event("gm_1", "最新记忆", reason="后续更新")
    )
    state = prepare_memory_delivery_state(
        state,
        user_message_id="user-1",
        created_at="2026-07-14T00:01:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
    )

    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir()
    target_dir.mkdir()
    (source_dir / MEMORY_DELIVERY_FILE).write_text(
        dumps(state, ensure_ascii=False),
        encoding="utf-8",
    )

    write_inherited_memory_delivery_state(
        source_dir,
        target_dir,
        message_id_map={
            "user-0": "child-user-0",
            "user-1": "child-user-1",
        },
    )

    inherited = loads(
        (target_dir / MEMORY_DELIVERY_FILE).read_text(encoding="utf-8")
    )
    assert inherited["last_prepared_user_message_id"] == "child-user-1"
    assert inherited["cursors"][GLOBAL_MEMORY_SCOPE] == len(global_events)
    continued = prepare_memory_delivery_state(
        inherited,
        user_message_id="child-task",
        created_at="2026-07-14T00:02:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
    )
    assert continued["deliveries"] == inherited["deliveries"]


def test_inherited_delivery_recreates_bounded_notification_for_functional_session(
    tmp_path,
):
    global_events = [_add_event("gm_1", "旧规则", reason="初始事实")]
    state = prepare_memory_delivery_state(
        None,
        user_message_id="user-0",
        created_at="2026-07-14T00:00:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
    )
    global_events.append(
        _update_event("gm_1", "新规则", reason="用户明确修改")
    )
    state = prepare_memory_delivery_state(
        state,
        user_message_id="user-1",
        created_at="2026-07-14T00:01:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
    )

    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir()
    target_dir.mkdir()
    (source_dir / MEMORY_DELIVERY_FILE).write_text(
        dumps(state, ensure_ascii=False),
        encoding="utf-8",
    )
    write_inherited_memory_delivery_state(
        source_dir,
        target_dir,
        message_id_map={
            "user-0": "function-user-0",
            "user-1": "function-user-1",
        },
    )
    inherited = loads(
        (target_dir / MEMORY_DELIVERY_FILE).read_text(encoding="utf-8")
    )

    injected = inject_memory_delivery_context(
        _request(
            _tagged_user("function-user-0", "第一轮"),
            ChatMessage(role=ChatMessageRole.ASSISTANT, content="第一轮回复"),
            _tagged_user("function-user-1", "第二轮"),
        ),
        inherited,
        global_enabled=True,
        project_enabled=True,
    )
    notification_message = injected.messages[-1].content

    assert notification_message.startswith(MEMORY_UPDATE_HEADER)
    assert "变更前：旧规则" in notification_message
    assert "变更后：新规则" in notification_message
    assert "变更依据：用户明确修改" in notification_message
    assert (
        f"{MEMORY_UPDATE_END}\n\n{USER_MESSAGE_HEADER}\n第二轮"
        in notification_message
    )


def test_new_session_freezes_labeled_global_and_project_memory_snapshots():
    state = prepare_memory_delivery_state(
        None,
        user_message_id="user-1",
        created_at="2026-07-14T00:00:00+00:00",
        global_events=[_add_event("gm_1", "全局偏好", reason="用户明确表达")],
        project_events=[_add_event("pm_1", "项目约束", reason="项目已确定")],
        global_enabled=True,
        project_enabled=True,
    )
    request = _request(
        ChatMessage(role=ChatMessageRole.SYSTEM, content="主系统提示词"),
        _tagged_user("user-1", "开始"),
    )

    injected = inject_memory_delivery_context(
        request,
        state,
        global_enabled=True,
        project_enabled=True,
    )

    assert [message.role for message in injected.messages[:3]] == [
        ChatMessageRole.SYSTEM,
        ChatMessageRole.SYSTEM,
        ChatMessageRole.SYSTEM,
    ]
    assert injected.messages[0].content == "主系统提示词"
    assert injected.messages[1].content.startswith(GLOBAL_MEMORY_HEADER)
    assert "gm_1：全局偏好" in injected.messages[1].content
    assert injected.messages[2].content.startswith(PROJECT_MEMORY_HEADER)
    assert "pm_1：项目约束" in injected.messages[2].content
    assert injected.messages[-1].content == "开始"


def test_memory_changes_bind_to_next_user_message_and_remain_in_history():
    global_events = [_add_event("gm_1", "旧全局记忆", reason="初始事实")]
    state = prepare_memory_delivery_state(
        None,
        user_message_id="user-1",
        created_at="2026-07-14T00:00:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
    )
    global_events.append(
        _update_event(
            "gm_1",
            "新全局记忆",
            reason="用户明确用新规则替代旧规则",
        )
    )
    state = prepare_memory_delivery_state(
        state,
        user_message_id="user-2",
        created_at="2026-07-14T00:01:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
    )
    request = _request(
        _tagged_user("user-1", "第一轮"),
        ChatMessage(role=ChatMessageRole.ASSISTANT, content="第一轮回复"),
        _tagged_user("user-2", "第二轮"),
        ChatMessage(role=ChatMessageRole.ASSISTANT, content="第二轮回复"),
        _tagged_user("user-3", "第三轮"),
    )

    first = inject_memory_delivery_context(
        request,
        state,
        global_enabled=True,
        project_enabled=True,
    )
    second = inject_memory_delivery_context(
        request,
        state,
        global_enabled=True,
        project_enabled=True,
    )

    first_user_2 = next(message for message in first.messages if "【用户本轮消息】\n第二轮" in message.content)
    second_user_2 = next(message for message in second.messages if "【用户本轮消息】\n第二轮" in message.content)
    assert first_user_2.content == second_user_2.content
    assert first_user_2.content.startswith(MEMORY_UPDATE_HEADER)
    assert f"{MEMORY_UPDATE_END}\n\n{USER_MESSAGE_HEADER}\n第二轮" in first_user_2.content
    assert "变更前：旧全局记忆" in first_user_2.content
    assert "变更后：新全局记忆" in first_user_2.content
    assert "变更依据：用户明确用新规则替代旧规则" in first_user_2.content
    assert first.messages[-1].content == "第三轮"


def test_change_folds_into_snapshot_after_bound_user_message_is_compressed_away():
    global_events = [_add_event("gm_1", "旧内容", reason="初始事实")]
    state = prepare_memory_delivery_state(
        None,
        user_message_id="user-1",
        created_at="2026-07-14T00:00:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
    )
    global_events.append(_update_event("gm_1", "新内容", reason="新事实替代旧事实"))
    state = prepare_memory_delivery_state(
        state,
        user_message_id="user-2",
        created_at="2026-07-14T00:01:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
    )
    compressed_request = _request(
        ChatMessage(role=ChatMessageRole.ASSISTANT, content="- 1-4：较早历史已压缩"),
        _tagged_user("user-3", "继续"),
    )

    injected = inject_memory_delivery_context(
        compressed_request,
        state,
        global_enabled=True,
        project_enabled=True,
    )

    global_snapshot = next(
        message for message in injected.messages
        if message.content.startswith(GLOBAL_MEMORY_HEADER)
    )
    assert "gm_1：新内容" in global_snapshot.content
    assert "旧内容" not in global_snapshot.content
    assert injected.messages[-1].content == "继续"


def test_compressed_leading_deliveries_are_persistently_folded_without_losing_order():
    global_events = [_add_event("gm_1", "旧内容", reason="初始事实")]
    state = _initial_state("user-1", global_events, [])
    global_events.append(_update_event("gm_1", "中间内容", reason="第一次更新"))
    state = prepare_memory_delivery_state(
        state,
        user_message_id="user-2",
        created_at="2026-07-14T00:01:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
    )
    global_events.append(_update_event("gm_1", "最新内容", reason="第二次更新"))
    state = prepare_memory_delivery_state(
        state,
        user_message_id="user-3",
        created_at="2026-07-14T00:02:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
    )

    compacted = fold_missing_leading_memory_deliveries(
        state,
        visible_message_ids={"user-3"},
        updated_at="2026-07-14T00:03:00+00:00",
    )

    assert compacted["baseline"][GLOBAL_MEMORY_SCOPE]["items"][0]["content"] == "中间内容"
    assert compacted["baseline"][GLOBAL_MEMORY_SCOPE]["event_count"] == 2
    assert [item["user_message_id"] for item in compacted["deliveries"]] == ["user-3"]
    injected = inject_memory_delivery_context(
        _request(_tagged_user("user-3", "继续")),
        compacted,
        global_enabled=True,
        project_enabled=True,
    )
    assert "gm_1：中间内容" in injected.messages[0].content
    assert "变更前：中间内容" in injected.messages[-1].content
    assert "变更后：最新内容" in injected.messages[-1].content


def test_missing_delivery_after_visible_history_moves_to_latest_user_instead_of_reordering():
    global_events = [_add_event("gm_1", "旧内容", reason="初始事实")]
    state = _initial_state("user-1", global_events, [])
    global_events.append(_update_event("gm_1", "中间内容", reason="第一次更新"))
    state = prepare_memory_delivery_state(
        state,
        user_message_id="user-2",
        created_at="2026-07-14T00:01:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
    )
    global_events.append(_update_event("gm_1", "最新内容", reason="第二次更新"))
    state = prepare_memory_delivery_state(
        state,
        user_message_id="user-3",
        created_at="2026-07-14T00:02:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
    )

    injected = inject_memory_delivery_context(
        _request(
            _tagged_user("user-2", "仍在历史中"),
            ChatMessage(role=ChatMessageRole.ASSISTANT, content="回复"),
            _tagged_user("user-4", "继续"),
        ),
        state,
        global_enabled=True,
        project_enabled=True,
    )

    assert "变更后：中间内容" in injected.messages[1].content
    assert "变更前：中间内容" in injected.messages[-1].content
    assert "变更后：最新内容" in injected.messages[-1].content


def test_global_changes_reach_every_project_but_project_changes_do_not_cross_projects():
    initial_global = [_add_event("gm_1", "全局初始", reason="全局事实")]
    project_a_initial = [_add_event("pm_a", "项目 A 初始", reason="A 项目事实")]
    project_b_initial = [_add_event("pm_b", "项目 B 初始", reason="B 项目事实")]
    state_a = _initial_state("a-1", initial_global, project_a_initial)
    state_b = _initial_state("b-1", initial_global, project_b_initial)
    changed_global = [
        *initial_global,
        _update_event("gm_1", "全局更新", reason="全局规则已更新"),
    ]
    changed_project_a = [
        *project_a_initial,
        _update_event("pm_a", "项目 A 更新", reason="A 项目规则已更新"),
    ]

    state_a = prepare_memory_delivery_state(
        state_a,
        user_message_id="a-2",
        created_at="2026-07-14T00:01:00+00:00",
        global_events=changed_global,
        project_events=changed_project_a,
        global_enabled=True,
        project_enabled=True,
    )
    state_b = prepare_memory_delivery_state(
        state_b,
        user_message_id="b-2",
        created_at="2026-07-14T00:01:00+00:00",
        global_events=changed_global,
        project_events=project_b_initial,
        global_enabled=True,
        project_enabled=True,
    )

    assert len(state_a["deliveries"][0][GLOBAL_MEMORY_SCOPE]) == 1
    assert len(state_b["deliveries"][0][GLOBAL_MEMORY_SCOPE]) == 1
    assert len(state_a["deliveries"][0][PROJECT_MEMORY_SCOPE]) == 1
    assert state_b["deliveries"][0][PROJECT_MEMORY_SCOPE] == []


def test_memory_delivery_never_truncates_changes_at_one_hundred():
    state = _initial_state("user-1", [], [])
    global_events = [
        _add_event(f"gm_{index}", f"全局记忆 {index}", reason=f"明确事实 {index}")
        for index in range(150)
    ]

    state = prepare_memory_delivery_state(
        state,
        user_message_id="user-2",
        created_at="2026-07-14T00:01:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
    )
    injected = inject_memory_delivery_context(
        _request(_tagged_user("user-2", "接收全部变更")),
        state,
        global_enabled=True,
        project_enabled=True,
    )

    assert len(state["deliveries"][0][GLOBAL_MEMORY_SCOPE]) == 150
    assert "gm_0（新增）" in injected.messages[-1].content
    assert "gm_149（新增）" in injected.messages[-1].content


def test_memory_delivery_rejects_event_log_rewind_instead_of_marking_changes_consumed():
    state = _initial_state(
        "user-1",
        [_add_event("gm_1", "已记录记忆", reason="明确事实")],
        [],
    )

    with pytest.raises(ValueError, match="shorter than its delivery cursor"):
        prepare_memory_delivery_state(
            state,
            user_message_id="user-2",
            created_at="2026-07-14T00:01:00+00:00",
            global_events=[],
            project_events=[],
            global_enabled=True,
            project_enabled=True,
        )


def test_cache_expiry_updates_snapshot_and_keeps_next_message_notification():
    global_events = [_add_event("gm_1", "旧内容", reason="初始事实")]
    state = prepare_memory_delivery_state(
        None,
        user_message_id="user-1",
        created_at="2026-07-14T00:00:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
        cache_provider_id="deepseek",
        cache_model_id="deepseek-v4",
        cache_retention_seconds=300,
    )
    global_events.append(_update_event("gm_1", "新内容", reason="事实更新"))

    state = prepare_memory_delivery_state(
        state,
        user_message_id="user-2",
        created_at="2026-07-14T00:06:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
        cache_provider_id="deepseek",
        cache_model_id="deepseek-v4",
        cache_retention_seconds=300,
    )

    assert state["baseline"][GLOBAL_MEMORY_SCOPE]["items"][0]["content"] == "新内容"
    assert state["deliveries"][-1][GLOBAL_MEMORY_SCOPE][0]["before"]["content"] == "旧内容"
    assert state["deliveries"][-1][GLOBAL_MEMORY_SCOPE][0]["after"]["content"] == "新内容"


def test_active_cache_keeps_snapshot_stable_and_appends_notification_only():
    global_events = [_add_event("gm_1", "旧内容", reason="初始事实")]
    state = prepare_memory_delivery_state(
        None,
        user_message_id="user-1",
        created_at="2026-07-14T00:00:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
        cache_provider_id="deepseek",
        cache_model_id="deepseek-v4",
        cache_retention_seconds=21600,
    )
    global_events.append(_update_event("gm_1", "新内容", reason="事实更新"))

    state = prepare_memory_delivery_state(
        state,
        user_message_id="user-2",
        created_at="2026-07-14T00:06:00+00:00",
        global_events=global_events,
        project_events=[],
        global_enabled=True,
        project_enabled=True,
        cache_provider_id="deepseek",
        cache_model_id="deepseek-v4",
        cache_retention_seconds=21600,
    )

    assert state["baseline"][GLOBAL_MEMORY_SCOPE]["items"][0]["content"] == "旧内容"
    assert state["deliveries"][-1][GLOBAL_MEMORY_SCOPE][0]["after"]["content"] == "新内容"


def _initial_state(user_message_id, global_events, project_events):
    return prepare_memory_delivery_state(
        None,
        user_message_id=user_message_id,
        created_at="2026-07-14T00:00:00+00:00",
        global_events=global_events,
        project_events=project_events,
        global_enabled=True,
        project_enabled=True,
    )


def _request(*messages):
    return ChatCompletionRequest(
        provider_id="openai",
        model_id="gpt-test",
        project_id="project-1",
        session_id="session-1",
        messages=tuple(messages),
    )


def _tagged_user(message_id: str, content: str) -> ChatMessage:
    return tag_conversation_message(
        ChatMessage(role=ChatMessageRole.USER, content=content),
        message_id,
    )


def _add_event(memory_id: str, content: str, *, reason: str) -> dict:
    return {
        "memory_id": memory_id,
        "operation": "add",
        "target_memory_id": None,
        "content": content,
        "keywords": [],
        "reason": reason,
        "created_at": "2026-07-14T00:00:00+00:00",
    }


def _update_event(memory_id: str, content: str, *, reason: str) -> dict:
    return {
        "memory_id": None,
        "operation": "update",
        "target_memory_id": memory_id,
        "content": content,
        "keywords": [],
        "reason": reason,
        "created_at": "2026-07-14T00:01:00+00:00",
    }
