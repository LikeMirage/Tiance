from __future__ import annotations

import http.client
import json

from deepseek_config import ToolError


def post_direct(action: str, payload: dict, api_key: str) -> dict:
    if action not in {"search", "fetch"}:
        raise ToolError("INVALID_ARGUMENT", "不支持的搜索操作。")
    connection = http.client.HTTPSConnection("api.deepseek.com", timeout=120)
    try:
        connection.request(
            "POST", f"/v1/tools/{action}",
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        status, body = response.status, response.read()
    except TimeoutError as exc:
        raise ToolError("DEEPSEEK_TIMEOUT", "DeepSeek 搜索或网页读取超时。") from exc
    except (OSError, http.client.HTTPException) as exc:
        raise ToolError("DEEPSEEK_CONNECTION_FAILED", f"连接 DeepSeek 官方接口失败：{str(exc).replace(api_key, '[REDACTED]')}") from exc
    finally:
        connection.close()
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ToolError("DEEPSEEK_INVALID_RESPONSE", f"DeepSeek 返回了无效 JSON，HTTP {status}。", {"http_status": status}) from exc
    if not isinstance(data, dict):
        raise ToolError("DEEPSEEK_INVALID_RESPONSE", "DeepSeek 响应必须是 JSON 对象。")
    if not 200 <= status < 300 or data.get("error"):
        error = data.get("error")
        message = error.get("message") if isinstance(error, dict) else error
        raise ToolError(
            "DEEPSEEK_HTTP_ERROR",
            f"DeepSeek 请求失败，HTTP {status}：{str(message or '未知上游错误').replace(api_key, '[REDACTED]')}",
            {"http_status": status},
        )
    return data