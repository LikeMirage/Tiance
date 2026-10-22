import asyncio
from copy import deepcopy

import pytest

from app.domain.llm.chat import ChatMessage, ChatMessageRole, ChatStreamEvent, ChatStreamEventKind, ChatToolResult
from app.infra.llm.chat_adapters.gemini import _build_gemini_body
from app.services.project.conversation_tool_loop import ConversationToolLoop
from app.services.tools.tool_permission_bridge import ToolPermissionBridgeService
from tests.test_chat_stream_cancellation import _FakeToolExecutionService
from tests.test_llm_protocol_continuation import _collect_gemini, _request


def _part(call_id=None, *, name="check_status", args=None):
    call = {"name": name, "args": args or {}}
    if call_id is not None:
        call["id"] = call_id
    return {"functionCall": call}


def _events(chunks):
    payloads = [{"candidates": [{"content": {"parts": parts}}]} for parts in chunks]
    payloads[-1]["candidates"][0]["finishReason"] = "STOP"
    return asyncio.run(_collect_gemini(payloads, _request("gemini", "model")))


@pytest.mark.parametrize("separate_chunks", [False, True])
@pytest.mark.parametrize("with_ids", [False, True])
def test_identical_arguments_do_not_merge_distinct_calls(separate_chunks, with_ids):
    parts = [_part("first" if with_ids else None), _part("second" if with_ids else None)]
    events = _events([[part] for part in parts] if separate_chunks else [parts])
    calls = [event.tool_call for event in events if event.kind == ChatStreamEventKind.TOOL_CALL]
    assert len(calls) == 2
    assert calls[0].call_id != calls[1].call_id
    assert [(call.name, call.arguments) for call in calls] == [("check_status", "{}")]*2
    continuation = next(event.protocol_continuation for event in events if event.kind == ChatStreamEventKind.PROTOCOL_CONTINUATION)
    assert list(continuation.items) == parts
    assistant = ChatMessage(role=ChatMessageRole.ASSISTANT, content="", tool_calls=tuple(calls), protocol_continuation=continuation)
    responses = tuple(ChatMessage(role=ChatMessageRole.TOOL, content="ok", name=call.name, tool_call_id=call.call_id) for call in calls)
    replay = _build_gemini_body(_request("gemini", "model", messages=(assistant, *responses)))
    assert replay["contents"][0]["parts"] == parts
    assert [item["parts"][0]["functionResponse"]["id"] for item in replay["contents"][1:]] == [call.call_id for call in calls]


def test_repeated_complete_call_id_executes_once_and_preserves_late_signature():
    first = _part("same")
    repeated = {**deepcopy(first), "thoughtSignature": "signature"}
    events = _events([[{"thought": True, "text": "plan"}, first], [repeated]])
    calls = [event.tool_call for event in events if event.kind == ChatStreamEventKind.TOOL_CALL]
    assert len(calls) == 1 and calls[0].call_id == "same"
    continuation = next(event.protocol_continuation for event in events if event.kind == ChatStreamEventKind.PROTOCOL_CONTINUATION)
    assert list(continuation.items) == [{"thought": True, "text": "plan"}, repeated]
    assert events[-1].kind == ChatStreamEventKind.DONE


@pytest.mark.parametrize("second", [_part("same", name="other"), _part("same", args={"different": True})])
def test_reused_id_with_conflicting_call_is_rejected_before_tools_run(second):
    events = _events([[_part("same")], [second]])
    assert events[-1].kind == ChatStreamEventKind.ERROR
    assert not any(event.kind == ChatStreamEventKind.DONE for event in events)


def test_missing_id_sequence_does_not_reset_across_chunks_or_responses():
    events = _events([[_part()], [{"text": "checking"}], [_part(name="other")]])
    ids = [e.tool_call.call_id for e in events if e.kind == ChatStreamEventKind.TOOL_CALL]
    new_ids = [e.tool_call.call_id for e in _events([[_part()]]) if e.kind == ChatStreamEventKind.TOOL_CALL]
    assert len(ids) == len(set(ids)) == 2
    assert not set(ids).intersection(new_ids)


@pytest.mark.parametrize("parts,expected_runs", [
    ([_part("first"), _part("second")], 2),
    ([_part("same"), _part("same")], 1),
    ([_part(), _part()], 2),
    ([_part("same"), _part("same", name="other")], 0),
])
def test_tool_loop_executes_each_distinct_call_and_replays_its_result(parts, expected_runs):
    model_events = _events([[part] for part in parts])
    executed = []
    requests = []

    class Chat:
        async def stream(self, request):
            requests.append(request)
            for event in (model_events if len(requests) == 1 else [ChatStreamEvent(kind=ChatStreamEventKind.DONE)]):
                yield event

    class Execution(_FakeToolExecutionService):
        def execute(self, call, *, context):
            executed.append(call)
            return ChatToolResult(call_id=call.call_id, name=call.name, arguments=call.arguments, ok=True, content="ok")

    async def run():
        loop = ConversationToolLoop(
            chat_service=Chat(), conversation_service=None, tool_execution_service=Execution(),
            tool_result_guidance_service=None, project_service=None, tool_call_record_service=None,
            client_tool_bridge_service=None, tool_permission_bridge_service=ToolPermissionBridgeService(),
        )
        request = _request("gemini", "model")
        return [event async for event in loop.stream_events(request, request)]

    asyncio.run(run())
    assert len(executed) == expected_runs
    assert len({call.call_id for call in executed}) == expected_runs
    if expected_runs:
        tool_results = [message for message in requests[-1].messages if message.role == ChatMessageRole.TOOL]
        assert [message.tool_call_id for message in tool_results] == [call.call_id for call in executed]
    else:
        assert len(requests) == 1
