from app.domain.llm.chat import ChatStreamEvent, ChatStreamEventKind
from app.domain.llm.provider_catalog import AuthScheme
from app.infra.llm.chat_adapters.sse import SSE_DONE, _iter_sse_payloads
from app.infra.llm.request_auth import build_auth_headers


def _build_headers(auth_scheme: AuthScheme, api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    headers.update(build_auth_headers(auth_scheme, api_key))
    return headers

def _build_stream_headers(auth_scheme: AuthScheme, api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    headers.update(build_auth_headers(auth_scheme, api_key))
    return headers


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
