from collections.abc import AsyncGenerator
from dataclasses import dataclass
from json import loads as json_loads

from app.domain.llm.chat import ChatStreamEvent, ChatStreamEventKind
from app.domain.llm.provider_catalog import AuthScheme
from app.infra.llm.request_auth import build_auth_headers

_NO_SSE_EVENT = object()


@dataclass(frozen=True, slots=True)
class SseDone:
    pass


SSE_DONE = SseDone()


def _build_headers(auth_scheme: AuthScheme, api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    headers.update(build_auth_headers(auth_scheme, api_key))
    return headers

def _build_stream_headers(auth_scheme: AuthScheme, api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    headers.update(build_auth_headers(auth_scheme, api_key))
    return headers

async def _iter_sse_payloads(
    chunks: AsyncGenerator[bytes, None],
) -> AsyncGenerator[dict[str, object] | None | SseDone, None]:
    buffer = b""
    data_lines: list[bytes] = []
    async for chunk in chunks:
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            data = _consume_sse_line(data_lines, line)
            if data is _NO_SSE_EVENT:
                continue
            if data.strip() == b"[DONE]":
                yield SSE_DONE
                return
            yield _load_stream_payload(data)
    if buffer:
        data = _consume_sse_line(data_lines, buffer)
        if data is not _NO_SSE_EVENT:
            if data.strip() == b"[DONE]":
                yield SSE_DONE
                return
            yield _load_stream_payload(data)
    data = _flush_sse_data_lines(data_lines)
    if data is not _NO_SSE_EVENT:
        if data.strip() == b"[DONE]":
            yield SSE_DONE
            return
        yield _load_stream_payload(data)


def _consume_sse_line(data_lines: list[bytes], raw_line: bytes) -> bytes | object:
    line = raw_line.rstrip(b"\r")
    if not line:
        return _flush_sse_data_lines(data_lines)
    if line.startswith(b":"):
        return _NO_SSE_EVENT

    field, separator, value = line.partition(b":")
    if not separator:
        return _NO_SSE_EVENT
    if value.startswith(b" "):
        value = value[1:]
    if field != b"data":
        return _NO_SSE_EVENT

    data_lines.append(value)
    return _NO_SSE_EVENT


def _flush_sse_data_lines(data_lines: list[bytes]) -> bytes | object:
    if not data_lines:
        return _NO_SSE_EVENT
    data = b"\n".join(data_lines)
    data_lines.clear()
    return data

def _load_stream_payload(data: bytes) -> dict[str, object] | None:
    try:
        payload = json_loads(data)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None

def _protocol_error_event(
    message: str = "上游供应商返回了无法解析的流式响应。",
    *,
    code: str = "upstream_stream_protocol_error",
) -> ChatStreamEvent:
    return ChatStreamEvent(
        kind=ChatStreamEventKind.ERROR,
        error=message,
        error_code=code,
    )

def _extract_error_message(payload: dict[str, object]) -> str:
    error_payload = payload.get("error")
    if isinstance(error_payload, dict):
        message = error_payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return "上游供应商返回错误。"

def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None

def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None
