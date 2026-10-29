"""Trusted identity of the live manager task, separate from persisted turn IDs."""
from contextvars import ContextVar

active_conversation_run: ContextVar[tuple[str, str, str] | None] = ContextVar('active_conversation_run', default=None)


def active_run_id_for(project_id: str | None, session_id: str | None) -> str | None:
    identity = active_conversation_run.get()
    if identity is not None and identity[:2] == (project_id, session_id):
        return identity[2]
    return None
