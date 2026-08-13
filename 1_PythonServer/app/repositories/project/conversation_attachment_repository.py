from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from re import fullmatch
from shutil import copy2
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.core.errors import NotFoundError
from app.domain.llm.chat import ChatMessageContentPartType
from app.domain.project.project_conversation import ProjectConversationMessage
from app.repositories.project.conversation_database import append_event, read_events
from app.repositories.project.conversation_storage import conversation_write_lock
from app.repositories.project.conversation_stores import (
    ConversationSessionStore,
    ConversationStateStore,
)
from app.repositories.project.project_repository import (
    ProjectRepository,
    get_project_repository,
)

ATTACHMENTS_DIR = "attachments"
ATTACHMENT_URI_PREFIX = "tiance-attachment://"


@dataclass(frozen=True, slots=True)
class ConversationAttachment:
    attachment_id: str
    stored_name: str
    display_name: str
    mime_type: str
    size_bytes: int
    sha256: str
    source_kind: str
    source_path: str | None
    created_at: str

    @property
    def uri(self) -> str:
        return f"{ATTACHMENT_URI_PREFIX}{self.attachment_id}"


class ConversationAttachmentRepository:
    def __init__(
        self,
        project_repository: ProjectRepository,
        *,
        session_store: ConversationSessionStore | None = None,
    ) -> None:
        self._session_store = session_store or ConversationSessionStore(
            project_repository,
            state_store=ConversationStateStore(),
        )

    def save_bytes(
        self,
        project_id: str,
        session_id: str,
        *,
        content: bytes,
        suffix: str,
        display_name: str,
        mime_type: str,
        source_kind: str,
        source_path: str | None,
        created_at: str,
    ) -> ConversationAttachment:
        content_sha256 = sha256(content).hexdigest()
        conversations_dir = self._session_store.conversations_dir(
            project_id,
            for_write=True,
        )
        with conversation_write_lock(conversations_dir):
            session_dir = self._session_store.require_session_dir(
                project_id,
                session_id,
                for_write=True,
            )
            attachments_dir = session_dir / ATTACHMENTS_DIR
            existing = _find_matching_attachment(
                session_dir,
                content_sha256=content_sha256,
                source_kind=source_kind,
                source_path=source_path,
            )
            if (
                existing is not None
                and (attachments_dir / existing.stored_name).is_file()
            ):
                return existing
            attachment_id = f"att_{uuid4().hex}"
            stored_name = f"{attachment_id}{_safe_suffix(suffix)}"
            attachments_dir.mkdir(parents=True, exist_ok=True)
            target_path = attachments_dir / stored_name
            temporary_path = attachments_dir / f".{stored_name}.{uuid4().hex}.tmp"
            size_bytes = len(content)
            try:
                with temporary_path.open("wb") as target:
                    target.write(content)
                atomic_replace_path(temporary_path, target_path)
            finally:
                temporary_path.unlink(missing_ok=True)

            attachment = ConversationAttachment(
                attachment_id=attachment_id,
                stored_name=stored_name,
                display_name=display_name,
                mime_type=mime_type,
                size_bytes=size_bytes,
                sha256=content_sha256,
                source_kind=source_kind,
                source_path=source_path,
                created_at=created_at,
            )
            append_event(
                session_dir,
                "attachments",
                _attachment_to_payload(attachment),
            )
            return attachment

    def read(
        self,
        project_id: str,
        session_id: str,
        attachment_uri: str,
    ) -> tuple[ConversationAttachment, Path]:
        attachment_id = attachment_id_from_uri(attachment_uri)
        session_dir = self._session_store.require_session_dir(project_id, session_id)
        attachments_dir = session_dir / ATTACHMENTS_DIR
        attachment = _find_attachment(
            session_dir,
            attachment_id,
        )
        if attachment is None:
            raise NotFoundError("会话附件记录不存在。")
        path = attachments_dir / attachment.stored_name
        if not path.is_file():
            raise NotFoundError("会话附件文件不存在。")
        return attachment, path


def attachment_id_from_uri(value: str) -> str:
    if not value.startswith(ATTACHMENT_URI_PREFIX):
        raise NotFoundError("会话附件地址无效。")
    attachment_id = value.removeprefix(ATTACHMENT_URI_PREFIX)
    if not fullmatch(r"att_[a-f0-9]{32}", attachment_id):
        raise NotFoundError("会话附件地址无效。")
    return attachment_id


def is_attachment_uri(value: str) -> bool:
    try:
        attachment_id_from_uri(value)
    except NotFoundError:
        return False
    return True


def get_conversation_attachment_repository() -> ConversationAttachmentRepository:
    return ConversationAttachmentRepository(get_project_repository())


def copy_referenced_attachments(
    source_session_dir: Path,
    target_session_dir: Path,
    messages: tuple[ProjectConversationMessage, ...],
    references: list[dict] | None = None,
) -> None:
    attachment_ids = {
        part.image_ref.attachment_id
        for message in messages
        for part in message.content_parts
        if part.type == ChatMessageContentPartType.IMAGE_REF
        and part.image_ref is not None
        and part.image_ref.attachment_id
    }
    attachment_ids.update(_attachment_ids_from_value(references or []))
    if not attachment_ids:
        return
    source_dir = source_session_dir / ATTACHMENTS_DIR
    target_dir = target_session_dir / ATTACHMENTS_DIR
    records = [
        attachment
        for attachment_id in sorted(attachment_ids)
        if (attachment := _find_attachment(
            source_session_dir,
            attachment_id,
        )) is not None
    ]
    if len(records) != len(attachment_ids):
        raise NotFoundError("分支所需的会话附件记录不完整。")
    target_dir.mkdir(parents=True, exist_ok=True)
    for attachment in records:
        source_file = source_dir / attachment.stored_name
        if not source_file.is_file():
            raise NotFoundError("分支所需的会话附件文件不存在。")
        copy2(source_file, target_dir / attachment.stored_name)
        append_event(
            target_session_dir,
            "attachments",
            _attachment_to_payload(attachment),
        )


def _attachment_ids_from_value(value: object) -> set[str]:
    ids: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            ids.update(_attachment_ids_from_value(item))
    elif isinstance(value, list):
        for item in value:
            ids.update(_attachment_ids_from_value(item))
    elif isinstance(value, str) and is_attachment_uri(value):
        ids.add(attachment_id_from_uri(value))
    return ids


def _safe_suffix(value: str) -> str:
    suffix = value.lower()
    return suffix if fullmatch(r"\.[a-z0-9]{1,10}", suffix) else ""


def _find_attachment(session_dir: Path, attachment_id: str) -> ConversationAttachment | None:
    for payload in read_events(session_dir, "attachments"):
        if payload.get("attachment_id") == attachment_id:
            return _attachment_from_payload(payload)
    return None


def _find_matching_attachment(
    session_dir: Path,
    *,
    content_sha256: str,
    source_kind: str,
    source_path: str | None,
) -> ConversationAttachment | None:
    for payload in read_events(session_dir, "attachments"):
        attachment = _attachment_from_payload(payload)
        if (
            attachment.sha256 == content_sha256
            and attachment.source_kind == source_kind
            and attachment.source_path == source_path
        ):
            return attachment
    return None


def _attachment_to_payload(value: ConversationAttachment) -> dict:
    return {
        "attachment_id": value.attachment_id,
        "stored_name": value.stored_name,
        "display_name": value.display_name,
        "mime_type": value.mime_type,
        "size_bytes": value.size_bytes,
        "sha256": value.sha256,
        "source_kind": value.source_kind,
        "source_path": value.source_path,
        "created_at": value.created_at,
    }


def _attachment_from_payload(payload: dict) -> ConversationAttachment:
    return ConversationAttachment(
        attachment_id=str(payload.get("attachment_id") or ""),
        stored_name=str(payload.get("stored_name") or ""),
        display_name=str(payload.get("display_name") or ""),
        mime_type=str(payload.get("mime_type") or ""),
        size_bytes=int(payload.get("size_bytes") or 0),
        sha256=str(payload.get("sha256") or ""),
        source_kind=str(payload.get("source_kind") or ""),
        source_path=(
            str(payload["source_path"])
            if isinstance(payload.get("source_path"), str)
            else None
        ),
        created_at=str(payload.get("created_at") or ""),
    )
