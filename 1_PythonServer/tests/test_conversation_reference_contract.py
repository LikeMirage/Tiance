import pytest
from pydantic import ValidationError

from app.domain.llm.chat import ChatMessageRole
from app.schemas.conversation_references import ConversationReferences
from app.schemas.llm.chat import ChatMessageRequest
from app.schemas.project.project_conversations import ProjectConversationSessionStatePatch


def test_chat_message_reference_contract_preserves_valid_file_reference():
    payload = _file_reference()
    request = ChatMessageRequest(
        role=ChatMessageRole.USER,
        content="检查文件",
        references=[{"type": "file", "reference": payload}],
    )

    message = request.to_domain()

    assert message.content == "检查文件"
    assert message.internal_metadata["conversation_references"] == [
        {"type": "file", "reference": payload}
    ]


def test_chat_message_reference_contract_rejects_incomplete_element():
    with pytest.raises(ValidationError):
        ChatMessageRequest(
            role=ChatMessageRole.USER,
            content="检查文件",
            references=[{
                "type": "file",
                "reference": {"id": "file-1", "filePath": "docs/a.md"},
            }],
        )


def test_draft_reference_contract_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ProjectConversationSessionStatePatch(
            references=[{
                "type": "file",
                "reference": {**_file_reference(), "unexpected": True},
            }]
        )


def test_external_file_reference_survives_persisted_round_trip_without_project_id():
    references = ConversationReferences.model_validate([
        {
            "type": "file",
            "reference": {
                "displayPath": "D:/Videos/meeting.txt",
                "fileName": "meeting.txt",
                "filePath": "D:/Videos/meeting.txt",
                "id": "file-external",
                "kind": "file",
                "projectId": None,
                "source": "external_path",
            },
        }
    ])

    persisted = references.to_payload()
    restored = ConversationReferences.model_validate(persisted)

    assert "projectId" not in persisted[0]["reference"]
    assert restored.root[0].reference.project_id is None


def test_project_file_reference_still_requires_project_id():
    reference = _file_reference()
    reference.pop("projectId")

    with pytest.raises(ValidationError, match="projectId is required"):
        ConversationReferences.model_validate([
            {"type": "file", "reference": reference}
        ])


def _file_reference() -> dict:
    return {
        "displayPath": "docs/a.md",
        "fileName": "a.md",
        "filePath": "docs/a.md",
        "id": "file-1",
        "kind": "file",
        "projectId": "project-a",
        "source": "project_file",
    }
