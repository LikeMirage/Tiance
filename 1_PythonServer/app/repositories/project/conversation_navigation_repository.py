"""Complete, lightweight navigation, independent of loaded message-body pages."""
from pathlib import Path

from app.domain.project.project_conversation import (
    ProjectConversationNavigation, ProjectConversationNavigationItem,
)
from app.repositories.project.conversation_database import (
    database_path_from_session, read_connection_for_path, read_conversation_snapshot,
    read_message_sync_state, session_id_from_session_dir,
)

PREVIEW_CHARS = 160  # Display preview only; never changes persisted/context content.


def read_navigation(session_dir: Path, *, query: str = "") -> ProjectConversationNavigation:
    query = query.strip()
    # Filter the complete user-message text in SQLite, not the truncated preview.
    # Apply this after numbering/window boundaries so search keeps original turns.
    search_clause = """
        WHERE EXISTS (
            SELECT 1 FROM conversation_messages source
            WHERE source.session_id = ? AND source.message_id = u.message_id
              AND (instr(lower(COALESCE(json_extract(source.payload_json, '$.content'), '')), lower(?)) > 0
                   OR EXISTS (
                       SELECT 1 FROM json_tree(source.payload_json, '$.references') ref
                       WHERE ref.type = 'text'
                         AND ref.key IN ('fileName', 'filePath', 'displayPath', 'content',
                                         'sourceFileName', 'imagePath', 'sheetName', 'rangeAddress')
                         AND instr(lower(ref.value), lower(?)) > 0
                   ))
        )
    """ if query else ""
    session_id = session_id_from_session_dir(session_dir)
    with read_conversation_snapshot(session_dir.parent.parent):
        state = read_message_sync_state(session_dir)
        with read_connection_for_path(database_path_from_session(session_dir)) as connection:
            if connection is None:
                rows = []
            else:
                # SQLite extracts only short user/reply previews. Tool results,
                # thinking, attachments and full message JSON never enter Python.
                rows = connection.execute(
                    f"""
                    WITH users AS MATERIALIZED (
                        SELECT message_id, ordinal,
                            ROW_NUMBER() OVER (ORDER BY ordinal) AS turn_number,
                            LEAD(ordinal) OVER (ORDER BY ordinal) AS next_ordinal,
                            substr(json_extract(payload_json, '$.content'), 1, ?) AS preview
                        FROM conversation_messages
                        WHERE session_id = ? AND json_extract(payload_json, '$.role') = 'user'
                    )
                    SELECT u.message_id, u.preview, a.message_id,
                        CASE WHEN json_extract(a.payload_json, '$.status') != 'running'
                            AND NOT EXISTS (
                                SELECT 1 FROM conversation_messages t
                                WHERE t.session_id = ? AND t.ordinal > a.ordinal
                                  AND t.ordinal < COALESCE(u.next_ordinal, 9223372036854775807)
                                  AND json_extract(t.payload_json, '$.role') = 'tool'
                            )
                        THEN substr(json_extract(a.payload_json, '$.content'), 1, ?) ELSE '' END,
                        u.turn_number
                    FROM users u
                    LEFT JOIN conversation_messages a ON a.session_id = ? AND a.ordinal = (
                        SELECT m.ordinal FROM conversation_messages m
                        WHERE m.session_id = ? AND m.ordinal > u.ordinal
                          AND m.ordinal < COALESCE(u.next_ordinal, 9223372036854775807)
                          AND json_extract(m.payload_json, '$.role') IN ('assistant', 'error')
                        ORDER BY m.ordinal DESC LIMIT 1
                    )
                    {search_clause}
                    ORDER BY u.ordinal
                    """,
                    (PREVIEW_CHARS + 1, session_id, session_id, PREVIEW_CHARS + 1,
                     session_id, session_id) + ((session_id, query, query) if query else ()),
                ).fetchall()
    return ProjectConversationNavigation(
        revision=state["revision"], reset_revision=state["reset_revision"],
        items=tuple(ProjectConversationNavigationItem(
            user_message_id=row[0], turn_number=row[4],
            user_preview=_preview(row[1]), assistant_message_id=row[2], assistant_preview=_preview(row[3]),
        ) for row in rows),
    )


def _preview(value: str | None) -> str:
    text = " ".join((value or "").split())
    return text[:PREVIEW_CHARS].rstrip() + ("…" if len(text) > PREVIEW_CHARS else "")
