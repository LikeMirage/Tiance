from json import dumps, loads
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
    INDEX_FILE,
    MESSAGES_FILE,
    NAMING_CALLS_FILE,
    SESSION_FILE,
    ConversationStorageMigration,
    append_jsonl,
    atomic_write_text,
)
from app.repositories.project.project_repository import ProjectRepository


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
        storage_migration: ConversationStorageMigration | None = None,
    ) -> None:
        self._project_repository = project_repository
        self._state_store = state_store
        self._storage_migration = storage_migration or ConversationStorageMigration()

    def conversations_dir(self, project_id: str, *, for_write: bool = False) -> Path:
        project = self._project_repository.get_project(project_id)
        if project is None:
            raise NotFoundError(f"项目 '{project_id}' 不存在。")
        return self._storage_migration.resolve_workspace_dir(
            Path(project.root_path),
            for_write=for_write,
        ) / CONVERSATIONS_DIR

    def session_dir(self, project_id: str, session_id: str, *, for_write: bool = False) -> Path:
        if not fullmatch(r"[A-Za-z0-9_-]+", session_id):
            raise NotFoundError(f"Conversation session '{session_id}' was not found.")
        return self.conversations_dir(project_id, for_write=for_write) / "sessions" / session_id

    def require_session_dir(self, project_id: str, session_id: str, *, for_write: bool = False) -> Path:
        session_dir = self.session_dir(project_id, session_id, for_write=for_write)
        if not (session_dir / SESSION_FILE).is_file():
            raise NotFoundError(f"Conversation session '{session_id}' was not found.")
        return session_dir

    def read_index(self, conversations_dir: Path) -> dict:
        index_path = conversations_dir / INDEX_FILE
        if not index_path.is_file():
            return _empty_index()
        try:
            payload = loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _empty_index()
        if not isinstance(payload, dict):
            return _empty_index()
        payload.setdefault("active_session_id", None)
        payload["pinned_session_ids"] = sorted(_index_pinned_session_ids(payload))
        payload.setdefault("sessions", [])
        payload.setdefault("session_states", {})
        payload.pop("assistant_title", None)
        return self._state_store.normalize_runtime_states(payload)

    def write_index(self, conversations_dir: Path, payload: dict) -> None:
        conversations_dir.mkdir(parents=True, exist_ok=True)
        payload.pop("assistant_title", None)
        atomic_write_text(
            conversations_dir / INDEX_FILE,
            dumps(payload, ensure_ascii=False, indent=2),
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
        session_path = conversations_dir / "sessions" / session_id / SESSION_FILE
        if not session_path.is_file():
            return None
        try:
            payload = loads(session_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        return _session_from_payload(payload)

    def write_session(self, session_dir: Path, session: ProjectConversationSession) -> None:
        session_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            session_dir / SESSION_FILE,
            dumps(_session_to_payload(session), ensure_ascii=False, indent=2),
        )

    def delete_session_dir(self, session_dir: Path, session_id: str) -> None:
        sessions_root = session_dir.parent.resolve()
        resolved_session_dir = session_dir.resolve()
        if resolved_session_dir.parent != sessions_root:
            raise NotFoundError(f"Conversation session '{session_id}' was not found.")
        rmtree(resolved_session_dir)


class ConversationMessageStore:
    def ensure_messages_file(self, session_dir: Path) -> None:
        messages_path = session_dir / MESSAGES_FILE
        if messages_path.exists():
            return
        atomic_write_text(messages_path, "")

    def list_messages(self, session_dir: Path) -> tuple[ProjectConversationMessage, ...]:
        messages_path = session_dir / MESSAGES_FILE
        if not messages_path.is_file():
            return ()

        messages: list[ProjectConversationMessage] = []
        for line in messages_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = loads(line)
            except ValueError:
                continue
            if isinstance(payload, dict):
                messages.append(_message_from_payload(payload))
        return tuple(messages)

    def list_messages_page(
        self,
        session_dir: Path,
        *,
        limit: int | None = None,
        before_message_id: str | None = None,
    ) -> ProjectConversationMessagePage:
        messages = self.list_messages(session_dir)
        total_count = len(messages)
        end_index = total_count
        if before_message_id is not None:
            cursor_index = None
            for index, message in enumerate(messages):
                if message.message_id == before_message_id:
                    cursor_index = index
                    break
            if cursor_index is None:
                raise BadRequestError(
                    "before_message_id does not reference a message in this conversation.",
                    details={"parameter": "before_message_id"},
                )
            end_index = cursor_index

        if limit is None:
            return ProjectConversationMessagePage(
                items=messages[:end_index],
                total_count=total_count,
                has_more=False,
                next_before_message_id=None,
            )

        start_index = _extend_start_index_for_tool_context(
            messages,
            max(0, end_index - limit),
        )
        items = messages[start_index:end_index]
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
        messages_path = session_dir / MESSAGES_FILE
        target_messages: list[ProjectConversationMessage] | None = None
        matched_non_user_message = False

        if messages_path.is_file():
            with messages_path.open("r", encoding="utf-8") as source:
                for line in source:
                    if not line.strip():
                        continue
                    try:
                        payload = loads(line)
                    except ValueError:
                        continue
                    if not isinstance(payload, dict):
                        continue

                    message = _message_from_payload(payload)
                    if target_messages is not None:
                        if message.role == "user":
                            break
                        target_messages.append(message)
                        continue

                    if message.message_id != user_message_id:
                        continue
                    if message.role != "user":
                        matched_non_user_message = True
                        continue
                    target_messages = [message]

        if target_messages is not None:
            return ProjectConversationMessageTurn(
                user_message_id=user_message_id,
                items=tuple(target_messages),
            )
        if matched_non_user_message:
            raise BadRequestError(
                "user_message_id does not reference a user message.",
                details={"parameter": "user_message_id"},
            )
        raise NotFoundError(
            f"Conversation user message '{user_message_id}' was not found.",
            details={"parameter": "user_message_id"},
        )

    def append_message(self, session_dir: Path, message: ProjectConversationMessage) -> None:
        append_jsonl(session_dir / MESSAGES_FILE, _message_to_payload(message))

    def write_messages(
        self,
        session_dir: Path,
        messages: tuple[ProjectConversationMessage, ...],
    ) -> None:
        content = "".join(
            f"{dumps(_message_to_payload(message), ensure_ascii=False, separators=(',', ':'))}\n"
            for message in messages
        )
        atomic_write_text(session_dir / MESSAGES_FILE, content)

    def append_naming_call_record(
        self,
        session_dir: Path,
        record: ProjectConversationNamingCallRecord,
    ) -> None:
        append_jsonl(session_dir / NAMING_CALLS_FILE, _naming_call_record_to_payload(record))


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
