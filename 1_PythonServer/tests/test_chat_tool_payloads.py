from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatImageUrl,
    ChatMessage,
    ChatMessageContentPart,
    ChatMessageContentPartType,
    ChatMessageRole,
    ChatToolCall,
    ChatToolDefinition,
)
from app.domain.llm.reasoning_replay import ReasoningReplayMode
from app.domain.llm.generation_params import (
    LlmGenerationParams,
    LlmReasoningMode,
    LlmReasoningOptions,
)
from app.infra.llm.chat_adapters.anthropic import _build_anthropic_body
from app.infra.llm.chat_adapters.gemini import _build_gemini_body
from app.infra.llm.chat_adapters.openai_compatible import _build_request_body, _parse_response
from app.infra.llm.chat_adapters.openai_responses import _build_responses_body
from app.infra.llm.chat_adapters.payloads import _message_to_openai_payload
from app.infra.llm.provider_profiles.base import GenericOpenAICompatibleProfile
from app.infra.llm.provider_profiles.deepseek import DeepSeekProfile
from app.infra.llm.provider_profiles.volcengine import VolcengineProfile
from app.schemas.llm.chat import ChatCompletionRequestBody


def test_chat_request_rejects_unknown_protocol_fields():
    with pytest.raises(ValidationError):
        ChatCompletionRequestBody.model_validate(
            {
                "provider_id": "openai",
                "model_id": "gpt-test",
                "messages": [],
                "provider_private_tools": [],
            }
        )


def test_openai_responses_body_includes_tool_definitions():
    body = _build_responses_body(_request(), stream=False)

    assert body["tools"] == [
        {
            "type": "function",
            "name": "read_text_file",
            "description": "读取本地纯文本文件。",
            "parameters": _input_schema(),
        }
    ]


def test_internal_message_metadata_is_not_sent_to_openai_apis():
    message = ChatMessage(
        role=ChatMessageRole.USER,
        content="测试",
        internal_metadata={"conversation_message_id": "msg-1"},
    )

    compatible_payload = _message_to_openai_payload(message)
    responses_body = _build_responses_body(
        ChatCompletionRequest(
            provider_id="openai",
            model_id="gpt-test",
            messages=(message,),
        ),
        stream=False,
    )

    assert compatible_payload == {"role": "user", "content": "测试"}
    assert responses_body["input"] == [
        {"role": "user", "content": "测试"},
    ]


def test_message_timestamp_is_serialized_consistently_for_all_protocols():
    message = ChatMessage(
        role=ChatMessageRole.USER,
        content="测试",
        created_at="2026-07-30T16:28:35+08:00",
    )
    request = ChatCompletionRequest(
        provider_id="test",
        model_id="test",
        messages=(message,),
        inject_message_timestamps=True,
    )
    expected = (
        "<message_time>2026-07-30T16:28:35+08:00</message_time>\n测试"
    )

    assert _message_to_openai_payload(message)["content"] == expected
    assert _build_responses_body(request, stream=False)["input"] == [
        {"role": "user", "content": expected},
    ]
    assert _build_anthropic_body(request, stream=False)["messages"] == [
        {"role": "user", "content": expected},
    ]
    assert _build_gemini_body(request)["contents"] == [
        {"role": "user", "parts": [{"text": expected}]},
    ]


def test_non_user_message_timestamps_are_not_serialized():
    assistant_message = ChatMessage(
        role=ChatMessageRole.ASSISTANT,
        content="",
        created_at="2026-07-30T16:30:00+08:00",
        tool_calls=(
            ChatToolCall(
                call_id="call-1",
                name="read_text_file",
                arguments="{}",
            ),
        ),
    )
    tool_message = ChatMessage(
        role=ChatMessageRole.TOOL,
        content="完成",
        tool_call_id="call-1",
        created_at="2026-07-30T16:30:01+08:00",
    )

    assistant_payload = _message_to_openai_payload(assistant_message)
    tool_payload = _message_to_openai_payload(tool_message)

    assert assistant_payload["content"] is None
    assert assistant_payload["tool_calls"][0]["id"] == "call-1"
    assert tool_payload["content"] == "完成"


def test_anthropic_body_includes_tool_definitions():
    body = _build_anthropic_body(_request(), stream=False)

    assert body["tools"] == [
        {
            "name": "read_text_file",
            "description": "读取本地纯文本文件。",
            "input_schema": _input_schema(),
        }
    ]


def test_gemini_body_includes_tool_definitions():
    body = _build_gemini_body(_request())

    assert body["tools"] == [
        {
            "functionDeclarations": [
                {
                    "name": "read_text_file",
                    "description": "读取本地纯文本文件。",
                    "parameters": _input_schema(),
                }
            ],
        }
    ]


def test_openai_responses_body_formats_tool_call_history():
    body = _build_responses_body(_request_with_tool_history(), stream=False)

    assert body["input"][-2:] == [
        {
            "type": "function_call",
            "call_id": "call-1",
            "name": "read_text_file",
            "arguments": '{"file_path":"C:/work/app.py"}',
        },
        {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": '{"ok":true}',
        },
    ]


def test_openai_chat_payload_formats_tool_call_history_with_null_content():
    request = _request_with_tool_history()

    payload = _message_to_openai_payload(request.messages[-2])

    assert payload == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "read_text_file",
                    "arguments": '{"file_path":"C:/work/app.py"}',
                },
            }
        ],
    }


def test_openai_chat_payload_includes_reasoning_for_tool_call_rounds():
    message = ChatMessage(
        role=ChatMessageRole.ASSISTANT,
        content="",
        thinking_content="需要先查看工作区。",
        tool_calls=(
            ChatToolCall(
                call_id="call-1",
                name="inspect_workspace",
                arguments="{}",
            ),
        ),
    )

    payload = _message_to_openai_payload(
        message,
        reasoning_replay_mode=ReasoningReplayMode.TOOL_CALL_ROUNDS,
    )

    assert payload["content"] is None
    assert payload["reasoning_content"] == "需要先查看工作区。"


def test_openai_chat_payload_includes_empty_reasoning_for_tool_call_rounds():
    request = _request_with_tool_history()

    payload = _message_to_openai_payload(
        request.messages[-2],
        reasoning_replay_mode=ReasoningReplayMode.TOOL_CALL_ROUNDS,
    )

    assert payload["content"] is None
    assert payload["reasoning_content"] == ""


def test_openai_chat_payload_formats_image_parts_by_protocol():
    payload = _message_to_openai_payload(_vision_message())

    assert payload == {
        "role": "user",
        "content": [
            {"type": "text", "text": "请看图"},
            {
                "type": "image_url",
                "image_url": {
                    "url": _IMAGE_DATA_URL,
                    "detail": "high",
                },
            },
        ],
    }


def test_openai_responses_body_formats_image_parts_by_protocol():
    body = _build_responses_body(_vision_request(), stream=False)

    assert body["input"][0] == {
        "role": "user",
        "content": [
            {"type": "input_text", "text": "请看图"},
            {
                "type": "input_image",
                "image_url": _IMAGE_DATA_URL,
                "detail": "high",
            },
        ],
    }


def test_anthropic_body_formats_image_parts_by_protocol():
    body = _build_anthropic_body(_vision_request(), stream=False)

    assert body["messages"][0] == {
        "role": "user",
        "content": [
            {"type": "text", "text": "请看图"},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": "aW1hZ2U=",
                },
            },
        ],
    }


def test_gemini_body_formats_image_parts_by_protocol():
    body = _build_gemini_body(_vision_request())

    assert body["contents"][0] == {
        "role": "user",
        "parts": [
            {"text": "请看图"},
            {
                "inlineData": {
                    "mimeType": "image/png",
                    "data": "aW1hZ2U=",
                },
            },
        ],
    }


def test_openai_chat_payload_tool_call_mode_omits_non_tool_reasoning():
    message = ChatMessage(
        role=ChatMessageRole.ASSISTANT,
        content="普通回复",
        thinking_content="普通思考不回传。",
    )

    payload = _message_to_openai_payload(
        message,
        reasoning_replay_mode=ReasoningReplayMode.TOOL_CALL_ROUNDS,
    )

    assert payload["content"] == "普通回复"
    assert "reasoning_content" not in payload


def test_openai_chat_payload_always_mode_includes_non_tool_reasoning():
    message = ChatMessage(
        role=ChatMessageRole.ASSISTANT,
        content="普通回复",
        thinking_content="普通思考也回传。",
    )

    payload = _message_to_openai_payload(
        message,
        reasoning_replay_mode=ReasoningReplayMode.ALWAYS,
    )

    assert payload["content"] == "普通回复"
    assert payload["reasoning_content"] == "普通思考也回传。"


def test_openai_compatible_body_respects_provider_reasoning_replay_mode():
    request = _request_with_tool_history()

    disabled_body = _build_request_body(
        replace(request, reasoning_replay_mode=ReasoningReplayMode.NEVER),
        stream=False,
        provider_profile=DeepSeekProfile(),
    )
    enabled_body = _build_request_body(
        replace(request, reasoning_replay_mode=ReasoningReplayMode.TOOL_CALL_ROUNDS),
        stream=False,
        provider_profile=DeepSeekProfile(),
    )

    assert "reasoning_content" not in disabled_body["messages"][-2]
    assert enabled_body["messages"][-2]["reasoning_content"] == ""


def test_openai_compatible_body_replay_mode_is_not_provider_specific():
    body = _build_request_body(
        replace(
            _request_with_tool_history(),
            reasoning_replay_mode=ReasoningReplayMode.TOOL_CALL_ROUNDS,
        ),
        stream=False,
        provider_profile=VolcengineProfile(),
    )

    assert body["messages"][-2]["reasoning_content"] == ""


def test_volcengine_profile_keeps_auto_mode_for_declared_rules_to_validate():
    request = replace(
        _request(),
        model_id="doubao-seed-2-0-pro-260215",
        generation=LlmGenerationParams(
            reasoning=LlmReasoningOptions(mode=LlmReasoningMode.AUTO),
        ),
    )

    body = _build_request_body(
        request,
        stream=False,
        provider_profile=VolcengineProfile(),
    )

    assert body["thinking"] == {"type": "auto"}


def test_volcengine_seed_2_pro_sends_supported_enabled_mode():
    request = replace(
        _request(),
        model_id="doubao-seed-2-0-pro-260215",
        generation=LlmGenerationParams(
            reasoning=LlmReasoningOptions(mode=LlmReasoningMode.ENABLED),
        ),
    )

    body = _build_request_body(
        request,
        stream=False,
        provider_profile=VolcengineProfile(),
    )

    assert body["thinking"] == {"type": "enabled"}


def test_openai_compatible_body_does_not_infer_replay_mode_from_model_name():
    body = _build_request_body(
        replace(
            _request_with_tool_history(),
            model_id="deepseek-v4-flash",
            reasoning_replay_mode=ReasoningReplayMode.NEVER,
        ),
        stream=False,
        provider_profile=GenericOpenAICompatibleProfile(),
    )

    assert "reasoning_content" not in body["messages"][-2]


def test_openai_compatible_body_replay_mode_is_independent_of_reasoning_generation():
    body = _build_request_body(
        replace(
            _request_with_tool_history(),
            reasoning_replay_mode=ReasoningReplayMode.NEVER,
            generation=LlmGenerationParams(
                reasoning=LlmReasoningOptions(mode=LlmReasoningMode.HIGH),
            ),
        ),
        stream=False,
        provider_profile=DeepSeekProfile(),
    )

    assert "reasoning_content" not in body["messages"][-2]


def test_anthropic_body_formats_tool_call_history():
    body = _build_anthropic_body(_request_with_tool_history(), stream=False)

    assert body["messages"][-2:] == [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "call-1",
                    "name": "read_text_file",
                    "input": {"file_path": "C:/work/app.py"},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call-1",
                    "content": '{"ok":true}',
                }
            ],
        },
    ]


def test_openai_compatible_parse_response_returns_tool_calls():
    result = _parse_response(
        _request(),
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "reasoning_content": "需要读取文件。",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "read_text_file",
                                    "arguments": '{"file_path":"C:/work/app.py"}',
                                },
                            }
                        ],
                    },
                }
            ]
        },
        GenericOpenAICompatibleProfile(),
    )

    assert result.finish_reason == "tool_calls"
    assert result.thinking_content == "需要读取文件。"
    assert result.message.thinking_content == "需要读取文件。"
    assert result.message.tool_calls == (
        ChatToolCall(
            call_id="call-1",
            name="read_text_file",
            arguments='{"file_path":"C:/work/app.py"}',
        ),
    )


def test_gemini_body_formats_tool_call_history():
    body = _build_gemini_body(_request_with_tool_history())

    assert body["contents"][-2:] == [
        {
            "role": "model",
            "parts": [
                {
                    "functionCall": {
                        "name": "read_text_file",
                        "args": {"file_path": "C:/work/app.py"},
                    },
                }
            ],
        },
        {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "id": "call-1",
                        "name": "read_text_file",
                        "response": {"result": '{"ok":true}'},
                    },
                }
            ],
        },
    ]


def _request() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        provider_id="provider",
        model_id="model",
        messages=(ChatMessage(role=ChatMessageRole.USER, content="hi"),),
        tools=(
            ChatToolDefinition(
                name="read_text_file",
                description="读取本地纯文本文件。",
                parameters=_input_schema(),
            ),
        ),
    )


def _request_with_tool_history() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        provider_id="provider",
        model_id="model",
        messages=(
            ChatMessage(role=ChatMessageRole.USER, content="read file"),
            ChatMessage(
                role=ChatMessageRole.ASSISTANT,
                content="",
                tool_calls=(
                    ChatToolCall(
                        call_id="call-1",
                        name="read_text_file",
                        arguments='{"file_path":"C:/work/app.py"}',
                    ),
                ),
            ),
            ChatMessage(
                role=ChatMessageRole.TOOL,
                content='{"ok":true}',
                name="read_text_file",
                tool_call_id="call-1",
            ),
        ),
        tools=(
            ChatToolDefinition(
                name="read_text_file",
                description="读取本地纯文本文件。",
                parameters=_input_schema(),
            ),
        ),
    )


_IMAGE_DATA_URL = "data:image/png;base64,aW1hZ2U="


def _vision_message() -> ChatMessage:
    return ChatMessage(
        role=ChatMessageRole.USER,
        content="请看图",
        content_parts=(
            ChatMessageContentPart(
                type=ChatMessageContentPartType.IMAGE_URL,
                image_url=ChatImageUrl(url=_IMAGE_DATA_URL, detail="high"),
            ),
        ),
    )


def _vision_request() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        provider_id="provider",
        model_id="vision-model",
        messages=(_vision_message(),),
    )


def _input_schema() -> dict[str, object]:
    return {
        "type": "object",
        "required": ["file_path"],
        "properties": {
            "file_path": {
                "type": "string",
                "description": "文件路径。",
            },
        },
        "additionalProperties": False,
    }
