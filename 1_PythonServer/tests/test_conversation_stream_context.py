from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatImageRef,
    ChatMessage,
    ChatMessageContentPart,
    ChatMessageContentPartType,
    ChatMessageRole,
)
from app.domain.project.project_conversation import (
    ProjectConversationMessage,
    ProjectConversationSession,
    ProjectConversationSessionSettings,
)
from app.services.project.conversation_stream_context import ConversationStreamContextBuilder
from app.services.project.conversation_request_provenance import conversation_message_id


def test_rebuild_session_request_messages_uses_full_persisted_history():
    image_part = ChatMessageContentPart(
        type=ChatMessageContentPartType.IMAGE_REF,
        image_ref=ChatImageRef(path="images/current.png", mime_type="image/png"),
    )
    history = tuple(
        _message(f"u-{index}", "user", f"历史 {index}")
        for index in range(1, 106)
    )
    persisted_current = _message(
        "u-current",
        "user",
        "当前",
        content_parts=(image_part,),
    )
    builder = ConversationStreamContextBuilder(
        conversation_service=_FakeConversationService(
            messages=(*history, persisted_current),
            session=ProjectConversationSession(
                session_id="session-1",
                sequence_number=1,
                title="测试会话",
                provider_id="provider",
                model_id="model",
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
                message_count=106,
                settings=ProjectConversationSessionSettings(),
            ),
        ),
        memory_service=object(),
        tool_injection_service=None,
    )

    request = ChatCompletionRequest(
        provider_id="provider",
        model_id="model",
        project_id="project-1",
        session_id="session-1",
        messages=(
            ChatMessage(
                role=ChatMessageRole.USER,
                content="当前",
                content_parts=(image_part,),
            ),
        ),
    )

    rebuilt = builder.rebuild_session_request_messages(
        request,
        drop_matching_last_user=True,
    )

    assert len(rebuilt.messages) == 106
    assert rebuilt.messages[0].content == "历史 1"
    assert rebuilt.messages[104].content == "历史 105"
    assert rebuilt.messages[-1].content == "当前"
    assert rebuilt.messages[-1].content_parts == (image_part,)
    assert rebuilt.messages[-1].created_at == "2026-01-01T00:00:00+00:00"
    assert [conversation_message_id(message) for message in rebuilt.messages] == [
        *(f"u-{index}" for index in range(1, 106)),
        "u-current",
    ]
    assert rebuilt.cache_affinity_id == "lineage-session-1"
    assert rebuilt.inject_message_timestamps is True


def test_rebuild_session_request_messages_keeps_history_for_preview_draft():
    builder = ConversationStreamContextBuilder(
        conversation_service=_FakeConversationService(
            messages=(_message("u-1", "user", "重复内容"),),
            session=ProjectConversationSession(
                session_id="session-1",
                sequence_number=1,
                title="测试会话",
                provider_id="provider",
                model_id="model",
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
                message_count=1,
                settings=ProjectConversationSessionSettings(),
            ),
        ),
        memory_service=object(),
        tool_injection_service=None,
    )

    request = ChatCompletionRequest(
        provider_id="provider",
        model_id="model",
        project_id="project-1",
        session_id="session-1",
        messages=(ChatMessage(role=ChatMessageRole.USER, content="重复内容"),),
    )

    rebuilt = builder.rebuild_session_request_messages(request)

    assert [message.content for message in rebuilt.messages] == [
        "重复内容",
        "重复内容",
    ]


class _FakeConversationService:
    def __init__(
        self,
        *,
        messages: tuple[ProjectConversationMessage, ...],
        session: ProjectConversationSession,
    ) -> None:
        self._messages = messages
        self._session = session

    def get_session(self, project_id: str, session_id: str) -> ProjectConversationSession | None:
        return self._session

    def list_messages(self, project_id: str, session_id: str) -> tuple[ProjectConversationMessage, ...]:
        return self._messages

    def get_cache_affinity_id(self, project_id: str, session_id: str) -> str:
        return f"lineage-{session_id}"


def _message(
    message_id: str,
    role: str,
    content: str,
    *,
    content_parts: tuple[ChatMessageContentPart, ...] = (),
) -> ProjectConversationMessage:
    return ProjectConversationMessage(
        message_id=message_id,
        session_id="session-1",
        role=role,
        content=content,
        thinking_content="",
        usage=None,
        provider_id=None,
        model_id=None,
        status="done",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        content_parts=content_parts,
    )
