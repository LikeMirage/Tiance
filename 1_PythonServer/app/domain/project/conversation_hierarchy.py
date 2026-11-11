"""Read-only visible hierarchy, matching the desktop conversation tree.

Sessions are the source of membership and display order; branch nodes only
describe relationships. An independent session need not have a branch node.
"""

FUNCTION_GROUPS = frozenset({
    "automatic_naming", "memory_compaction", "project_memory_management",
    "global_memory_management",
})


def visible_conversation_parents(sessions, nodes):
    """Return session -> (nearest visible parent, leaf group), without writes."""
    live_ids = {session.session_id for session in sessions}
    relations = {node.session_id: node for node in nodes}
    parents = {}
    for session in sessions:
        node = relations.get(session.session_id)
        if node is None or node.deleted_at:
            continue
        if node.relation_kind in {"child", "fork"}:
            group = node.relation_kind
        elif node.relation_kind == "functional" and node.function_type in FUNCTION_GROUPS:
            group = node.function_type
        else:
            continue
        parent_id = node.parent_session_id
        visited = set()
        while parent_id and parent_id not in visited:
            visited.add(parent_id)
            parent = relations.get(parent_id)
            if parent is None:
                break
            if not parent.deleted_at and parent_id in live_ids:
                if parent_id != session.session_id:
                    parents[session.session_id] = (parent_id, group)
                break
            parent_id = parent.parent_session_id

    # As on desktop, break malformed cycles in display order so every session
    # remains reachable. Do not repair or rewrite the stored relationship graph.
    for session_id in list(parents):
        visited = {session_id}
        current = parents[session_id][0]
        while current:
            if current in visited:
                del parents[session_id]
                break
            visited.add(current)
            current = parents.get(current, (None, None))[0]
    return parents
