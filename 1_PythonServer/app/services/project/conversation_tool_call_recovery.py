from __future__ import annotations

from dataclasses import dataclass, replace
from json import JSONDecodeError, dumps

from app.domain.llm.chat import ChatToolCall, ChatToolResult
from app.services.tools.tool_execution_arguments import parse_tool_arguments


INVALID_TOOL_ARGUMENTS = "INVALID_TOOL_ARGUMENTS"
INVALID_TOOL_ARGUMENTS_MESSAGE = (
    "工具参数未通过 JSON 对象校验，工具尚未执行。"
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
        except ValueError as error:
            replay_calls.append(replace(tool_call, arguments="{}"))
            invalid_results.append(
                (tool_call, _invalid_tool_arguments_result(tool_call, error))
            )
            continue
        replay_calls.append(tool_call)
        executable_calls.append(tool_call)
    return PreparedToolCallRound(
        replay_calls=tuple(replay_calls),
        executable_calls=tuple(executable_calls),
        invalid_results=tuple(invalid_results),
    )


def _invalid_tool_arguments_result(
    tool_call: ChatToolCall,
    error: ValueError,
) -> ChatToolResult:
    diagnostic: dict[str, object] = {"detail": str(error)}
    cause = error.__cause__
    if isinstance(cause, JSONDecodeError):
        start = max(0, cause.pos - 80)
        end = min(len(cause.doc), cause.pos + 80)
        diagnostic.update(
            line=cause.lineno,
            column=cause.colno,
            position=cause.pos,
            at_end=cause.pos == len(cause.doc),
            excerpt=cause.doc[start:end],
            excerpt_start=start,
        )
    message = f"{INVALID_TOOL_ARGUMENTS_MESSAGE}{error}"
    return ChatToolResult(
        call_id=tool_call.call_id,
        name=tool_call.name,
        arguments=tool_call.arguments,
        ok=False,
        content=dumps(
            {
                "ok": False,
                "error_code": INVALID_TOOL_ARGUMENTS,
                "message": message,
                "executed": False,
                "diagnostic": diagnostic,
                "received_arguments": tool_call.arguments,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        error=message,
    )
