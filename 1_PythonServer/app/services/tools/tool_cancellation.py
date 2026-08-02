from __future__ import annotations

from enum import StrEnum
from json import dumps

from app.domain.llm.chat import ChatToolCall, ChatToolResult


class ToolCancellationScope(StrEnum):
    CALL = "call"
    EXECUTION = "execution"
    WAIT = "wait"


def cancelled_tool_result(
    tool_call: ChatToolCall,
    *,
    scope: ToolCancellationScope,
) -> ChatToolResult:
    if scope == ToolCancellationScope.WAIT:
        reason = "会话已暂停，已停止等待工具结果；被等待的任务未被取消。"
    elif scope == ToolCancellationScope.EXECUTION:
        reason = "会话已暂停，工具执行已取消。"
    else:
        reason = "会话已暂停，本次工具调用已取消。"
    return ChatToolResult(
        call_id=tool_call.call_id,
        name=tool_call.name,
        arguments=tool_call.arguments,
        ok=False,
        content=dumps(
            {
                "ok": False,
                "outcome": "cancelled",
                "cancel_scope": scope.value,
                "reason": reason,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        error=reason,
    )
