from app.services.project.conversation_message_source import (
    add_source_context_to_model_content,
    normalize_source_context,
)


def test_source_context_is_injected_without_mutating_user_content():
    user_content = "请分析这份文档。"
    context = {
        "project_id": "project-1",
        "session_id": "session-2",
        "session_title": '子会话 <A> & "B"',
        "tool_request_id": "request-3",
    }

    model_content = add_source_context_to_model_content(user_content, context)

    assert user_content == "请分析这份文档。"
    assert model_content.endswith("\n\n请分析这份文档。")
    assert 'project_id="project-1"' in model_content
    assert 'session_id="session-2"' in model_content
    assert 'session_title="子会话 &lt;A&gt; &amp; &quot;B&quot;"' in model_content
    assert 'tool_request_id="request-3"' in model_content


def test_incomplete_source_context_is_not_partially_injected():
    incomplete = {
        "project_id": "project-1",
        "session_id": "session-2",
    }

    assert normalize_source_context(incomplete) == {}
    assert add_source_context_to_model_content("原文", incomplete) == "原文"
