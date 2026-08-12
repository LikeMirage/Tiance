from __future__ import annotations

from dataclasses import dataclass
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any
from urllib.parse import urlparse


CONFIG_PATH = Path(__file__).with_name("config.json")
DEEPSEEK_KEY_URL = "https://platform.deepseek.com/api_keys"
VALID_REASONING_EFFORTS = {"high", "max"}


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True, slots=True)
class ToolConfig:
    responses_url: str
    api_key: str
    model: str
    reasoning_effort: str
    max_output_tokens: int
    request_timeout_seconds: int


def default_config_payload() -> dict[str, Any]:
    return {
        "deepseek": {
            "responses_url": "https://api.deepseek.com/v1/responses",
            "api_key": "",
            "model": "deepseek-v4-flash",
            "reasoning_effort": "high",
            "max_output_tokens": 32768,
            "request_timeout_seconds": 165,
        }
    }


def config_details(fields: list[str]) -> dict[str, Any]:
    return {
        "config_path": str(CONFIG_PATH.resolve(strict=False)),
        "fields": fields,
        "api_key_url": DEEPSEEK_KEY_URL,
        "expected_config": default_config_payload(),
        "configuration_steps": [
            "可调用 action=configure 并传入 api_key，由工具写入配置。",
            "打开 config_path 指向的 JSON 文件。",
            "把 DeepSeek 官方 API Key 写入 deepseek.api_key 的空字符串中。",
            "保存文件后重新调用 action=search。",
            "也可以设置环境变量 DEEPSEEK_API_KEY，环境变量优先于 config.json。",
        ],
        "ai_instruction": (
            "用户提供 DeepSeek 官方 API Key 后，可调用 action=configure 写入配置；"
            "工具结果不会回显密钥。"
        ),
    }


def configure_api_key(api_key: str) -> None:
    payload = default_config_payload()
    if CONFIG_PATH.exists():
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ToolError(
                "CONFIG_INVALID",
                "工具 config.json 不是有效 JSON，不能安全写入 API Key。",
                config_details(["deepseek"]),
            ) from exc
        if not isinstance(loaded, dict) or not isinstance(loaded.get("deepseek"), dict):
            raise ToolError(
                "CONFIG_INVALID",
                "config.json 必须包含 deepseek 配置对象。",
                config_details(["deepseek"]),
            )
        payload = loaded
    payload["deepseek"]["api_key"] = api_key
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=CONFIG_PATH.parent,
            prefix="config.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            json.dump(payload, temp_file, ensure_ascii=False, indent=2)
            temp_file.write("\n")
            temp_path = Path(temp_file.name)
        temp_path.replace(CONFIG_PATH)
    except OSError as exc:
        raise ToolError(
            "CONFIG_WRITE_FAILED",
            "无法写入工具 config.json。",
            {"config_path": str(CONFIG_PATH.resolve(strict=False))},
        ) from exc
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def load_config() -> ToolConfig:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(
            json.dumps(default_config_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        details = config_details(["deepseek"])
        details["parse_error"] = str(exc)
        raise ToolError("CONFIG_INVALID", "工具 config.json 不是有效 JSON。", details) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("deepseek"), dict):
        raise ToolError(
            "CONFIG_INVALID",
            "config.json 必须包含 deepseek 配置对象。",
            config_details(["deepseek"]),
        )
    deepseek = payload["deepseek"]
    effort = str(deepseek.get("reasoning_effort") or "high").strip().lower()
    if effort not in VALID_REASONING_EFFORTS:
        raise ToolError(
            "CONFIG_INVALID",
            "deepseek.reasoning_effort 只支持 high 或 max。",
            config_details(["deepseek.reasoning_effort"]),
        )
    return ToolConfig(
        responses_url=str(deepseek.get("responses_url") or "").strip(),
        api_key=(str(os.environ.get("DEEPSEEK_API_KEY") or "").strip()
                 or str(deepseek.get("api_key") or "").strip()),
        model=str(deepseek.get("model") or "").strip(),
        reasoning_effort=effort,
        max_output_tokens=read_int(deepseek.get("max_output_tokens"), 32768, 256, 384000),
        request_timeout_seconds=read_int(
            deepseek.get("request_timeout_seconds"),
            165,
            10,
            600,
        ),
    )


def validate_config(config: ToolConfig) -> None:
    missing: list[str] = []
    if not config.responses_url:
        missing.append("deepseek.responses_url")
    if not config.api_key:
        missing.append("deepseek.api_key 或环境变量 DEEPSEEK_API_KEY")
    if not config.model:
        missing.append("deepseek.model")
    if missing:
        raise ToolError(
            "CONFIG_MISSING",
            "DeepSeek 官方网络搜索工具配置不完整。",
            config_details(missing),
        )


def read_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def build_request(query: str, config: ToolConfig) -> dict[str, Any]:
    return {
        "model": config.model,
        "instructions": (
            "Use the server-side web search tool. Answer the request with current, "
            "source-grounded information and include citations when the API provides them."
        ),
        "input": query,
        "tools": [{"type": "web_search"}],
        "tool_choice": {"type": "web_search"},
        "reasoning": {"effort": config.reasoning_effort},
        "max_output_tokens": config.max_output_tokens,
    }


def post_json(url: str, api_key: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolError(
            "CONFIG_INVALID_URL",
            "deepseek.responses_url 不是有效的 HTTP 地址。",
            config_details(["deepseek.responses_url"]),
        )
    connection_class = (
        http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    )
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Tiance-DeepSeek-Web-Search/1.0",
    }
    try:
        connection = connection_class(parsed.netloc, timeout=timeout)
        connection.request("POST", path, body=body, headers=headers)
        response = connection.getresponse()
        try:
            status_code = response.status
            response_text = response.read().decode("utf-8", errors="replace")
        finally:
            response.close()
            connection.close()
    except OSError as exc:
        raise ToolError(
            "DEEPSEEK_REQUEST_FAILED",
            f"连接 DeepSeek 官方接口失败：{exc}",
            {"responses_url": url},
        ) from exc
    try:
        result = json.loads(response_text)
    except ValueError as exc:
        raise ToolError(
            "DEEPSEEK_INVALID_JSON",
            f"DeepSeek 返回了无效 JSON，HTTP {status_code}。",
            {"status_code": status_code, "text_preview": response_text[:500]},
        ) from exc
    if not isinstance(result, dict):
        raise ToolError(
            "DEEPSEEK_INVALID_RESPONSE",
            "DeepSeek 返回的 JSON 顶层不是对象。",
            {"status_code": status_code},
        )
    if status_code >= 400 or result.get("error"):
        details = {
            "status_code": status_code,
            "upstream_error": safe_value(result.get("error") or result),
        }
        if status_code in {401, 403}:
            details.update(config_details(["deepseek.api_key"]))
        raise ToolError(
            "DEEPSEEK_HTTP_ERROR",
            f"DeepSeek 官方接口请求失败，HTTP {status_code}：{error_message(result)}",
            details,
        )
    return result


def parse_response(payload: dict[str, Any]) -> dict[str, Any]:
    status = str(payload.get("status") or "").strip()
    if status in {"failed", "incomplete"}:
        raise ToolError(
            "DEEPSEEK_RESPONSE_NOT_COMPLETED",
            f"DeepSeek Responses 状态为 {status}。",
            {
                "status": status,
                "error": safe_value(payload.get("error")),
                "incomplete_details": safe_value(payload.get("incomplete_details")),
            },
        )
    output = payload.get("output")
    if not isinstance(output, list):
        raise ToolError("DEEPSEEK_INVALID_RESPONSE", "DeepSeek 响应缺少 output 数组。")

    answer_parts: list[str] = []
    search_queries: list[str] = []
    search_actions: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    saw_web_search = False
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "web_search_call":
            saw_web_search = True
            action = item.get("action")
            if isinstance(action, dict):
                search_actions.append(safe_value(action))
                append_queries(search_queries, action)
                append_action_sources(sources, action)
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                answer_parts.append(part["text"])
            annotations = part.get("annotations")
            if isinstance(annotations, list):
                append_annotation_sources(sources, annotations)

    if not saw_web_search:
        raise ToolError(
            "DEEPSEEK_WEB_SEARCH_NOT_USED",
            "DeepSeek 返回了回答，但没有执行服务端 web_search。",
        )
    answer = "\n".join(part for part in answer_parts if part).strip()
    if not answer:
        raise ToolError(
            "DEEPSEEK_EMPTY_ANSWER",
            "DeepSeek 已执行网络搜索，但没有返回可用答案。",
        )
    unique_sources = deduplicate_sources(sources)
    return {
        "provider": "DeepSeek official API",
        "model": str(payload.get("model") or ""),
        "answer": answer,
        "search_queries": unique_strings(search_queries),
        "sources": unique_sources,
        "search_actions": search_actions,
        "usage": safe_value(payload.get("usage")) if isinstance(payload.get("usage"), dict) else {},
        "response_id": payload.get("id"),
        "status": status or None,
    }


def append_queries(target: list[str], action: dict[str, Any]) -> None:
    query = action.get("query")
    if isinstance(query, str) and query.strip():
        target.append(query.strip())
    queries = action.get("queries")
    if isinstance(queries, list):
        target.extend(item.strip() for item in queries if isinstance(item, str) and item.strip())


def append_action_sources(target: list[dict[str, Any]], action: dict[str, Any]) -> None:
    raw_sources = action.get("sources")
    if not isinstance(raw_sources, list):
        return
    for source in raw_sources:
        if isinstance(source, dict) and isinstance(source.get("url"), str):
            target.append({
                "url": source["url"],
                "title": source.get("title"),
                "source_kind": "search_result",
                "metadata": safe_value(source),
            })


def append_annotation_sources(
    target: list[dict[str, Any]],
    annotations: list[Any],
) -> None:
    for annotation in annotations:
        if not isinstance(annotation, dict) or not isinstance(annotation.get("url"), str):
            continue
        target.append({
            "url": annotation["url"],
            "title": annotation.get("title"),
            "source_kind": str(annotation.get("type") or "citation"),
            "metadata": safe_value(annotation),
        })


def deduplicate_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in sources:
        url = str(source.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(source)
    return result


def unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def error_message(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    if isinstance(error, str):
        return error
    for key in ("message", "detail"):
        if payload.get(key):
            return str(payload[key])
    return "未知上游错误"


def safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): safe_value(item)
            for key, item in value.items()
            if str(key).casefold() not in {"authorization", "api_key", "token", "key"}
        }
    if isinstance(value, list):
        return [safe_value(item) for item in value]
    if isinstance(value, str):
        return value[:8000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def format_tool_error(error: ToolError) -> str:
    text = f"{error.code}: {error.message}"
    config_path = error.details.get("config_path")
    if isinstance(config_path, str) and config_path:
        text += f"\n配置文件：{config_path}"
    steps = error.details.get("configuration_steps")
    if isinstance(steps, list) and steps:
        text += "\n配置方法：\n" + "\n".join(
            f"{index}. {step}"
            for index, step in enumerate(steps, start=1)
            if isinstance(step, str) and step
        )
    return text


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        action = str(payload.get("action") or "search").strip().lower()
        if action == "config_info":
            return {
                "ok": True,
                "summary": "已返回 DeepSeek 官方网络搜索工具的独立配置位置和配置方法。",
                "data": config_details(["deepseek.api_key"]),
            }
        if action == "configure":
            api_key = payload.get("api_key")
            if not isinstance(api_key, str) or not api_key.strip():
                raise ToolError("INVALID_ARGUMENT", "configure 时 api_key 必须是非空字符串。")
            configure_api_key(api_key.strip())
            return {
                "ok": True,
                "summary": "DeepSeek 官方 API Key 已保存到本工具配置文件。",
                "data": {
                    "configured": True,
                    "config_path": str(CONFIG_PATH.resolve(strict=False)),
                },
            }
        if action != "search":
            raise ToolError(
                "INVALID_ARGUMENT",
                "action 只支持 search、configure 或 config_info。",
            )
        query = payload.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolError("INVALID_ARGUMENT", "query 必须是非空字符串。")
        config = load_config()
        validate_config(config)
        response = post_json(
            config.responses_url,
            config.api_key,
            build_request(query.strip(), config),
            config.request_timeout_seconds,
        )
        data = parse_response(response)
        return {
            "ok": True,
            "summary": f"DeepSeek 官方网络搜索已完成，返回 {len(data['sources'])} 条来源。",
            "data": data,
        }
    except ToolError as exc:
        return {
            "ok": False,
            "error": format_tool_error(exc),
            "error_info": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"DEEPSEEK_SEARCH_FAILED: {str(exc) or type(exc).__name__}",
            "error_info": {
                "code": "DEEPSEEK_SEARCH_FAILED",
                "message": str(exc) or type(exc).__name__,
                "details": {},
            },
        }


def main() -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        input_text = sys.stdin.read().lstrip("\ufeff")
        payload = json.loads(input_text or "{}")
    except ValueError as exc:
        result = {
            "ok": False,
            "error": f"INVALID_INPUT_JSON: {exc}",
            "error_info": {
                "code": "INVALID_INPUT_JSON",
                "message": str(exc),
                "details": {},
            },
        }
    else:
        result = run(payload if isinstance(payload, dict) else {})
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
