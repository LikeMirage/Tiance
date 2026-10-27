from hashlib import sha256
from unittest.mock import Mock

import pytest

from app.core.errors import NotFoundError
from app.domain.llm.chat import ChatImageRef, ChatMessageContentPart, ChatMessageContentPartType
from app.repositories.project import conversation_attachment_repository as attachments
from app.repositories.project.conversation_database import append_event, read_events
from tests.test_project_conversation_branching import PROJECT_ID, _append, _create_session, _repository


def _add_attachment(session_dir, number):
    attachment_id = f"att_{number:032x}"
    content = f"image {number}".encode()
    payload = {
        "attachment_id": attachment_id,
        "stored_name": f"{attachment_id}.png",
        "display_name": f"图片 {number}.png",
        "mime_type": "image/png",
        "size_bytes": len(content),
        "sha256": sha256(content).hexdigest(),
        "source_kind": "external_file",
        "source_path": f"C:/images/{number}.png",
        "created_at": "2026-10-27T00:00:00Z",
    }
    folder = session_dir / attachments.ATTACHMENTS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / payload["stored_name"]).write_bytes(content)
    append_event(session_dir, "attachments", payload)
    return payload


def _setup(tmp_path):
    repository = _repository(tmp_path)
    session = _create_session(repository)
    source_dir = repository._session_store.session_dir(PROJECT_ID, session.session_id)
    return repository, session, source_dir


def test_real_fork_reads_attachment_records_once_for_history_and_draft_refs(tmp_path, monkeypatch):
    repository, session, source_dir = _setup(tmp_path)
    payloads = [_add_attachment(source_dir, i) for i in range(31)]
    parts = tuple(ChatMessageContentPart(
        type=ChatMessageContentPartType.IMAGE_REF,
        image_ref=ChatImageRef(
            path=attachments.ATTACHMENT_URI_PREFIX + payload["attachment_id"],
            attachment_id=payload["attachment_id"], mime_type="image/png",
        ),
    ) for payload in payloads[:20])
    repository.append_message(
        PROJECT_ID, session.session_id, role="user", content="历史图片", content_parts=parts,
        status="done",
    )
    source_message = _append(repository, session.session_id, "user", "从这里编辑")
    repository.save_session_runtime_status(PROJECT_ID, session.session_id, "idle")
    references = [{"nested": [{"path": attachments.ATTACHMENT_URI_PREFIX + payload["attachment_id"]}]}
                  for payload in payloads[10:30]]
    reads = Mock(wraps=attachments.read_events)
    copies = Mock(wraps=attachments.copy2)
    monkeypatch.setattr(attachments, "read_events", reads)
    monkeypatch.setattr(attachments, "copy2", copies)

    fork = repository.fork_session(
        PROJECT_ID, session.session_id, source_message_id=source_message.message_id,
        draft="修改后的消息", references=references,
    )
    reads.assert_called_once_with(source_dir, "attachments")
    assert copies.call_count == 30
    target_dir = repository._session_store.session_dir(PROJECT_ID, fork.session.session_id)
    assert read_events(target_dir, "attachments") == payloads[:30]
    target_files = list((target_dir / attachments.ATTACHMENTS_DIR).iterdir())
    assert len(target_files) == 30
    for payload in payloads[:30]:
        filename = payload["stored_name"]
        assert (target_dir / attachments.ATTACHMENTS_DIR / filename).read_bytes() == (
            source_dir / attachments.ATTACHMENTS_DIR / filename
        ).read_bytes()
    assert not (target_dir / attachments.ATTACHMENTS_DIR / payloads[30]["stored_name"]).exists()
    assert read_events(source_dir, "attachments") == payloads


def test_no_attachment_references_does_not_query_or_create_directory(tmp_path, monkeypatch):
    reads = Mock(side_effect=AssertionError("no attachments should not query"))
    monkeypatch.setattr(attachments, "read_events", reads)
    target_dir = tmp_path / "target"
    attachments.copy_referenced_attachments(tmp_path / "source", target_dir, (), [{"path": "plain.txt"}])
    reads.assert_not_called()
    assert not target_dir.exists()


def test_duplicate_ids_keep_first_record_and_unrelated_bad_metadata_is_ignored(tmp_path):
    repository, source, source_dir = _setup(tmp_path)
    target = _create_session(repository)
    target_dir = repository._session_store.session_dir(PROJECT_ID, target.session_id)
    payload = _add_attachment(source_dir, 1)
    append_event(source_dir, "attachments", {**payload, "stored_name": "nonexistent.png", "size_bytes": "bad"})
    append_event(source_dir, "attachments", {"attachment_id": ["invalid"], "size_bytes": "bad"})
    append_event(source_dir, "attachments", {"attachment_id": "unreferenced", "size_bytes": "bad"})
    attachments.copy_referenced_attachments(
        source_dir, target_dir, (), [{"path": attachments.ATTACHMENT_URI_PREFIX + payload["attachment_id"]}],
    )
    assert read_events(target_dir, "attachments") == [payload]
    assert (target_dir / attachments.ATTACHMENTS_DIR / payload["stored_name"]).read_bytes() == b"image 1"


@pytest.mark.parametrize("missing", ["record", "file"])
def test_missing_attachment_still_rejects_fork_and_rolls_back(tmp_path, missing):
    repository, session, source_dir = _setup(tmp_path)
    payload = _add_attachment(source_dir, 1)
    if missing == "file":
        (source_dir / attachments.ATTACHMENTS_DIR / payload["stored_name"]).unlink()
        requested = payload["attachment_id"]
    else:
        requested = f"att_{2:032x}"
    source_message = _append(repository, session.session_id, "user", "从这里编辑")
    repository.save_session_runtime_status(PROJECT_ID, session.session_id, "idle")
    with pytest.raises(NotFoundError, match="记录不完整" if missing == "record" else "文件不存在"):
        repository.fork_session(
            PROJECT_ID, session.session_id, source_message_id=source_message.message_id, draft="新草稿",
            references=[{"path": attachments.ATTACHMENT_URI_PREFIX + requested}],
        )
    assert [item.session_id for item in repository.list_sessions(PROJECT_ID)] == [session.session_id]
    assert not list(source_dir.parent.glob("*.tmp-*"))
    assert read_events(source_dir, "attachments") == [payload]
