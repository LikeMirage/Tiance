from __future__ import annotations

import contextlib
import json
import os
import sys
from collections.abc import Callable
from typing import Any, TextIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

Payload = dict[str, Any]
ToolResult = dict[str, Any]
ToolHandler = Callable[[Payload], ToolResult]

MODEL_CONTEXT_ENV = "TIANCE_MODEL_CONTEXT"
HOST_CAPABILITY_TOKEN_ENV = "TIANCE_HOST_CAPABILITY_TOKEN"
API_BASE_URL_ENV = "TIANCE_API_BASE_URL"

_HOST_CAPABILITY_PATHS = {
    "web_search": "/llm/provider-capabilities/web-search",
}


def get_model_context() -> dict[str, Any]:
    """Return the model context supplied to every tool execution."""

    raw = os.environ.get(MODEL_CONTEXT_ENV, "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}

    modalities = payload.get("input_modalities")
    normalized_modalities = (
        sorted(
            {
                str(modality).strip().lower()
                for modality in modalities
                if isinstance(modality, str) and modality.strip()
            }
        )
        if isinstance(modalities, list)
        else []
    )
    return {
        "provider_id": _optional_string(payload.get("provider_id")),
        "model_id": _optional_string(payload.get("model_id")),
        "input_modalities": normalized_modalities,
    }


def model_supports_input(modality: str) -> bool:
    normalized = modality.strip().lower()
    if not normalized:
        return False
    return normalized in get_model_context().get("input_modalities", [])


def call_host_capability(
    capability: str,
    payload: Payload,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Call a backend capability authorized for the current tool process."""

    normalized_capability = capability.strip().lower()
    path = _HOST_CAPABILITY_PATHS.get(normalized_capability)
    if path is None:
        raise ValueError(f"未知的后端能力：{capability}")
    if not isinstance(payload, dict):
        raise ValueError("后端能力输入必须是 JSON 对象。")
    if timeout_seconds <= 0:
        raise ValueError("后端能力请求超时时间必须大于 0。")

    api_base_url = os.environ.get(API_BASE_URL_ENV, "").strip().rstrip("/")
    token = os.environ.get(HOST_CAPABILITY_TOKEN_ENV, "").strip()
    if not api_base_url or not token:
        raise RuntimeError("当前工具执行没有获得后端供应商能力授权。")

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{api_base_url}{path}",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read()
    except HTTPError as exc:
        response_body = exc.read()
        raise RuntimeError(_host_capability_error_message(response_body, exc.code)) from exc
    except (URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", None) or str(exc)
        raise RuntimeError(f"连接后端供应商能力接口失败：{reason}") from exc

    try:
        result = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("后端供应商能力接口返回了无效 JSON。") from exc
    if not isinstance(result, dict):
        raise RuntimeError("后端供应商能力接口返回值必须是 JSON 对象。")
    return result


def run_tool(
    handler: ToolHandler,
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    error_stream: TextIO | None = None,
    exit_process: bool = True,
) -> int:
    """Run a Tiance tool entry function with the standard JSON bridge."""

    stdin = input_stream or sys.stdin
    stdout = output_stream or sys.stdout
    stderr = error_stream or sys.stderr

    exit_code = 0
    try:
        payload = _read_payload(stdin)
        with contextlib.redirect_stdout(stderr):
            result = handler(payload)
        if not isinstance(result, dict):
            result = _failure("工具返回值必须是 dict。")
            exit_code = 1
        elif result.get("ok") is False:
            exit_code = 1
    except Exception as exc:
        result = _failure(str(exc) or exc.__class__.__name__)
        exit_code = 1

    if not _write_result(stdout, result):
        result = _failure("工具返回值必须能转换为 JSON。")
        _write_result(stdout, result)
        exit_code = 1

    if exit_process:
        raise SystemExit(exit_code)
    return exit_code


def _read_payload(stream: TextIO) -> Payload:
    raw = stream.read()
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"工具输入不是合法 JSON：{exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError("工具输入必须是 JSON 对象。")
    return payload


def _write_result(stream: TextIO, result: ToolResult) -> bool:
    try:
        text = json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        return False
    stream.write(text)
    stream.write("\n")
    stream.flush()
    return True


def _failure(message: str) -> ToolResult:
    return {
        "ok": False,
        "error": message,
    }


def _optional_string(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _host_capability_error_message(response_body: bytes, status_code: int) -> str:
    try:
        payload = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    return f"后端供应商能力接口返回 HTTP {status_code}。"
