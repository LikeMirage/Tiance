from __future__ import annotations

from dataclasses import dataclass, replace
from json import dumps

from app.domain.llm.chat import ChatToolCall, ChatToolResult
from app.services.tools.tool_execution_arguments import parse_tool_arguments


INVALID_TOOL_ARGUMENTS = "INVALID_TOOL_ARGUMENTS"
INVALID_TOOL_ARGUMENTS_MESSAGE = (
    "本次工具指令参数不是合法 JSON，请检查并重新输出完整工具调用。"
)


@dataclass(frozen=True, slots=True)
class PreparedToolCallRound:
    replay_calls: tuple[ChatToolCall, ...]
    executable_calls: tuple[ChatToolCall, ...]
    invalid_results: tuple[tuple[ChatToolCall, ChatToolResult], ...]


def prepare_tool_calls_for_replay(
    tool_calls: tuple[ChatToolCall, ...],
) -> PreparedToolCallRound:
    replay_calls: list[ChatToolCall] = []
    executable_calls: list[ChatToolCall] = []
    invalid_results: list[tuple[ChatToolCall, ChatToolResult]] = []
    for tool_call in tool_calls:
        try:
            parse_tool_arguments(tool_call.arguments)
        except ValueError:
            replay_calls.append(replace(tool_call, arguments="{}"))
            invalid_results.append(
                (tool_call, _invalid_tool_arguments_result(tool_call))
            )
            continue
        replay_calls.append(tool_call)
        executable_calls.append(tool_call)
    return PreparedToolCallRound(
        replay_calls=tuple(replay_calls),
        executable_calls=tuple(executable_calls),
        invalid_results=tuple(invalid_results),
    )


def _invalid_tool_arguments_result(tool_call: ChatToolCall) -> ChatToolResult:
    return ChatToolResult(
        call_id=tool_call.call_id,
        name=tool_call.name,
        arguments=tool_call.arguments,
        ok=False,
        content=dumps(
            {
                "ok": False,
                "error_code": INVALID_TOOL_ARGUMENTS,
                "message": INVALID_TOOL_ARGUMENTS_MESSAGE,
                "received_arguments": tool_call.arguments,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        error=INVALID_TOOL_ARGUMENTS_MESSAGE,
    )
