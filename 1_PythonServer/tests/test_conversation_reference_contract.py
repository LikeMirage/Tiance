import pytest
from pydantic import ValidationError

from app.domain.llm.chat import ChatMessageRole
from app.schemas.conversation_references import ConversationReferences
from app.schemas.llm.chat import ChatMessageRequest
from app.schemas.project.project_conversations import ProjectConversationStateSaveRequest


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
        ProjectConversationStateSaveRequest(
            session_references={
                "session-1": [{
                    "type": "file",
                    "reference": {**_file_reference(), "unexpected": True},
                }]
            }
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


def test_word_text_reference_preserves_structured_location():
    payload = {
        "type": "text",
        "reference": {
            "content": "并联电阻公式",
            "contentMarkdown": "$\\frac{1}{R}=\\frac{1}{R_1}+\\frac{1}{R_2}$",
            "displayPath": "docs/formulas.docx",
            "fileName": "formulas.docx",
            "filePath": "docs/formulas.docx",
            "id": "word-text-1",
            "documentFingerprint": "sha256:" + "a" * 64,
            "location": {
                "kind": "word_range",
                "nearestHeading": "2.4 公式与结果对照表",
                "prefix": "电阻并联",
                "start": {
                    "cellParagraphIndex": 1,
                    "characterOffset": 0,
                    "columnIndex": 2,
                    "container": "table",
                    "pageNumber": 3,
                    "paragraphIndex": 110,
                    "rowIndex": 5,
                    "tableIndex": 3,
                },
                "end": {
                    "cellParagraphIndex": 1,
                    "characterOffset": 8,
                    "columnIndex": 2,
                    "container": "table",
                    "pageNumber": 3,
                    "paragraphIndex": 110,
                    "rowIndex": 5,
                    "tableIndex": 3,
                },
                "suffix": "R1=6, R2=3",
            },
            "projectId": "project-a",
            "source": "office",
        },
    }

    references = ConversationReferences.model_validate([payload])

    assert references.to_payload() == [payload]


def test_word_text_reference_rejects_invalid_location_coordinates():
    with pytest.raises(ValidationError):
        ConversationReferences.model_validate([{
            "type": "text",
            "reference": {
                "content": "内容",
                "displayPath": "docs/a.docx",
                "fileName": "a.docx",
                "filePath": "docs/a.docx",
                "id": "word-text-invalid",
                "location": {
                    "kind": "word_range",
                    "start": {"characterOffset": -1, "container": "body"},
                    "end": {"characterOffset": 1, "container": "body"},
                },
                "projectId": "project-a",
                "source": "office",
            },
        }])


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
