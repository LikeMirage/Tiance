from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.domain.llm.chat import ChatCompletionRequest
from app.domain.llm.response_body import ResponseBody, body_chunks


@dataclass(frozen=True, slots=True)
class ChatHttpExchange:
    started_at: str
    completed_at: str
    request_url: str
    request_headers: dict[str, str]
    request_body: dict[str, object]
    response_status: int | None
    response_headers: dict[str, str]
    response_body: bytes | ResponseBody
    error_type: str | None = None
    error_message: str | None = None


class ChatHttpExchangeRecorder(Protocol):
    async def record_http_exchange(
        self,
        request: ChatCompletionRequest,
        exchange: ChatHttpExchange,
    ) -> None:
        ...

    def record_attempt_outcome(
        self,
        request: ChatCompletionRequest,
        *,
        status: str,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        ...


def exchange_to_payload(exchange: ChatHttpExchange) -> dict[str, Any]:
    # Explicit materialization for readers only. Persistence uses the streaming
    # payload below so a disk-backed body never needs to become one bytes object.
    content = b"".join(body_chunks(exchange.response_body))
    try:
        response_body: dict[str, str] = {
            "encoding": "utf-8",
            "content": content.decode("utf-8"),
        }
    except UnicodeDecodeError:
        from base64 import b64encode

        response_body = {
            "encoding": "base64",
            "content": b64encode(content).decode("ascii"),
        }
    return exchange_payload(exchange, response_body)


def exchange_payload(exchange: ChatHttpExchange, response_body: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "started_at": exchange.started_at,
        "completed_at": exchange.completed_at,
        "request": {
            "url": exchange.request_url,
            "headers": exchange.request_headers,
            "body": exchange.request_body,
        },
        "response": {
            "status": exchange.response_status,
            "headers": exchange.response_headers,
            "body": response_body,
        },
        "error": (
            {
                "type": exchange.error_type,
                "message": exchange.error_message,
            }
            if exchange.error_type is not None
            else None
        ),
    }
