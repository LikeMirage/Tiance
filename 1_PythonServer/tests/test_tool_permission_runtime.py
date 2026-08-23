import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from app.domain.llm.chat import (
    ChatClientCapability,
    ChatClientToolRequest,
    ChatCompletionRequest,
    ChatMessage,
    ChatMessageRole,
    ChatStreamEventKind,
    ChatToolCall,
    ChatToolResult,
)
from app.services.project.conversation_tool_loop import ConversationToolLoop
from app.services.project.conversation_run_manager import ConversationRunManager
from app.services.tools.tool_permission_bridge import ToolPermissionBridgeService
from app.services.tools.client_tool_bridge import ClientToolResultPayload
from app.services.tools.tool_execution import PreparedClientToolExecution
from app.services.tools.tool_permissions import (
    ToolPermissionEvaluation,
    ToolPermissionFact,
    evaluate_tool_permissions,
)


def test_permission_evaluation_uses_strictest_fact_and_skips_none(tmp_path: Path):
    tool_root = tmp_path / "tool"
    (tool_root / ".tool").mkdir(parents=True)
    (tool_root / ".tool" / "permissions.json").write_text(
        json.dumps(
            {
                "version": 1,
                "fallback": "ask",
                "policies": {
                    "filesystem_read": {
                        "workspace_inside": "allow",
                        "workspace_outside": "deny",
                        "unresolved": "ask",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    evaluation = evaluate_tool_permissions(
        tool_name="read_files",
        arguments={
            "inside": "README.md",
            "outside": str(tmp_path / "outside.txt"),
            "presentation": True,
        },
        input_schema={
            "type": "object",
            "properties": {
                "inside": {"type": "string", "permission_type": "filesystem_read"},
                "outside": {"type": "string", "permission_type": "filesystem_read"},
                "presentation": {"type": "boolean", "permission_type": "none"},
            },
        },
        tool_root=str(tool_root),
        workspace_root=str(workspace),
        project_id="project-1",
    )

    assert evaluation.decision == "deny"
    assert {(fact.parameter_name, fact.scope, fact.decision) for fact in evaluation.facts} == {
        ("inside", "workspace_inside", "allow"),
        ("outside", "workspace_outside", "deny"),
    }


def test_missing_parameter_permission_type_is_unknown_and_asks(tmp_path: Path):
    tool_root = tmp_path / "tool"
    tool_root.mkdir()

    evaluation = evaluate_tool_permissions(
        tool_name="custom_tool",
        arguments={"value": "anything"},
        input_schema={"type": "object", "properties": {"value": {"type": "string"}}},
        tool_root=str(tool_root),
        workspace_root=str(tmp_path),
        project_id="project-1",
    )

    assert evaluation.decision == "ask"
    assert evaluation.facts[0].permission_type == "unknown"
    assert evaluation.facts[0].scope == "all"


def test_permission_bridge_accepts_exactly_one_decision():
    async def scenario():
        bridge = ToolPermissionBridgeService()
        request = await bridge.create_request(
            displayed_call_id="call-1",
            displayed_tool_name="write_file",
            project_id="project-1",
            session_id="session-1",
            evaluation=_ask_evaluation("write_file"),
        )
        assert await bridge.should_replay_request(request.request_id)
        assert await bridge.submit_decision(request.request_id, "allow")
        assert not await bridge.submit_decision(request.request_id, "deny")
        assert await bridge.wait_for_decision(request.request_id) == "allow"
        assert not await bridge.should_replay_request(request.request_id)

    asyncio.run(scenario())


def test_conversation_waits_for_one_time_permission_before_execution():
    async def scenario():
        bridge = ToolPermissionBridgeService()
        execution = _AskingToolExecutionService()
        loop = ConversationToolLoop(
            chat_service=None,
            conversation_service=_ConversationService(),
            tool_execution_service=execution,
            tool_result_guidance_service=None,
            project_service=_ProjectService(),
            tool_call_record_service=None,
            client_tool_bridge_service=None,
            tool_permission_bridge_service=bridge,
        )
        call = ChatToolCall(call_id="call-1", name="write_file", arguments='{"path":"a.txt"}')
        events = loop._execute_tool_call_events(_request(), call)

        requested = await anext(events)
        assert requested.kind == ChatStreamEventKind.TOOL_PERMISSION_REQUEST
        assert not execution.executed

        permission_request = requested.tool_permission_request
        assert permission_request is not None
        assert await bridge.submit_decision(permission_request.request_id, "allow")

        resolved = await anext(events)
        assert resolved.kind == ChatStreamEventKind.TOOL_PERMISSION_RESOLVED
        result = await anext(events)
        assert result.kind == ChatStreamEventKind.TOOL_RESULT
        assert result.tool_result is not None and result.tool_result.ok
        assert execution.executed

    asyncio.run(scenario())


def test_one_time_rejection_returns_tool_failure_without_execution():
    async def scenario():
        bridge = ToolPermissionBridgeService()
        execution = _AskingToolExecutionService()
        loop = ConversationToolLoop(
            chat_service=None,
            conversation_service=_ConversationService(),
            tool_execution_service=execution,
            tool_result_guidance_service=None,
            project_service=_ProjectService(),
            tool_call_record_service=None,
            client_tool_bridge_service=None,
            tool_permission_bridge_service=bridge,
        )
        call = ChatToolCall(call_id="call-1", name="write_file", arguments='{"path":"a.txt"}')
        events = loop._execute_tool_call_events(_request(), call)

        requested = await anext(events)
        permission_request = requested.tool_permission_request
        assert permission_request is not None
        assert await bridge.submit_decision(permission_request.request_id, "deny")

        assert (await anext(events)).kind == ChatStreamEventKind.TOOL_PERMISSION_RESOLVED
        result = await anext(events)
        assert result.tool_result is not None
        assert not result.tool_result.ok
        assert "用户拒绝" in (result.tool_result.error or "")
        assert not execution.executed

    asyncio.run(scenario())


def test_client_tool_request_is_not_sent_before_permission_is_allowed():
    async def scenario():
        permission_bridge = ToolPermissionBridgeService()
        client_bridge = _ClientToolBridge()
        execution = _AskingClientToolExecutionService()
        loop = ConversationToolLoop(
            chat_service=None,
            conversation_service=_ConversationService(),
            tool_execution_service=execution,
            tool_result_guidance_service=None,
            project_service=_ProjectService(),
            tool_call_record_service=None,
            client_tool_bridge_service=client_bridge,
            tool_permission_bridge_service=permission_bridge,
        )
        call = ChatToolCall(call_id="call-1", name="open_editor", arguments='{"path":"a.txt"}')
        events = loop._execute_tool_call_events(_request(), call)

        requested = await anext(events)
        assert requested.kind == ChatStreamEventKind.TOOL_PERMISSION_REQUEST
        assert not client_bridge.created
        permission_request = requested.tool_permission_request
        assert permission_request is not None
        assert await permission_bridge.submit_decision(permission_request.request_id, "allow")

        assert (await anext(events)).kind == ChatStreamEventKind.TOOL_PERMISSION_RESOLVED
        assert (await anext(events)).kind == ChatStreamEventKind.CLIENT_TOOL_REQUEST
        assert client_bridge.created
        result = await anext(events)
        assert result.tool_result is not None and result.tool_result.ok

    asyncio.run(scenario())


def test_permission_gate_checks_every_invocation_node_without_tool_name_exceptions():
    async def scenario():
        bridge = ToolPermissionBridgeService()
        execution = _RecordingPermissionToolExecutionService()
        loop = ConversationToolLoop(
            chat_service=None,
            conversation_service=_ConversationService(),
            tool_execution_service=execution,
            tool_result_guidance_service=None,
            project_service=_ProjectService(),
            tool_call_record_service=None,
            client_tool_bridge_service=None,
            tool_permission_bridge_service=bridge,
        )
        wrapper = ChatToolCall(
            call_id="call-1",
            name="execute_dynamic_tool",
            arguments='{"tool_name":"write_file","arguments":{"path":"a.txt"}}',
        )
        target = ChatToolCall(
            call_id="call-1",
            name="write_file",
            arguments='{"path":"a.txt"}',
        )

        error, pending = await loop._prepare_permission_gate(
            _request(),
            displayed_call=wrapper,
            actual_calls=(wrapper, target),
            context=await loop._build_tool_execution_context(_request()),
        )

        assert error is None
        assert pending is not None
        assert execution.checked_names == ["execute_dynamic_tool", "write_file"]
        assert {fact["tool_name"] for fact in pending.facts} == {"write_file"}

    asyncio.run(scenario())


def test_pending_permission_is_replayed_and_cancelled_with_the_conversation_run():
    async def scenario():
        bridge = ToolPermissionBridgeService()
        permission_request = await bridge.create_request(
            displayed_call_id="call-1",
            displayed_tool_name="write_file",
            project_id="project-1",
            session_id="session-1",
            evaluation=_ask_evaluation("write_file"),
        )
        manager = ConversationRunManager(tool_permission_bridge_service=bridge)
        stream_service = _PermissionWaitingStreamService(
            bridge,
            permission_request.request_id,
        )
        subscription = await manager.start(_request(), stream_service)
        listener = manager.stream(subscription)

        first = await anext(listener)
        assert first["kind"] == "tool_permission_request"
        await listener.aclose()

        resumed = await manager.subscribe("project-1", "session-1")
        resumed_listener = manager.stream(resumed)
        assert await anext(resumed_listener) == first

        assert await manager.stop("project-1", "session-1")
        cancelled = await anext(resumed_listener)
        assert cancelled["kind"] == "tool_permission_request_cancelled"
        assert cancelled["request_id"] == permission_request.request_id

    asyncio.run(scenario())


def _ask_evaluation(tool_name: str) -> ToolPermissionEvaluation:
    return ToolPermissionEvaluation(
        decision="ask",
        facts=(
            ToolPermissionFact(
                tool_name=tool_name,
                parameter_name="path",
                permission_type="filesystem_write",
                scope="workspace_inside",
                decision="ask",
            ),
        ),
    )


class _AskingToolExecutionService:
    def __init__(self) -> None:
        self.executed = False

    def is_client_tool(self, _tool_name: str) -> bool:
        return False

    def evaluate_permissions(self, tool_call, *, context):
        return _ask_evaluation(tool_call.name)

    def execute(self, tool_call, *, context):
        self.executed = True
        return ChatToolResult(
            call_id=tool_call.call_id,
            name=tool_call.name,
            arguments=tool_call.arguments,
            ok=True,
            content='{"ok":true}',
        )


class _RecordingPermissionToolExecutionService(_AskingToolExecutionService):
    def __init__(self) -> None:
        super().__init__()
        self.checked_names: list[str] = []

    def evaluate_permissions(self, tool_call, *, context):
        self.checked_names.append(tool_call.name)
        if tool_call.name == "execute_dynamic_tool":
            return ToolPermissionEvaluation(decision="allow", facts=())
        return _ask_evaluation(tool_call.name)


class _AskingClientToolExecutionService(_AskingToolExecutionService):
    def is_client_tool(self, _tool_name: str) -> bool:
        return True

    def prepare_client_tool(self, _tool_call):
        return PreparedClientToolExecution(
            tool_project_id="client-tool",
            dynamic=False,
            timeout_seconds=30,
            capability=ChatClientCapability(name="test.client", version=1),
        )


class _ClientToolBridge:
    def __init__(self) -> None:
        self.created = False

    async def create_request(self, tool_call, **kwargs):
        self.created = True
        return ChatClientToolRequest(
            request_id="client-request-1",
            call_id=tool_call.call_id,
            name=tool_call.name,
            arguments=tool_call.arguments,
        )

    async def wait_for_result(self, _request_id: str, *, timeout_seconds: int):
        return ClientToolResultPayload(ok=True, content={"ok": True})


class _ConversationService:
    def get_session(self, _project_id: str, _session_id: str):
        return SimpleNamespace(
            settings=SimpleNamespace(tools_enabled=True, enabled_tool_names=None)
        )


class _ProjectService:
    def get_project(self, _project_id: str):
        return SimpleNamespace(root_path="C:/work")


class _PermissionWaitingStreamService:
    def __init__(self, bridge: ToolPermissionBridgeService, request_id: str) -> None:
        self._bridge = bridge
        self._request_id = request_id

    async def stream_payloads(self, request, **_kwargs):
        yield {
            "kind": "tool_permission_request",
            "tool_permission_request": {
                "request_id": self._request_id,
                "call_id": "call-1",
                "name": "write_file",
            },
        }
        await self._bridge.wait_for_decision(self._request_id)


def _request() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        provider_id="provider",
        model_id="model",
        project_id="project-1",
        session_id="session-1",
        messages=(ChatMessage(role=ChatMessageRole.USER, content="run"),),
    )
