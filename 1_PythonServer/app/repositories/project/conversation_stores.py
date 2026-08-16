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
    _DEFAULT_ASSISTANT_TITLE,
    _default_session_state,
    _empty_index,
    _expire_running_state_if_stale,
    _index_pinned_session_ids,
    _index_session_items,
    _message_from_payload,
    _message_to_payload,
    _naming_call_record_to_payload,
    _optional_str,
    _session_from_payload,
    _session_index_payload,
    _session_state_from_payload,
    _session_state_to_payload,
    _session_to_payload,
)
from app.repositories.project.conversation_storage import (
    CONVERSATIONS_DIR,
    ProjectWorkspaceDirectoryResolver,
)
from app.repositories.project.project_repository import ProjectRepository
from app.repositories.project.conversation_records import (
    append_event,
    append_message_payload,
    count_message_payloads,
    delete_session,
    find_message_ordinal,
    list_session_payloads,
    list_message_payloads,
    list_message_payloads_range,
    read_message_turn_payloads,
    read_conversation_control,
    read_session,
    read_session_state,
    replace_message_payloads,
    session_exists,
    write_conversation_control,
    write_session_file,
    write_session_state,
)


class ConversationStateStore:
    def conversation_state(
        self,
        sessions: tuple[ProjectConversationSession, ...],
        index: dict,
    ) -> tuple[str, str | None, dict[str, ProjectConversationSessionState]]:
        session_ids = {session.session_id for session in sessions}
        assistant_title = _DEFAULT_ASSISTANT_TITLE
        active_session_id = _optional_str(index.get("active_session_id"))
        if active_session_id not in session_ids:
            active_session_id = sessions[0].session_id if sessions else None

        raw_states = index.get("session_states", {})
        states: dict[str, ProjectConversationSessionState] = {}
        if isinstance(raw_states, dict):
            for session_id in session_ids:
                states[session_id] = _session_state_from_payload(
                    session_id,
                    raw_states.get(session_id),
                )
        else:
            states = {session_id: _default_session_state(session_id) for session_id in session_ids}
        return assistant_title, active_session_id, states

    def normalize_runtime_states(self, index: dict) -> dict:
        raw_states = index.get("session_states", {})
        if not isinstance(raw_states, dict):
            index["session_states"] = {}
            return index

        for session_id, payload in list(raw_states.items()):
            state = _session_state_from_payload(str(session_id), payload)
            normalized_state = _expire_running_state_if_stale(state)
            raw_states[session_id] = _session_state_to_payload(normalized_state)
        return index


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
        sessions: list[ProjectConversationSession] = []
        pinned_session_ids: list[str] = []
        session_states: dict[str, dict] = {}
        for raw_session in list_session_payloads(conversations_dir):
            session = _session_from_payload(raw_session)
            sessions.append(session)
            state = read_session_state(
                conversations_dir / "sessions" / session.session_id
            )
            if state.get("pinned") is True:
                pinned_session_ids.append(session.session_id)
            runtime = state.get("runtime")
            session_states[session.session_id] = (
                runtime if isinstance(runtime, dict) else {}
            )
        sessions.sort(
            key=lambda session: (session.created_at, session.sequence_number),
            reverse=True,
        )
        control = read_conversation_control(conversations_dir)
        payload = {
            "version": 1,
            "active_session_id": control.get("active_session_id"),
            "pinned_session_ids": sorted(pinned_session_ids),
            "sessions": [_session_index_payload(session) for session in sessions],
            "session_states": session_states,
        }
        return self._state_store.normalize_runtime_states(payload)

    def write_index(self, conversations_dir: Path, payload: dict) -> None:
        live_session_ids = {
            str(item.get("session_id") or "")
            for item in payload.get("sessions", [])
            if isinstance(item, dict) and item.get("session_id")
        }
        active_session_id = _optional_str(payload.get("active_session_id"))
        if active_session_id not in live_session_ids:
            active_session_id = None
        write_conversation_control(
            conversations_dir,
            {"active_session_id": active_session_id},
        )

        pinned = _index_pinned_session_ids(payload) & live_session_ids
        raw_states = payload.get("session_states")
        raw_states = raw_states if isinstance(raw_states, dict) else {}
        for session_id in live_session_ids:
            state_path = (
                conversations_dir
                / "sessions"
                / session_id
                / "state.json"
            )
            if state_path.is_file():
                continue
            runtime = raw_states.get(session_id)
            write_session_state(
                conversations_dir / "sessions" / session_id,
                {
                    "pinned": session_id in pinned,
                    "runtime": runtime if isinstance(runtime, dict) else {},
                },
            )

    def index_with_session(
        self,
        conversations_dir: Path,
        session: ProjectConversationSession,
        *,
        set_active: bool,
    ) -> dict:
        index = self.read_index(conversations_dir)
        sessions = [
            item for item in index.get("sessions", [])
            if isinstance(item, dict) and item.get("session_id") != session.session_id
        ]
        sessions.insert(0, _session_index_payload(session))
        if set_active:
            index["active_session_id"] = session.session_id
        index["sessions"] = sessions
        session_states = index.setdefault("session_states", {})
        if isinstance(session_states, dict) and session.session_id not in session_states:
            session_states[session.session_id] = _session_state_to_payload(
                _default_session_state(session.session_id)
            )
        return index

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

    def write_session(self, session_dir: Path, session: ProjectConversationSession) -> None:
        write_session_file(
            session_dir,
            session.session_id,
            _session_to_payload(session),
        )

    def read_state(
        self,
        session_dir: Path,
        session_id: str,
    ) -> tuple[bool, ProjectConversationSessionState]:
        payload = read_session_state(session_dir)
        runtime = payload.get("runtime")
        return (
            payload.get("pinned") is True,
            _session_state_from_payload(
                session_id,
                runtime if isinstance(runtime, dict) else {},
            ),
        )

    def write_state(
        self,
        session_dir: Path,
        *,
        pinned: bool,
        runtime: ProjectConversationSessionState,
    ) -> None:
        write_session_state(
            session_dir,
            {
                "pinned": pinned,
                "runtime": _session_state_to_payload(runtime),
            },
        )

    def initialize_state(self, session_dir: Path, session_id: str) -> None:
        self.write_state(
            session_dir,
            pinned=False,
            runtime=_default_session_state(session_id),
        )

    def write_active_session(
        self,
        conversations_dir: Path,
        session_id: str | None,
    ) -> None:
        write_conversation_control(
            conversations_dir,
            {"active_session_id": session_id},
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
        replace_message_payloads(session_dir, [])

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
