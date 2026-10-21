from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.errors import AppError
from app.infra.http_client import get_shared_http_client


async def request_deepseek_web(
    *, action: str, payload: dict[str, Any], api_key: str,
) -> dict[str, Any]:
    if action not in {"search", "fetch"}:
        raise ValueError("Unsupported DeepSeek web action")
    try:
        async with asyncio.timeout(150):
            response = await get_shared_http_client().post(
                f"https://api.deepseek.com/v1/tools/{action}",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
                timeout=httpx.Timeout(120, connect=15),
                follow_redirects=False,
            )
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise AppError("DeepSeek 搜索或网页读取超时。", code="DEEPSEEK_TIMEOUT") from exc
    except httpx.RequestError as exc:
        raise AppError(
            f"连接 DeepSeek 官方接口失败：{str(exc).replace(api_key, '[REDACTED]')}",
            code="DEEPSEEK_CONNECTION_FAILED",
        ) from exc
    try:
        result = response.json()
    except ValueError as exc:
        raise AppError(
            f"DeepSeek 返回了无效 JSON，HTTP {response.status_code}。",
            code="DEEPSEEK_INVALID_RESPONSE",
            details={"http_status": response.status_code},
        ) from exc
    if not isinstance(result, dict):
        raise AppError("DeepSeek 响应必须是 JSON 对象。", code="DEEPSEEK_INVALID_RESPONSE")
    if not response.is_success or result.get("error"):
        error = result.get("error")
        message = error.get("message") if isinstance(error, dict) else error
        raise AppError(
            f"DeepSeek 请求失败，HTTP {response.status_code}：{str(message or '未知上游错误').replace(api_key, '[REDACTED]')}",
            code="DEEPSEEK_HTTP_ERROR",
            details={"http_status": response.status_code},
        )
    return result
