from dataclasses import dataclass, replace

from app.domain.project.conversation_branch import ProjectConversationBranchNode
from app.domain.project.project_conversation import (
    ProjectConversationMessage,
    ProjectConversationSession,
)


PREVIEW_MAX_LENGTH = 160
USER_MESSAGE_MARKER = "\n\n【用户消息】\n"


@dataclass(frozen=True, slots=True)
class ProjectConversationBranchGroup:
    group_id: str
    root_session_id: str
    title: str
    updated_at: str
    session_ids: tuple[str, ...]
    is_branched: bool


@dataclass(frozen=True, slots=True)
class ProjectConversationBranchTurnTarget:
    session_id: str
    message_id: str


@dataclass(frozen=True, slots=True)
class ProjectConversationBranchTurnNode:
    node_id: str
    variant_group_id: str
    variant_index: int
    user_preview: str
    assistant_preview: str
    reply_status: str
    created_at: str
    targets: tuple[ProjectConversationBranchTurnTarget, ...]


@dataclass(frozen=True, slots=True)
class ProjectConversationBranchTurnEdge:
    source_node_id: str
    target_node_id: str


@dataclass(frozen=True, slots=True)
class ProjectConversationBranchGroupDetail:
    group: ProjectConversationBranchGroup
    nodes: tuple[ProjectConversationBranchTurnNode, ...]
    edges: tuple[ProjectConversationBranchTurnEdge, ...]


def build_conversation_branch_groups(
    sessions: tuple[ProjectConversationSession, ...],
    branch_nodes: tuple[ProjectConversationBranchNode, ...],
) -> tuple[ProjectConversationBranchGroup, ...]:
    sessions_by_id = {session.session_id: session for session in sessions}
    functional_session_ids = {
        node.session_id
        for node in branch_nodes
        if node.deleted_at is None and node.relation_kind == "functional"
    }
    live_nodes = tuple(
        node
        for node in branch_nodes
        if (
            node.deleted_at is None
            and node.session_id in sessions_by_id
            and node.relation_kind != "functional"
        )
    )
    session_node = {node.session_id: node for node in live_nodes}
    nodes_by_tree: dict[str, list[ProjectConversationBranchNode]] = {}
    for node in live_nodes:
        nodes_by_tree.setdefault(node.tree_id, []).append(node)

    groups: list[ProjectConversationBranchGroup] = []
    for tree_id, tree_nodes in nodes_by_tree.items():
        ordered_nodes = sorted(tree_nodes, key=lambda node: node.created_at)
        ordered_sessions = tuple(
            sorted(
                (sessions_by_id[node.session_id] for node in ordered_nodes),
                key=lambda session: session.sequence_number,
            )
        )
        root_node = next(
            (
                node
                for node in ordered_nodes
                if node.parent_branch_id is None
            ),
            ordered_nodes[0],
        )
        title_session = sessions_by_id[root_node.session_id]
        groups.append(
            ProjectConversationBranchGroup(
                group_id=tree_id,
                root_session_id=root_node.session_id,
                title=title_session.title,
                updated_at=max(session.updated_at for session in ordered_sessions),
                session_ids=tuple(session.session_id for session in ordered_sessions),
                is_branched=len(ordered_sessions) > 1,
            )
        )

    for session in sessions:
        if (
            session.session_id in session_node
            or session.session_id in functional_session_ids
        ):
            continue
        groups.append(
            ProjectConversationBranchGroup(
                group_id=f"session:{session.session_id}",
                root_session_id=session.session_id,
                title=session.title,
                updated_at=session.updated_at,
                session_ids=(session.session_id,),
                is_branched=False,
            )
        )

    return tuple(
        sorted(
            groups,
            key=lambda group: (
                sessions_by_id[group.root_session_id].pinned,
                sessions_by_id[group.root_session_id].created_at,
                sessions_by_id[group.root_session_id].sequence_number,
            ),
            reverse=True,
        )
    )


def build_conversation_branch_group_detail(
    group: ProjectConversationBranchGroup,
    session_messages: tuple[
        tuple[ProjectConversationSession, tuple[ProjectConversationMessage, ...]],
        ...,
    ],
) -> ProjectConversationBranchGroupDetail:
    node_order: list[str] = []
    nodes: dict[str, ProjectConversationBranchTurnNode] = {}
    targets: dict[str, list[ProjectConversationBranchTurnTarget]] = {}
    edges: dict[tuple[str, str], ProjectConversationBranchTurnEdge] = {}

    for session, messages in session_messages:
        previous_node_id: str | None = None
        for message_index, message in enumerate(messages):
            if message.role != "user":
                continue
            node_id = message.origin_message_id or message.message_id
            turn_end = _next_user_message_index(messages, message_index + 1)
            final_reply = _find_final_reply(messages, message_index + 1, turn_end)
            reply_status = _reply_status(messages, message_index + 1, turn_end, final_reply)
            target = ProjectConversationBranchTurnTarget(
                session_id=session.session_id,
                message_id=message.message_id,
            )
            if node_id not in nodes:
                node_order.append(node_id)
                nodes[node_id] = ProjectConversationBranchTurnNode(
                    node_id=node_id,
                    variant_group_id=message.variant_group_id or node_id,
                    variant_index=max(1, message.variant_index),
                    user_preview=_preview_user_content(message.content),
                    assistant_preview=_normalize_preview(final_reply.content if final_reply else ""),
                    reply_status=reply_status,
                    created_at=message.created_at,
                    targets=(),
                )
                targets[node_id] = []
            if target not in targets[node_id]:
                targets[node_id].append(target)
            if previous_node_id is not None and previous_node_id != node_id:
                edge_key = (previous_node_id, node_id)
                edges.setdefault(
                    edge_key,
                    ProjectConversationBranchTurnEdge(
                        source_node_id=previous_node_id,
                        target_node_id=node_id,
                    ),
                )
            previous_node_id = node_id

    resolved_nodes = tuple(
        replace(nodes[node_id], targets=tuple(targets[node_id]))
        for node_id in node_order
    )
    return ProjectConversationBranchGroupDetail(
        group=group,
        nodes=resolved_nodes,
        edges=tuple(edges.values()),
    )


def _next_user_message_index(
    messages: tuple[ProjectConversationMessage, ...],
    start: int,
) -> int:
    index = start
    while index < len(messages) and messages[index].role != "user":
        index += 1
    return index


def _find_final_reply(
    messages: tuple[ProjectConversationMessage, ...],
    start: int,
    end: int,
) -> ProjectConversationMessage | None:
    last_tool_index = max(
        (index for index in range(start, end) if messages[index].role == "tool"),
        default=-1,
    )
    for index in range(end - 1, start - 1, -1):
        message = messages[index]
        if index < last_tool_index:
            return None
        if message.role not in {"assistant", "error"}:
            continue
        if message.status == "running" or not message.content.strip():
            continue
        return message
    return None


def _reply_status(
    messages: tuple[ProjectConversationMessage, ...],
    start: int,
    end: int,
    final_reply: ProjectConversationMessage | None,
) -> str:
    if final_reply is not None:
        return "error" if final_reply.role == "error" else "done"
    if any(message.status == "running" for message in messages[start:end]):
        return "running"
    return "missing"


def _preview_user_content(content: str) -> str:
    normalized_content = content.replace("\r\n", "\n")
    marker_index = normalized_content.find(USER_MESSAGE_MARKER)
    if marker_index >= 0:
        normalized_content = normalized_content[marker_index + len(USER_MESSAGE_MARKER):]
    return _normalize_preview(normalized_content)


def _normalize_preview(content: str) -> str:
    normalized = " ".join(content.split())
    if len(normalized) <= PREVIEW_MAX_LENGTH:
        return normalized
    return f"{normalized[:PREVIEW_MAX_LENGTH].rstrip()}..."
