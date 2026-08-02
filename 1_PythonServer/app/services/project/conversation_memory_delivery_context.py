from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.domain.llm.chat import ChatCompletionRequest, ChatMessage, ChatMessageRole
from app.domain.project.conversation_memory_markers import (
    MEMORY_UPDATE_END_MARKER,
    MEMORY_UPDATE_START_MARKER,
    USER_MESSAGE_START_MARKER,
)
from app.services.project.conversation_memory_delivery_schema import (
    GLOBAL_MEMORY_SCOPE,
    PROJECT_MEMORY_SCOPE,
    normalize_memory_delivery_state,
)
from app.services.project.conversation_memory_delivery_state import apply_memory_changes
from app.services.project.conversation_request_provenance import conversation_message_id


GLOBAL_MEMORY_HEADER = "【全局长期记忆｜适用于所有项目】"
PROJECT_MEMORY_HEADER = "【项目长期记忆｜仅适用于当前项目】"
MEMORY_UPDATE_HEADER = MEMORY_UPDATE_START_MARKER
MEMORY_UPDATE_END = MEMORY_UPDATE_END_MARKER
USER_MESSAGE_HEADER = USER_MESSAGE_START_MARKER
_DRAFT_USER_MESSAGE_ID = "__draft_user_message__"


def draft_user_message_id() -> str:
    return _DRAFT_USER_MESSAGE_ID


def inject_memory_delivery_context(
    request: ChatCompletionRequest,
    state_payload: dict[str, Any],
    *,
    global_enabled: bool,
    project_enabled: bool,
    draft_delivery_target: str | None = None,
) -> ChatCompletionRequest:
    state = normalize_memory_delivery_state(state_payload)
    messages = list(request.messages)
    visible_message_indexes = {
        message_id: index
        for index, message in enumerate(messages)
        if (message_id := conversation_message_id(message)) is not None
    }
    last_user_index = _last_user_message_index(messages)
    baseline = {
        GLOBAL_MEMORY_SCOPE: list(state["baseline"][GLOBAL_MEMORY_SCOPE]["items"]),
        PROJECT_MEMORY_SCOPE: list(state["baseline"][PROJECT_MEMORY_SCOPE]["items"]),
    }
    changes_by_message_index: dict[int, dict[str, list[dict[str, Any]]]] = {}
    found_visible_delivery = False

    for delivery in state["deliveries"]:
        target_message_id = delivery["user_message_id"]
        target_index = visible_message_indexes.get(target_message_id)
        if (
            target_index is None
            and draft_delivery_target is not None
            and target_message_id == draft_delivery_target
        ):
            target_index = last_user_index
        if target_index is None:
            if not found_visible_delivery:
                for scope in (GLOBAL_MEMORY_SCOPE, PROJECT_MEMORY_SCOPE):
                    baseline[scope] = apply_memory_changes(
                        baseline[scope],
                        delivery[scope],
                    )
                continue
            target_index = last_user_index
            if target_index is None:
                continue
        else:
            found_visible_delivery = True
        target_changes = changes_by_message_index.setdefault(
            target_index,
            {
                GLOBAL_MEMORY_SCOPE: [],
                PROJECT_MEMORY_SCOPE: [],
            },
        )
        target_changes[GLOBAL_MEMORY_SCOPE].extend(delivery[GLOBAL_MEMORY_SCOPE])
        target_changes[PROJECT_MEMORY_SCOPE].extend(delivery[PROJECT_MEMORY_SCOPE])

    for index, scoped_changes in changes_by_message_index.items():
        global_changes = scoped_changes[GLOBAL_MEMORY_SCOPE] if global_enabled else []
        project_changes = scoped_changes[PROJECT_MEMORY_SCOPE] if project_enabled else []
        update_text = _memory_update_text(global_changes, project_changes)
        if update_text:
            messages[index] = _prefix_user_message(messages[index], update_text, scoped_changes)

    memory_system_messages: list[ChatMessage] = []
    if global_enabled and baseline[GLOBAL_MEMORY_SCOPE]:
        memory_system_messages.append(
            _memory_snapshot_message(
                GLOBAL_MEMORY_HEADER,
                baseline[GLOBAL_MEMORY_SCOPE],
                scope=GLOBAL_MEMORY_SCOPE,
            )
        )
    if project_enabled and baseline[PROJECT_MEMORY_SCOPE]:
        memory_system_messages.append(
            _memory_snapshot_message(
                PROJECT_MEMORY_HEADER,
                baseline[PROJECT_MEMORY_SCOPE],
                scope=PROJECT_MEMORY_SCOPE,
            )
        )
    if memory_system_messages:
        insert_at = 0
        while insert_at < len(messages) and messages[insert_at].role == ChatMessageRole.SYSTEM:
            insert_at += 1
        messages[insert_at:insert_at] = memory_system_messages
    return replace(request, messages=tuple(messages))


def _memory_snapshot_message(
    header: str,
    items: list[dict[str, Any]],
    *,
    scope: str,
) -> ChatMessage:
    lines = [
        header,
        "以下是应用维护的已确认长期背景。用于理解后续对话；若与用户当前明确表达冲突，以当前表达为准。",
    ]
    lines.extend(
        f"- {item['id']}：{item['content']}"
        for item in items
    )
    return ChatMessage(
        role=ChatMessageRole.SYSTEM,
        content="\n".join(lines),
        preview_metadata={
            "long_term_memory": {
                "kind": "snapshot",
                "scope": scope,
                "item_count": len(items),
            }
        },
    )


def _memory_update_text(
    global_changes: list[dict[str, Any]],
    project_changes: list[dict[str, Any]],
) -> str:
    if not global_changes and not project_changes:
        return ""
    lines = [
        MEMORY_UPDATE_HEADER,
        "以下是应用确认的长期背景变化，不替代用户本轮明确指令。",
    ]
    if global_changes:
        lines.extend(("", "全局长期记忆（适用于所有项目）："))
        lines.extend(_change_lines(global_changes))
    if project_changes:
        lines.extend(("", "项目长期记忆（仅适用于当前项目）："))
        lines.extend(_change_lines(project_changes))
    return "\n".join(lines)


def _change_lines(changes: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for change in changes:
        operation = change["operation"]
        memory_id = change["memory_id"]
        before = change.get("before")
        after = change.get("after")
        lines.extend((
            f"- {memory_id}（{_operation_label(operation)}）",
            f"  变更前：{_memory_value(before, missing='无此记忆')}",
            f"  变更后：{_memory_value(after, missing='已删除')}",
            f"  变更依据：{change.get('reason') or '未记录'}",
        ))
    return lines


def _prefix_user_message(
    message: ChatMessage,
    update_text: str,
    scoped_changes: dict[str, list[dict[str, Any]]],
) -> ChatMessage:
    content = f"{update_text}\n{MEMORY_UPDATE_END}\n\n{USER_MESSAGE_HEADER}"
    if message.content:
        content = f"{content}\n{message.content}"
    metadata = dict(message.preview_metadata)
    metadata["long_term_memory"] = {
        "kind": "updates",
        "global_change_count": len(scoped_changes[GLOBAL_MEMORY_SCOPE]),
        "project_change_count": len(scoped_changes[PROJECT_MEMORY_SCOPE]),
    }
    return replace(message, content=content, preview_metadata=metadata)


def _memory_value(value: object, *, missing: str) -> str:
    if not isinstance(value, dict):
        return missing
    content = value.get("content")
    return content.strip() if isinstance(content, str) and content.strip() else missing


def _operation_label(operation: str) -> str:
    return {
        "add": "新增",
        "update": "更新",
        "delete": "删除",
    }.get(operation, operation)


def _last_user_message_index(messages: list[ChatMessage]) -> int | None:
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == ChatMessageRole.USER:
            return index
    return None
