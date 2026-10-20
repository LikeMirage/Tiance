import json

import pytest

from app.domain.llm.chat import ChatToolCall
from app.services.project.conversation_tool_call_recovery import prepare_tool_calls_for_replay


@pytest.mark.parametrize(
    ("arguments", "at_end"),
    [
        ('{"result":{"items":[{"content":"摘要","keywords":[]}]}', True),
        ('{"result":{"items":[{"content":"摘要","keywords":[]}],"handoff":"交接"}]}}', False),
        ('{\n  "value":\n}', False),
    ],
)
def test_invalid_json_reports_exact_position_without_guessing_a_repair(arguments, at_end):
    call = ChatToolCall(call_id="invalid", name="example_tool", arguments=arguments)
    with pytest.raises(json.JSONDecodeError) as failure:
        json.loads(arguments)

    prepared = prepare_tool_calls_for_replay((call,))

    assert prepared.executable_calls == ()
    assert prepared.replay_calls[0].arguments == "{}"
    result = prepared.invalid_results[0][1]
    assert result.arguments == arguments
    payload = json.loads(result.content)
    assert payload["executed"] is False
    assert payload["received_arguments"] == arguments
    diagnostic = payload["diagnostic"]
    error = failure.value
    assert (diagnostic["line"], diagnostic["column"], diagnostic["position"]) == (
        error.lineno, error.colno, error.pos,
    )
    assert diagnostic["at_end"] is at_end
    assert diagnostic["excerpt"] == arguments[
        diagnostic["excerpt_start"]:diagnostic["excerpt_start"] + len(diagnostic["excerpt"])
    ]
    assert len(diagnostic["excerpt"]) <= 160


def test_non_object_json_reports_shape_error_without_fabricating_a_syntax_error():
    prepared = prepare_tool_calls_for_replay((
        ChatToolCall(call_id="array", name="example_tool", arguments="[]"),
    ))
    payload = json.loads(prepared.invalid_results[0][1].content)
    assert payload["diagnostic"] == {"detail": "工具参数必须是 JSON 对象。"}
    assert payload["executed"] is False


def test_valid_long_arguments_keep_all_content_and_are_executable():
    content = '路径 C:\\work\\sample.dwg\n"原文"及括号 }] 必须保留。' * 500
    arguments = json.dumps({"result": {
        "items": [{"content": content, "keywords": ["图纸"]}],
        "handoff": "最近用户请求：继续核验。",
    }}, ensure_ascii=False)
    call = ChatToolCall(call_id="valid", name="example_tool", arguments=arguments)

    prepared = prepare_tool_calls_for_replay((call,))

    assert prepared.invalid_results == ()
    assert prepared.executable_calls == (call,)
    assert prepared.replay_calls == (call,)
