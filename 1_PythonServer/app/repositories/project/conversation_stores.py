from pathlib import Path
from re import fullmatch
from shutil import rmtree

from app.core.errors import BadRequestError, NotFoundError
from app.domain.project.project_conversation import (
    ProjectConversationMessage,
    ProjectConversationMessagePage,
    ProjectConversationMessageTurn,
    ProjectConversationNamingCallRecord,
    ProjectConversationSession,
    ProjectConversationSessionState,
)
from app.repositories.project.conversation_serialization import (
    _empty_index,
    _expire_running_state_if_stale,
    _index_pinned_session_ids,
    _message_from_payload,
    _message_to_payload,
    _naming_call_record_to_payload,
    _optional_str,
    _session_from_payload,
    _session_state_from_payload,
    _session_to_payload,
)
from app.repositories.project.conversation_storage import (
    CONVERSATIONS_DIR,
    ProjectWorkspaceDirectoryResolver,
)
from app.repositories.project.project_repository import ProjectRepository
from app.repositories.project.conversation_database import (
    append_event,
    append_message_payload,
    count_message_payloads,
    delete_session,
    find_message_ordinal,
    list_message_payloads,
    list_message_payloads_range,
    read_message_turn_payloads,
    read_conversation_list_snapshot,
    read_meta,
    read_session,
    read_session_state_payloads,
    read_sessions,
    replace_message_payloads,
    session_exists,
    write_meta,
    write_session,
    write_session_draft,
    write_session_references,
    write_session_runtime_state,
)


class ConversationStateStore:
    def conversation_state(
        self,
        conversations_dir: Path,
        sessions: tuple[ProjectConversationSession, ...],
        index: dict,
        *,
        stored_states: dict[str, dict] | None = None,
    ) -> tuple[str | None, dict[str, ProjectConversationSessionState]]:
        session_ids = {session.session_id for session in sessions}
        active_session_id = _optional_str(index.get("active_session_id"))
        if active_session_id not in session_ids:
            active_session_id = sessions[0].session_id if sessions else None
        raw_states = (
            read_session_state_payloads(conversations_dir, session_ids)
            if stored_states is None
            else stored_states
        )
        states = {
            session_id: _expire_running_state_if_stale(
                _session_state_from_payload(session_id, raw_states.get(session_id))
            )
            for session_id in session_ids
        }
        return active_session_id, states

    def read_session_state(
        self,
        conversations_dir: Path,
        session_id: str,
    ) -> ProjectConversationSessionState:
        payload = read_session_state_payloads(conversations_dir, {session_id}).get(session_id)
        return _expire_running_state_if_stale(
            _session_state_from_payload(session_id, payload)
        )

    def write_runtime_status(
        self,
        conversations_dir: Path,
        session_id: str,
        runtime_status: str,
        updated_at: str,
    ) -> None:
        write_session_runtime_state(
            conversations_dir,
            session_id,
            runtime_status,
            updated_at,
        )

    def write_draft(
        self,
        conversations_dir: Path,
        session_id: str,
        draft: str,
        updated_at: str,
    ) -> None:
        write_session_draft(conversations_dir, session_id, draft, updated_at)

    def write_references(
        self,
        conversations_dir: Path,
        session_id: str,
        references: list[dict],
        updated_at: str,
    ) -> None:
        write_session_references(
            conversations_dir,
            session_id,
            references,
            updated_at,
        )


class ConversationSessionStore:
    def __init__(
        self,
        project_repository: ProjectRepository,
        *,
        state_store: ConversationStateStore,
        workspace_resolver: ProjectWorkspaceDirectoryResolver | None = None,
    ) -> None:
        self._project_repository = project_repository
        self._state_store = state_store
        self._workspace_resolver = workspace_resolver or ProjectWorkspaceDirectoryResolver()

    def conversations_dir(self, project_id: str, *, for_write: bool = False) -> Path:
        project = self._project_repository.get_project(project_id)
        if project is None:
            raise NotFoundError(f"项目 '{project_id}' 不存在。")
        return self._workspace_resolver.resolve_workspace_dir(
            Path(project.root_path),
            for_write=for_write,
        ) / CONVERSATIONS_DIR

    def session_dir(self, project_id: str, session_id: str, *, for_write: bool = False) -> Path:
        if not fullmatch(r"[A-Za-z0-9_-]+", session_id):
            raise NotFoundError(f"Conversation session '{session_id}' was not found.")
        return self.conversations_dir(project_id, for_write=for_write) / "sessions" / session_id

    def require_session_dir(self, project_id: str, session_id: str, *, for_write: bool = False) -> Path:
        session_dir = self.session_dir(project_id, session_id, for_write=for_write)
        if not session_exists(session_dir.parent.parent, session_id):
            raise NotFoundError(f"Conversation session '{session_id}' was not found.")
        return session_dir

    def read_index(self, conversations_dir: Path) -> dict:
        payload = read_meta(conversations_dir, "conversation_index", _empty_index())
        return self.normalize_index_payload(payload)

    def normalize_index_payload(self, payload: object) -> dict:
        if not isinstance(payload, dict):
            return _empty_index()
        active_session_id = payload.get("active_session_id")
        return {
            "active_session_id": (
                active_session_id if isinstance(active_session_id, str) else None
            ),
            "pinned_session_ids": sorted(_index_pinned_session_ids(payload)),
        }

    def read_list_snapshot(
        self,
        conversations_dir: Path,
    ) -> tuple[
        int,
        dict,
        dict[str, ProjectConversationSession],
        dict[str, dict],
        object,
    ]:
        revision, raw_index, raw_sessions, raw_states, raw_graph = read_conversation_list_snapshot(
            conversations_dir,
        )
        return (
            revision,
            self.normalize_index_payload(raw_index),
            {
                session_id: _session_from_payload(payload)
                for session_id, payload in raw_sessions.items()
            },
            raw_states,
            raw_graph,
        )

    def write_index(self, conversations_dir: Path, payload: dict) -> None:
        write_meta(
            conversations_dir,
            "conversation_index",
            self.normalize_index_payload(payload),
        )

    def index_after_session_write(
        self,
        conversations_dir: Path,
        session: ProjectConversationSession,
        *,
        set_active: bool,
    ) -> dict:
        index = self.read_index(conversations_dir)
        if set_active:
            index["active_session_id"] = session.session_id
        return index

    def next_sequence_number(self, conversations_dir: Path) -> int:
        sessions = self.read_sessions_from_conversations_dir(conversations_dir)
        return max(
            (session.sequence_number for session in sessions.values()),
            default=0,
        ) + 1

    def read_session_state(
        self,
        conversations_dir: Path,
        session_id: str,
    ) -> ProjectConversationSessionState:
        return self._state_store.read_session_state(conversations_dir, session_id)

    def write_session_runtime_status(
        self,
        conversations_dir: Path,
        session_id: str,
        runtime_status: str,
        updated_at: str,
    ) -> None:
        self._state_store.write_runtime_status(
            conversations_dir, session_id, runtime_status, updated_at
        )

    def write_session_draft(
        self,
        conversations_dir: Path,
        session_id: str,
        draft: str,
        updated_at: str,
    ) -> None:
        self._state_store.write_draft(
            conversations_dir, session_id, draft, updated_at
        )

    def write_session_references(
        self,
        conversations_dir: Path,
        session_id: str,
        references: list[dict],
        updated_at: str,
    ) -> None:
        self._state_store.write_references(
            conversations_dir, session_id, references, updated_at
        )

    def read_session(self, project_id: str, session_id: str) -> ProjectConversationSession | None:
        return self.read_session_from_conversations_dir(
            self.conversations_dir(project_id),
            session_id,
        )

    def read_session_from_conversations_dir(
        self,
        conversations_dir: Path,
        session_id: str,
    ) -> ProjectConversationSession | None:
        if not fullmatch(r"[A-Za-z0-9_-]+", session_id):
            return None
        payload = read_session(conversations_dir, session_id)
        if not isinstance(payload, dict):
            return None
        return _session_from_payload(payload)

    def read_sessions_from_conversations_dir(
        self,
        conversations_dir: Path,
    ) -> dict[str, ProjectConversationSession]:
        return {
            session_id: _session_from_payload(payload)
            for session_id, payload in read_sessions(conversations_dir).items()
        }

    def write_session(self, session_dir: Path, session: ProjectConversationSession) -> None:
        write_session(
            session_dir.parent.parent,
            session.session_id,
            _session_to_payload(session),
        )

    def delete_session_dir(self, session_dir: Path, session_id: str) -> None:
        sessions_root = session_dir.parent.resolve()
        resolved_session_dir = session_dir.resolve()
        if resolved_session_dir.parent != sessions_root:
            raise NotFoundError(f"Conversation session '{session_id}' was not found.")
        delete_session(session_dir.parent.parent, session_id)
        if resolved_session_dir.exists():
            rmtree(resolved_session_dir)


class ConversationMessageStore:
    def ensure_messages_file(self, session_dir: Path) -> None:
        return None

    def list_messages(self, session_dir: Path) -> tuple[ProjectConversationMessage, ...]:
        return tuple(
            _message_from_payload(payload)
            for payload in list_message_payloads(session_dir)
        )

    def list_messages_page(
        self,
        session_dir: Path,
        *,
        limit: int | None = None,
        before_message_id: str | None = None,
    ) -> ProjectConversationMessagePage:
        total_count = count_message_payloads(session_dir)
        end_index = total_count
        if before_message_id is not None:
            cursor_index = find_message_ordinal(session_dir, before_message_id)
            if cursor_index is None:
                raise BadRequestError(
                    "before_message_id does not reference a message in this conversation.",
                    details={"parameter": "before_message_id"},
                )
            end_index = cursor_index

        if limit is None:
            messages = tuple(
                _message_from_payload(payload)
                for payload in list_message_payloads_range(
                    session_dir,
                    start_ordinal=0,
                    end_ordinal=end_index,
                )
            )
            return ProjectConversationMessagePage(
                items=messages,
                total_count=total_count,
                has_more=False,
                next_before_message_id=None,
            )

        start_index = max(0, end_index - limit)
        messages = tuple(
            _message_from_payload(payload)
            for payload in list_message_payloads_range(
                session_dir,
                start_ordinal=start_index,
                end_ordinal=end_index,
            )
        )
        if start_index > 0 and messages and messages[0].role == "tool":
            context_start = start_index
            context_messages = messages
            while context_start > 0 and context_messages[0].role == "tool":
                previous_start = max(0, context_start - 32)
                previous = tuple(
                    _message_from_payload(payload)
                    for payload in list_message_payloads_range(
                        session_dir,
                        start_ordinal=previous_start,
                        end_ordinal=context_start,
                    )
                )
                context_messages = previous + context_messages
                context_start = previous_start
            local_start = _extend_start_index_for_tool_context(
                context_messages,
                start_index - context_start,
            )
            if local_start < start_index - context_start:
                start_index = context_start + local_start
                messages = context_messages[local_start:]
        items = messages
        has_more = start_index > 0
        return ProjectConversationMessagePage(
            items=tuple(items),
            total_count=total_count,
            has_more=has_more,
            next_before_message_id=items[0].message_id if has_more and items else None,
        )

    def get_message_turn(
        self,
        session_dir: Path,
        user_message_id: str,
    ) -> ProjectConversationMessageTurn:
        target_role, payloads = read_message_turn_payloads(
            session_dir,
            user_message_id,
        )
        if target_role == "user":
            return ProjectConversationMessageTurn(
                user_message_id=user_message_id,
                items=tuple(_message_from_payload(payload) for payload in payloads),
            )
        if target_role is not None:
            raise BadRequestError(
                "user_message_id does not reference a user message.",
                details={"parameter": "user_message_id"},
            )
        raise NotFoundError(
            f"Conversation user message '{user_message_id}' was not found.",
            details={"parameter": "user_message_id"},
        )

    def append_message(self, session_dir: Path, message: ProjectConversationMessage) -> None:
        append_message_payload(
            session_dir,
            message.message_id,
            _message_to_payload(message),
        )

    def write_messages(
        self,
        session_dir: Path,
        messages: tuple[ProjectConversationMessage, ...],
    ) -> None:
        replace_message_payloads(
            session_dir,
            [_message_to_payload(message) for message in messages],
        )

    def append_naming_call_record(
        self,
        session_dir: Path,
        record: ProjectConversationNamingCallRecord,
    ) -> None:
        append_event(
            session_dir,
            "naming_calls",
            _naming_call_record_to_payload(record),
        )

    def append_model_exchange(self, session_dir: Path, payload: dict) -> None:
        append_event(session_dir, "model_exchanges", payload)


def _extend_start_index_for_tool_context(
    messages: tuple[ProjectConversationMessage, ...],
    start_index: int,
) -> int:
    if start_index <= 0 or start_index >= len(messages):
        return start_index
    if messages[start_index].role != "tool":
        return start_index

    index = start_index - 1
    while index >= 0 and messages[index].role == "tool":
        index -= 1
    if index >= 0 and messages[index].role == "assistant" and messages[index].tool_calls:
        return index
    return start_index
