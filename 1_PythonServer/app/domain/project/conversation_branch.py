from dataclasses import dataclass

from app.domain.project.project_conversation import (
    ProjectConversationMessage,
    ProjectConversationSession,
    ProjectConversationSessionState,
)


def build_derived_session_title(source_title: str, sibling_index: int) -> str:
    return f"{source_title}_{sibling_index}"


@dataclass(frozen=True, slots=True)
class ProjectConversationBranchNode:
    branch_id: str
    tree_id: str
    session_id: str
    parent_branch_id: str | None
    parent_session_id: str | None
    relation_kind: str
    function_type: str | None
    created_by: str
    history_mode: str
    source_message_id: str | None
    sibling_index: int
    created_at: str
    deleted_at: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectConversationMessageVariant:
    variant_group_id: str
    variant_index: int
    branch_id: str
    session_id: str
    message_id: str | None
    origin_message_id: str | None
    created_at: str
    deleted_at: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectConversationForkResult:
    session: ProjectConversationSession
    state: ProjectConversationSessionState
    branch: ProjectConversationBranchNode
    source_message: ProjectConversationMessage
