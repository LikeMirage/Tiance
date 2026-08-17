from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.domain.llm.chat import ChatCompletionRequest


@dataclass(frozen=True, slots=True)
class ChatHttpExchange:
    started_at: str
    completed_at: str
    request_url: str
    request_headers: dict[str, str]
    request_body: dict[str, object]
    response_status: int | None
    response_headers: dict[str, str]
    response_body: bytes
    error_type: str | None = None
    error_message: str | None = None


class ChatHttpExchangeRecorder(Protocol):
    def record_http_exchange(
        self,
        request: ChatCompletionRequest,
        exchange: ChatHttpExchange,
    ) -> None:
        ...


def exchange_to_payload(exchange: ChatHttpExchange) -> dict[str, Any]:
    try:
        response_body: dict[str, str] = {
            "encoding": "utf-8",
            "content": exchange.response_body.decode("utf-8"),
        }
    except UnicodeDecodeError:
        from base64 import b64encode

        response_body = {
            "encoding": "base64",
            "content": b64encode(exchange.response_body).decode("ascii"),
        }
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
