import asyncio
from collections.abc import AsyncGenerator

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.llm import chat_socket


class _DirectStreamService:
    def validate_conversation_target(self, _request) -> None:
        return None

    async def stream_payloads(
        self,
        request,
        *,
        await_background_tasks: bool = False,
        include_persistence_checkpoints: bool = False,
    ) -> AsyncGenerator[dict[str, object | None], None]:
        del await_background_tasks, include_persistence_checkpoints
        yield {
            "kind": "delta",
            "content": request.messages[0].content,
        }
        yield {
            "kind": "done",
            "finish_reason": "stop",
        }


def test_chat_socket_multiplexes_independent_channels(monkeypatch) -> None:
    monkeypatch.setattr(
        chat_socket,
        "get_project_conversation_stream_service",
        lambda: _DirectStreamService(),
    )
    application = FastAPI()
    application.include_router(chat_socket.router)

    with TestClient(application).websocket_connect(
        "/llm/chat/completions/socket",
    ) as websocket:
        websocket.send_json(_start_command("channel-a", "A"))
        websocket.send_json(_start_command("channel-b", "B"))

        messages = [websocket.receive_json() for _ in range(8)]

    by_channel: dict[str, list[dict]] = {"channel-a": [], "channel-b": []}
    for message in messages:
        by_channel[message["channel_id"]].append(message)

    for channel_id, expected_content in (("channel-a", "A"), ("channel-b", "B")):
        channel_messages = by_channel[channel_id]
        assert [message["type"] for message in channel_messages] == [
            "opened",
            "event",
            "event",
            "complete",
        ]
        assert channel_messages[1]["event"]["content"] == expected_content
        assert channel_messages[2]["event"]["kind"] == "done"


def test_chat_socket_rejects_invalid_commands_without_closing_connection() -> None:
    application = FastAPI()
    application.include_router(chat_socket.router)

    with TestClient(application).websocket_connect(
        "/llm/chat/completions/socket",
    ) as websocket:
        websocket.send_json({
            "type": "start",
            "channel_id": "invalid",
            "request": {},
        })
        error = websocket.receive_json()

    assert error == {
        "type": "error",
        "channel_id": "invalid",
        "status": 400,
        "code": "bad_request",
        "error": "会话流通道命令参数无效。",
    }


def test_chat_socket_send_timeout_closes_stalled_connection(monkeypatch) -> None:
    class _StalledWebSocket:
        def __init__(self) -> None:
            self.closed = False

        async def send_json(self, _payload) -> None:
            await asyncio.Event().wait()

        async def close(self, *, code: int) -> None:
            assert code == 1011
            self.closed = True

    async def run_test() -> None:
        websocket = _StalledWebSocket()
        session = chat_socket._ChatSocketSession(websocket)
        monkeypatch.setattr(chat_socket, "_SOCKET_SEND_TIMEOUT_SECONDS", 0.01)

        with pytest.raises(chat_socket._ChatSocketSendTimeoutError):
            await session._send({"type": "complete", "channel_id": "slow"})
        assert websocket.closed is True

    asyncio.run(run_test())


def _start_command(channel_id: str, content: str) -> dict:
    return {
        "type": "start",
        "channel_id": channel_id,
        "request": {
            "provider_id": "provider-a",
            "model_id": "model-a",
            "messages": [
                {
                    "role": "user",
                    "content": content,
                    "message_id": f"message-{content.lower()}",
                }
            ],
        },
    }
