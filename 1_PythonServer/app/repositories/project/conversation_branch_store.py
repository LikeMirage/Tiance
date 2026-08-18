from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.core.errors import ConflictError
from app.domain.project.conversation_branch import (
    ProjectConversationBranchNode,
    ProjectConversationMessageVariant,
)
from app.domain.project.project_conversation import ProjectConversationSession
from app.repositories.project.conversation_database import read_meta, write_meta

BRANCH_GRAPH_VERSION = 4

CREATED_BY_USER = "user"
CREATED_BY_AI = "ai"
CREATED_BY_SYSTEM = "system"
HISTORY_MODE_EMPTY = "empty"
HISTORY_MODE_FORK = "fork"
HISTORY_MODE_COPY = "copy"
RELATION_KIND_ROOT = "root"
RELATION_KIND_CHILD = "child"
RELATION_KIND_FORK = "fork"
RELATION_KIND_FUNCTIONAL = "functional"
FUNCTION_TYPE_AUTOMATIC_NAMING = "automatic_naming"
FUNCTION_TYPE_MEMORY_COMPACTION = "memory_compaction"
FUNCTION_TYPE_PROJECT_MEMORY_MANAGEMENT = "project_memory_management"
FUNCTION_TYPE_GLOBAL_MEMORY_MANAGEMENT = "global_memory_management"
FUNCTION_TYPES = {
    FUNCTION_TYPE_AUTOMATIC_NAMING,
    FUNCTION_TYPE_GLOBAL_MEMORY_MANAGEMENT,
    FUNCTION_TYPE_MEMORY_COMPACTION,
    FUNCTION_TYPE_PROJECT_MEMORY_MANAGEMENT,
}


class ConversationBranchStore:
    def read_graph(self, conversations_dir: Path) -> dict:
        payload = read_meta(conversations_dir, "branch_graph")
        return self.normalize_graph_payload(payload)

    def normalize_graph_payload(self, payload: object) -> dict:
        if payload is None:
            return _empty_graph()
        if not isinstance(payload, dict):
            raise ConflictError("会话分支关系数据格式无效，已停止写入以避免覆盖。")
        if (
            payload.get("version") != BRANCH_GRAPH_VERSION
            or not _is_dict_list(payload.get("nodes"))
            or not _is_dict_list(payload.get("variants"))
        ):
            raise ConflictError("会话分支关系数据格式无效，已停止写入以避免覆盖。")
        return {
            "version": BRANCH_GRAPH_VERSION,
            "nodes": _dict_items(payload.get("nodes")),
            "variants": _dict_items(payload.get("variants")),
        }

    def write_graph(self, conversations_dir: Path, graph: dict) -> None:
        write_meta(conversations_dir, "branch_graph", graph)

    def list_nodes(self, graph: dict) -> tuple[ProjectConversationBranchNode, ...]:
        return tuple(
            node
            for payload in _dict_items(graph.get("nodes"))
            if (node := _node_from_payload(payload)) is not None
        )

    def list_variants(self, graph: dict) -> tuple[ProjectConversationMessageVariant, ...]:
        return tuple(
            variant
            for payload in _dict_items(graph.get("variants"))
            if (variant := _variant_from_payload(payload)) is not None
        )

    def ensure_root_node(
        self,
        graph: dict,
        session: ProjectConversationSession,
        *,
        created_at: str,
    ) -> ProjectConversationBranchNode:
        existing = self.node_for_session(graph, session.session_id)
        if existing is not None:
            return existing
        node = ProjectConversationBranchNode(
            branch_id=f"branch_{uuid4().hex}",
            tree_id=f"tree_{uuid4().hex}",
            session_id=session.session_id,
            parent_branch_id=None,
            parent_session_id=None,
            relation_kind=RELATION_KIND_ROOT,
            function_type=None,
            created_by=CREATED_BY_USER,
            history_mode=HISTORY_MODE_EMPTY,
            source_message_id=None,
            sibling_index=0,
            created_at=created_at,
        )
        graph.setdefault("nodes", []).append(_node_to_payload(node))
        return node

    def create_child_node(
        self,
        graph: dict,
        *,
        parent: ProjectConversationBranchNode,
        session_id: str,
        created_at: str,
        created_by: str,
        relation_kind: str,
        source_message_id: str | None,
        function_type: str | None = None,
    ) -> ProjectConversationBranchNode:
        normalized_relation_kind = _child_relation_kind(relation_kind)
        history_mode = (
            HISTORY_MODE_FORK
            if normalized_relation_kind == RELATION_KIND_FORK
            else (
                HISTORY_MODE_COPY
                if normalized_relation_kind == RELATION_KIND_FUNCTIONAL
                else HISTORY_MODE_EMPTY
            )
        )
        normalized_function_type = _function_type(function_type)
        if normalized_relation_kind == RELATION_KIND_FUNCTIONAL and normalized_function_type is None:
            raise ValueError("Functional conversations require a function_type.")
        if normalized_relation_kind != RELATION_KIND_FUNCTIONAL:
            normalized_function_type = None
        sibling_index = 1 + max(
            (
                node.sibling_index
                for node in self.list_nodes(graph)
                if node.parent_branch_id == parent.branch_id
                and node.relation_kind == normalized_relation_kind
                and node.function_type == normalized_function_type
            ),
            default=0,
        )
        node = ProjectConversationBranchNode(
            branch_id=f"branch_{uuid4().hex}",
            tree_id=(
                parent.tree_id
                if history_mode == HISTORY_MODE_FORK
                else f"tree_{uuid4().hex}"
            ),
            session_id=session_id,
            parent_branch_id=parent.branch_id,
            parent_session_id=parent.session_id,
            relation_kind=normalized_relation_kind,
            function_type=normalized_function_type,
            created_by=_created_by(created_by),
            history_mode=_history_mode(history_mode),
            source_message_id=source_message_id,
            sibling_index=sibling_index,
            created_at=created_at,
        )
        graph.setdefault("nodes", []).append(_node_to_payload(node))
        return node

    def ensure_source_variant(
        self,
        graph: dict,
        *,
        branch: ProjectConversationBranchNode,
        session_id: str,
        message_id: str,
        origin_message_id: str,
        variant_group_id: str,
        variant_index: int,
        created_at: str,
    ) -> None:
        if any(
            variant.variant_group_id == variant_group_id
            and variant.origin_message_id == origin_message_id
            and variant.deleted_at is None
            for variant in self.list_variants(graph)
        ):
            return
        graph.setdefault("variants", []).append(_variant_to_payload(
            ProjectConversationMessageVariant(
                variant_group_id=variant_group_id,
                variant_index=variant_index,
                branch_id=branch.branch_id,
                session_id=session_id,
                message_id=message_id,
                origin_message_id=origin_message_id,
                created_at=created_at,
            )
        ))

    def create_pending_variant(
        self,
        graph: dict,
        *,
        branch: ProjectConversationBranchNode,
        variant_group_id: str,
        created_at: str,
    ) -> ProjectConversationMessageVariant:
        variant_index = 1 + max(
            (
                variant.variant_index
                for variant in self.list_variants(graph)
                if variant.variant_group_id == variant_group_id
            ),
            default=0,
        )
        variant = ProjectConversationMessageVariant(
            variant_group_id=variant_group_id,
            variant_index=variant_index,
            branch_id=branch.branch_id,
            session_id=branch.session_id,
            message_id=None,
            origin_message_id=None,
            created_at=created_at,
        )
        graph.setdefault("variants", []).append(_variant_to_payload(variant))
        return variant

    def complete_pending_variant(
        self,
        graph: dict,
        *,
        session_id: str,
        message_id: str,
        origin_message_id: str,
    ) -> ProjectConversationMessageVariant | None:
        variants = _dict_items(graph.get("variants"))
        for payload in variants:
            if payload.get("session_id") != session_id or payload.get("message_id"):
                continue
            payload["message_id"] = message_id
            payload["origin_message_id"] = origin_message_id
            return _variant_from_payload(payload)
        return None

    def pending_variant_for_session(
        self,
        graph: dict,
        session_id: str,
    ) -> ProjectConversationMessageVariant | None:
        for variant in self.list_variants(graph):
            if variant.session_id == session_id and variant.message_id is None and variant.deleted_at is None:
                return variant
        return None

    def node_for_session(
        self,
        graph: dict,
        session_id: str,
    ) -> ProjectConversationBranchNode | None:
        for node in self.list_nodes(graph):
            if node.session_id == session_id:
                return node
        return None

    def cache_affinity_session_id(self, graph: dict, session_id: str) -> str:
        nodes_by_session_id = {
            node.session_id: node
            for node in self.list_nodes(graph)
        }
        current_session_id = session_id
        visited_session_ids: set[str] = set()
        while current_session_id not in visited_session_ids:
            visited_session_ids.add(current_session_id)
            node = nodes_by_session_id.get(current_session_id)
            if (
                node is None
                or node.history_mode not in {HISTORY_MODE_FORK, HISTORY_MODE_COPY}
                or node.parent_session_id is None
            ):
                return current_session_id
            current_session_id = node.parent_session_id
        raise ConflictError("会话分支关系存在循环，无法确定缓存谱系。")

    def mark_session_deleted(self, graph: dict, session_id: str, *, deleted_at: str) -> bool:
        changed = False
        for payload in _dict_items(graph.get("nodes")):
            if payload.get("session_id") == session_id and not payload.get("deleted_at"):
                payload["deleted_at"] = deleted_at
                changed = True
        for payload in _dict_items(graph.get("variants")):
            if payload.get("session_id") == session_id and not payload.get("deleted_at"):
                payload["deleted_at"] = deleted_at
                changed = True
        return changed

    def live_descendant_session_ids(
        self,
        graph: dict,
        session_id: str,
    ) -> frozenset[str]:
        """Return live descendants using the persisted parent relation, not UI grouping."""
        nodes_by_session_id = {
            node.session_id: node
            for node in self.list_nodes(graph)
        }
        descendants: set[str] = set()
        for node in nodes_by_session_id.values():
            if node.deleted_at is not None or node.session_id == session_id:
                continue
            visited = {node.session_id}
            parent_session_id = node.parent_session_id
            while parent_session_id is not None:
                if parent_session_id in visited:
                    raise ConflictError("会话分支关系存在循环，无法安全删除会话。")
                if parent_session_id == session_id:
                    descendants.add(node.session_id)
                    break
                visited.add(parent_session_id)
                parent = nodes_by_session_id.get(parent_session_id)
                if parent is None:
                    break
                parent_session_id = parent.parent_session_id
        return frozenset(descendants)

    def delete_sessions_and_reparent(
        self,
        graph: dict,
        session_ids: frozenset[str],
        *,
        deleted_at: str,
    ) -> frozenset[str]:
        """Tombstone selected nodes and reconnect every surviving node to live ancestry."""
        if not session_ids:
            return frozenset()

        node_payloads = _dict_items(graph.get("nodes"))
        payload_by_session_id = {
            str(payload.get("session_id")): payload
            for payload in node_payloads
            if _required_str(payload.get("session_id"))
        }
        promoted_session_ids: set[str] = set()

        for payload in node_payloads:
            current_session_id = _required_str(payload.get("session_id"))
            if not current_session_id or payload.get("deleted_at"):
                continue
            if current_session_id in session_ids:
                payload["deleted_at"] = deleted_at
                continue

            original_parent_session_id = _optional_str(payload.get("parent_session_id"))
            resolved_parent_session_id = _nearest_live_parent_session_id(
                original_parent_session_id,
                payload_by_session_id,
                session_ids,
            )
            if resolved_parent_session_id == original_parent_session_id:
                continue

            resolved_parent = (
                payload_by_session_id.get(resolved_parent_session_id)
                if resolved_parent_session_id is not None
                else None
            )
            payload["parent_session_id"] = resolved_parent_session_id
            payload["parent_branch_id"] = (
                _optional_str(resolved_parent.get("branch_id"))
                if resolved_parent is not None
                else None
            )
            # The old branch point belongs to the removed direct parent. Keeping it
            # would make the persisted relation claim an anchor that no longer exists.
            payload["source_message_id"] = None
            promoted_session_ids.add(current_session_id)

        for payload in _dict_items(graph.get("variants")):
            if (
                _required_str(payload.get("session_id")) in session_ids
                and not payload.get("deleted_at")
            ):
                payload["deleted_at"] = deleted_at

        _renumber_live_siblings(node_payloads)
        return frozenset(promoted_session_ids)


def _empty_graph() -> dict:
    return {"version": BRANCH_GRAPH_VERSION, "nodes": [], "variants": []}


def _dict_items(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _nearest_live_parent_session_id(
    parent_session_id: str | None,
    payload_by_session_id: dict[str, dict],
    deleted_session_ids: frozenset[str],
) -> str | None:
    visited: set[str] = set()
    current_session_id = parent_session_id
    while current_session_id is not None:
        if current_session_id in visited:
            raise ConflictError("会话分支关系存在循环，无法安全删除会话。")
        visited.add(current_session_id)
        parent = payload_by_session_id.get(current_session_id)
        if parent is None:
            return None
        if current_session_id not in deleted_session_ids and not parent.get("deleted_at"):
            return current_session_id
        current_session_id = _optional_str(parent.get("parent_session_id"))
    return None


def _renumber_live_siblings(node_payloads: list[dict]) -> None:
    sibling_groups: dict[tuple[str | None, str, str | None], list[dict]] = {}
    for payload in node_payloads:
        if payload.get("deleted_at"):
            continue
        group_key = (
            _optional_str(payload.get("parent_session_id")),
            _relation_kind(payload.get("relation_kind")),
            _function_type(payload.get("function_type")),
        )
        sibling_groups.setdefault(group_key, []).append(payload)

    for siblings in sibling_groups.values():
        siblings.sort(
            key=lambda payload: (
                _required_str(payload.get("created_at")),
                _required_str(payload.get("session_id")),
            )
        )
        for sibling_index, payload in enumerate(siblings, start=1):
            payload["sibling_index"] = (
                0
                if _optional_str(payload.get("parent_session_id")) is None
                and _relation_kind(payload.get("relation_kind")) == RELATION_KIND_ROOT
                else sibling_index
            )


def _is_dict_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, dict) for item in value)


def _node_from_payload(payload: dict) -> ProjectConversationBranchNode | None:
    branch_id = _required_str(payload.get("branch_id"))
    tree_id = _required_str(payload.get("tree_id"))
    session_id = _required_str(payload.get("session_id"))
    created_at = _required_str(payload.get("created_at"))
    if not branch_id or not tree_id or not session_id or not created_at:
        return None
    return ProjectConversationBranchNode(
        branch_id=branch_id,
        tree_id=tree_id,
        session_id=session_id,
        parent_branch_id=_optional_str(payload.get("parent_branch_id")),
        parent_session_id=_optional_str(payload.get("parent_session_id")),
        relation_kind=_relation_kind(payload.get("relation_kind")),
        function_type=_function_type(payload.get("function_type")),
        created_by=_created_by(payload.get("created_by")),
        history_mode=_history_mode(payload.get("history_mode")),
        source_message_id=_optional_str(payload.get("source_message_id")),
        sibling_index=_non_negative_int(payload.get("sibling_index")),
        created_at=created_at,
        deleted_at=_optional_str(payload.get("deleted_at")),
    )


def _variant_from_payload(payload: dict) -> ProjectConversationMessageVariant | None:
    group_id = _required_str(payload.get("variant_group_id"))
    branch_id = _required_str(payload.get("branch_id"))
    session_id = _required_str(payload.get("session_id"))
    created_at = _required_str(payload.get("created_at"))
    if not group_id or not branch_id or not session_id or not created_at:
        return None
    return ProjectConversationMessageVariant(
        variant_group_id=group_id,
        variant_index=max(1, _non_negative_int(payload.get("variant_index"))),
        branch_id=branch_id,
        session_id=session_id,
        message_id=_optional_str(payload.get("message_id")),
        origin_message_id=_optional_str(payload.get("origin_message_id")),
        created_at=created_at,
        deleted_at=_optional_str(payload.get("deleted_at")),
    )


def _node_to_payload(node: ProjectConversationBranchNode) -> dict:
    return {
        "branch_id": node.branch_id,
        "tree_id": node.tree_id,
        "session_id": node.session_id,
        "parent_branch_id": node.parent_branch_id,
        "parent_session_id": node.parent_session_id,
        "relation_kind": node.relation_kind,
        "function_type": node.function_type,
        "created_by": node.created_by,
        "history_mode": node.history_mode,
        "source_message_id": node.source_message_id,
        "sibling_index": node.sibling_index,
        "created_at": node.created_at,
        "deleted_at": node.deleted_at,
    }


def _variant_to_payload(variant: ProjectConversationMessageVariant) -> dict:
    return {
        "variant_group_id": variant.variant_group_id,
        "variant_index": variant.variant_index,
        "branch_id": variant.branch_id,
        "session_id": variant.session_id,
        "message_id": variant.message_id,
        "origin_message_id": variant.origin_message_id,
        "created_at": variant.created_at,
        "deleted_at": variant.deleted_at,
    }


def _required_str(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _optional_str(value: object) -> str | None:
    normalized = _required_str(value)
    return normalized or None


def _non_negative_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _created_by(value: object) -> str:
    if value == CREATED_BY_AI:
        return CREATED_BY_AI
    if value == CREATED_BY_SYSTEM:
        return CREATED_BY_SYSTEM
    return CREATED_BY_USER


def _history_mode(value: object) -> str:
    if value == HISTORY_MODE_FORK:
        return HISTORY_MODE_FORK
    if value == HISTORY_MODE_COPY:
        return HISTORY_MODE_COPY
    return HISTORY_MODE_EMPTY


def _relation_kind(value: object) -> str:
    if value == RELATION_KIND_CHILD:
        return RELATION_KIND_CHILD
    if value == RELATION_KIND_FORK:
        return RELATION_KIND_FORK
    if value == RELATION_KIND_FUNCTIONAL:
        return RELATION_KIND_FUNCTIONAL
    return RELATION_KIND_ROOT


def _child_relation_kind(value: object) -> str:
    if value == RELATION_KIND_CHILD:
        return RELATION_KIND_CHILD
    if value == RELATION_KIND_FORK:
        return RELATION_KIND_FORK
    if value == RELATION_KIND_FUNCTIONAL:
        return RELATION_KIND_FUNCTIONAL
    raise ValueError("Child conversation relation must be 'child', 'fork', or 'functional'.")


def _function_type(value: object) -> str | None:
    if isinstance(value, str) and value in FUNCTION_TYPES:
        return value
    return None
