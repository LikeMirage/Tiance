from __future__ import annotations

import asyncio

from app.domain.llm.chat import ChatCompletionRequest
from app.infra.llm import chat_remote_client as remote_client_module
from app.infra.llm.chat_remote_client import ChatRemoteClient


class _Response:
    status_code = 200
    headers = {"content-type": "application/json", "set-cookie": "secret-cookie"}
    content = b'{"answer":"ok"}'

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {"answer": "ok"}


class _Client:
    async def post(self, _url, *, headers, json):
        assert headers["Authorization"] == "Bearer secret"
        assert json["api_key"] == "secret-body-key"
        return _Response()


def test_complete_exchange_callback_receives_full_body_with_credentials_redacted(
    monkeypatch,
) -> None:
    monkeypatch.setattr(remote_client_module, "get_shared_http_client", lambda: _Client())
    captured = []

    async def record(_request, exchange) -> None:
        captured.append(exchange)

    request = ChatCompletionRequest(provider_id="provider", model_id="model", messages=())

    async def execute() -> None:
        payload = await ChatRemoteClient()._post_json(
            "https://example.test/v1/chat?key=secret-query&trace=visible",
            {"Authorization": "Bearer secret", "X-Trace": "visible"},
            {"api_key": "secret-body-key", "model": "model"},
            request=request,
            on_exchange=record,
        )
        assert payload == {"answer": "ok"}

    asyncio.run(execute())

    assert len(captured) == 1
    exchange = captured[0]
    assert "secret-query" not in exchange.request_url
    assert exchange.request_headers["Authorization"] == "[REDACTED]"
    assert exchange.request_headers["X-Trace"] == "visible"
    assert exchange.request_body["api_key"] == "[REDACTED]"
    assert exchange.response_headers["set-cookie"] == "[REDACTED]"
    assert exchange.response_body == b'{"answer":"ok"}'
