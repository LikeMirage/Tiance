"""Recent user/answer history without loading tool results or thinking bodies."""
import json
from pathlib import Path

from .conversation_database import (
    database_path_from_session, read_connection_for_path,
    read_conversation_snapshot, session_id_from_session_dir,
)


def read_recent_history(session_dir: Path, limit: int):
    if limit < 1:
        raise ValueError('History limit must be positive.')
    session_id = session_id_from_session_dir(session_dir)
    turns = []
    with read_conversation_snapshot(session_dir.parent.parent):
        with read_connection_for_path(database_path_from_session(session_dir)) as connection:
            if connection is None:
                return turns
            users = connection.execute("""
                SELECT message_id,ordinal,json_extract(payload_json,'$.content'),
                       json_extract(payload_json,'$.references'),
                       json_extract(payload_json,'$.created_at')
                FROM conversation_messages
                WHERE session_id=? AND json_extract(payload_json,'$.role')='user'
                ORDER BY ordinal DESC LIMIT ?
            """, (session_id, limit)).fetchall()
            end = 9223372036854775807
            for user_id, ordinal, content, references, created_at in users:
                # The last assistant/tool entry determines whether a final answer
                # exists. Text preceding an unfinished tool call is not the answer.
                answer = connection.execute("""
                    SELECT json_extract(payload_json,'$.role'),
                           CASE WHEN json_extract(payload_json,'$.role')='assistant'
                                THEN json_extract(payload_json,'$.content') ELSE '' END,
                           json_extract(payload_json,'$.status'),
                           coalesce(json_array_length(payload_json,'$.tool_calls'),0)
                    FROM conversation_messages
                    WHERE session_id=? AND ordinal>? AND ordinal<?
                      AND json_extract(payload_json,'$.role') IN ('assistant','tool')
                    ORDER BY ordinal DESC LIMIT 1
                """, (session_id, ordinal, end)).fetchone()
                errors = connection.execute("""
                    SELECT json_extract(payload_json,'$.content') FROM conversation_messages
                    WHERE session_id=? AND ordinal>? AND ordinal<?
                      AND json_extract(payload_json,'$.role')='error' ORDER BY ordinal
                """, (session_id, ordinal, end)).fetchall()
                outcome = connection.execute("""
                    SELECT status,error_message FROM conversation_runs
                    WHERE session_id=? AND user_message_id=?
                    ORDER BY started_at DESC,run_id DESC LIMIT 1
                """, (session_id, user_id)).fetchone()
                final = bool(answer and answer[0] == 'assistant' and not answer[3])
                turns.append(dict(
                    user_message_id=user_id, user_content=content or '',
                    references=json.loads(references) if references else [], created_at=created_at,
                    assistant_content=(answer[1] or '') if final else '',
                    status=outcome[0] if outcome else (answer[2] if answer else None),
                    errors=list(dict.fromkeys([r[0] for r in errors if r[0]] +
                                              ([outcome[1]] if outcome and outcome[1] else []))),
                ))
                end = ordinal
    return list(reversed(turns))
