from __future__ import annotations

from dataclasses import dataclass
import http.client
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

from tiance_runtime import run_tool


CONFIG_PATH = Path(__file__).with_name("config.json")
API_KEY_URL = "https://app.tavily.com"
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
VALID_SEARCH_DEPTHS = {"basic", "advanced", "fast", "ultra-fast"}
VALID_TOPICS = {"general", "news", "finance"}
VALID_TIME_RANGES = {"day", "week", "month", "year", "d", "w", "m", "y"}
VALID_RAW_CONTENT = {"none", "markdown", "text"}
CONFIG_FIELDS = [
    "tavily.base_url",
    "tavily.api_key",
    "tavily.defaults.search_depth",
    "tavily.defaults.topic",
    "tavily.defaults.max_results",
    "tavily.defaults.include_answer",
    "tavily.defaults.include_raw_content",
    "tavily.defaults.include_images",
    "tavily.defaults.include_image_descriptions",
    "tavily.defaults.include_favicon",
    "tavily.defaults.include_usage",
]


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class ToolConfig:
    base_url: str
    api_key: str
    project_id: str
    search_depth: str
    topic: str
    max_results: int
    include_answer: bool | str
    include_raw_content: bool | str
    include_images: bool
    include_image_descriptions: bool
    include_favicon: bool
    include_usage: bool
    auto_parameters: bool
    exact_match: bool
    chunks_per_source: int
    request_timeout_seconds: int
    max_content_chars: int
    max_raw_content_chars: int


def ok(summary: str, data: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    return {"ok": True, "summary": summary, "data": data, "warnings": warnings}


def fail(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    safe_details = details or {}
    error_text = f"{code}: {message}"
    config_path = safe_details.get("config_path")
    fields = safe_details.get("fields")
    parse_error = safe_details.get("parse_error")
    if config_path:
        error_text += f"\n配置文件：{config_path}"
    if fields:
        error_text += f"\n需检查字段：{', '.join(str(item) for item in fields)}"
    if parse_error:
        error_text += f"\nJSON错误：{parse_error}"
    if safe_details.get("api_key_url"):
        error_text += f"\n获取 Key：{safe_details['api_key_url']}"
    if safe_details.get("ai_instruction"):
        error_text += f"\nAI操作：{safe_details['ai_instruction']}"
    return {
        "ok": False,
        "error": error_text,
        "error_info": {"code": code, "message": message, "details": safe_details},
        "warnings": [],
    }


def default_config_payload() -> dict[str, Any]:
    return {
        "tavily": {
            "base_url": "https://api.tavily.com",
            "api_key": "",
            "project_id": "",
            "defaults": {
                "search_depth": "basic",
                "topic": "general",
                "max_results": 5,
                "include_answer": "basic",
                "include_raw_content": False,
                "include_images": False,
                "include_image_descriptions": False,
                "include_favicon": True,
                "include_usage": True,
                "auto_parameters": False,
                "exact_match": False,
                "chunks_per_source": 3,
                "request_timeout_seconds": 60,
                "max_content_chars": 1200,
                "max_raw_content_chars": 4000,
            },
        }
    }


def ensure_config_file_exists() -> None:
    if CONFIG_PATH.exists():
        return
    CONFIG_PATH.write_text(json.dumps(default_config_payload(), ensure_ascii=False, indent=2), encoding="utf-8")


def config_guidance_details(fields: list[str], message: str) -> dict[str, Any]:
    return {
        "config_path": str(CONFIG_PATH.resolve(strict=False)),
        "fields": fields,
        "message": message,
        "api_key_url": API_KEY_URL,
        "ai_instruction": (
            "请指导用户到 Tavily 平台获取 API Key。用户提供后，按 expected_config 格式修改 config_path 指向的 JSON 文件；"
            "至少填写 tavily.api_key，不要在最终回复中回显密钥原文。"
        ),
        "expected_config": default_config_payload(),
    }


def load_tool_config() -> ToolConfig:
    ensure_config_file_exists()
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        details = config_guidance_details(CONFIG_FIELDS, "请修复配置文件 JSON 格式。")
        details["parse_error"] = str(exc)
        raise ToolError("CONFIG_INVALID", "工具配置文件不是有效 JSON。", details) from exc
    if not isinstance(payload, dict):
        raise ToolError(
            "CONFIG_INVALID",
            "工具配置文件根节点必须是 JSON 对象。",
            config_guidance_details(CONFIG_FIELDS, "请按 expected_config 重写配置文件。"),
        )

    tavily = payload.get("tavily") if isinstance(payload.get("tavily"), dict) else {}
    defaults = tavily.get("defaults") if isinstance(tavily.get("defaults"), dict) else {}
    return ToolConfig(
        base_url=str(tavily.get("base_url") or "").strip(),
        api_key=str(tavily.get("api_key") or "").strip(),
        project_id=str(tavily.get("project_id") or "").strip(),
        search_depth=read_enum(defaults.get("search_depth"), VALID_SEARCH_DEPTHS, "basic"),
        topic=read_enum(defaults.get("topic"), VALID_TOPICS, "general"),
        max_results=read_int(defaults.get("max_results"), 5, 1, 20),
        include_answer=read_include_answer(defaults.get("include_answer")),
        include_raw_content=read_include_raw_content(defaults.get("include_raw_content")),
        include_images=read_bool(defaults.get("include_images"), False),
        include_image_descriptions=read_bool(defaults.get("include_image_descriptions"), False),
        include_favicon=read_bool(defaults.get("include_favicon"), True),
        include_usage=read_bool(defaults.get("include_usage"), True),
        auto_parameters=read_bool(defaults.get("auto_parameters"), False),
        exact_match=read_bool(defaults.get("exact_match"), False),
        chunks_per_source=read_int(defaults.get("chunks_per_source"), 3, 1, 3),
        request_timeout_seconds=read_int(defaults.get("request_timeout_seconds"), 60, 10, 300),
        max_content_chars=read_int(defaults.get("max_content_chars"), 1200, 200, 8000),
        max_raw_content_chars=read_int(defaults.get("max_raw_content_chars"), 4000, 500, 20000),
    )


def ensure_tool_config(config: ToolConfig) -> None:
    missing: list[str] = []
    if not config.base_url:
        missing.append("tavily.base_url")
    if not config.api_key:
        missing.append("tavily.api_key")
    if missing:
        raise ToolError(
            "CONFIG_MISSING",
            "Tavily 搜索工具运行配置不完整。",
            config_guidance_details(missing, "请让用户提供缺失配置，然后修改配置文件后重试本工具。"),
        )


def read_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def read_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def read_enum(value: Any, allowed: set[str], default: str) -> str:
    text = str(value or "").strip()
    return text if text in allowed else default


def read_include_answer(value: Any) -> bool | str:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"basic", "advanced"}:
        return text
    if text in {"true", "1", "yes", "on"}:
        return "basic"
    return False


def read_include_raw_content(value: Any) -> bool | str:
    if isinstance(value, bool):
        return "markdown" if value else False
    text = str(value or "").strip().lower()
    if text in {"markdown", "text"}:
        return text
    if text in {"true", "1", "yes", "on"}:
        return "markdown"
    return False


def read_payload_int(payload: dict[str, Any], key: str, default: int, minimum: int, maximum: int) -> int:
    return read_int(payload.get(key), default, minimum, maximum) if key in payload else default


def read_payload_enum(payload: dict[str, Any], key: str, allowed: set[str], default: str) -> str:
    return read_enum(payload.get(key), allowed, default) if key in payload else default


def normalize_domains(value: Any, limit: int, field_name: str) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ToolError("INVALID_ARGUMENT", f"{field_name} 必须是字符串数组。")
    domains: list[str] = []
    seen: set[str] = set()
    for item in value[:limit]:
        text = str(item or "").strip().lower()
        if not text:
            continue
        parsed = urlparse(text if "://" in text else f"https://{text}")
        domain = parsed.netloc or parsed.path
        domain = domain.strip().strip("/")
        if not domain or domain in seen:
            continue
        domains.append(domain)
        seen.add(domain)
    return domains


def validate_date(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    text = str(value or "").strip()
    if not text:
        return None
    if not DATE_PATTERN.match(text):
        raise ToolError("INVALID_ARGUMENT", f"{field_name} 必须使用 YYYY-MM-DD 格式。")
    return text


def build_search_payload(payload: dict[str, Any], config: ToolConfig) -> tuple[dict[str, Any], int]:
    query = str(payload.get("query") or "").strip()
    if not query:
        raise ToolError("INVALID_ARGUMENT", "query 必须是非空字符串。")

    search_depth = read_payload_enum(payload, "search_depth", VALID_SEARCH_DEPTHS, config.search_depth)
    topic = read_payload_enum(payload, "topic", VALID_TOPICS, config.topic)
    include_raw_content = read_payload_enum(payload, "include_raw_content", VALID_RAW_CONTENT, "none")
    max_results = read_payload_int(payload, "max_results", config.max_results, 1, 20)
    timeout = read_payload_int(
        payload,
        "request_timeout_seconds",
        config.request_timeout_seconds,
        10,
        300,
    )

    request_payload: dict[str, Any] = {
        "query": query,
        "search_depth": search_depth,
        "topic": topic,
        "max_results": max_results,
        "include_answer": config.include_answer,
        "include_raw_content": False if include_raw_content == "none" else include_raw_content,
        "include_images": config.include_images,
        "include_image_descriptions": config.include_image_descriptions,
        "include_favicon": config.include_favicon,
        "include_usage": config.include_usage,
        "auto_parameters": config.auto_parameters,
        "exact_match": config.exact_match,
    }
    if search_depth == "advanced":
        request_payload["chunks_per_source"] = config.chunks_per_source

    time_range = payload.get("time_range")
    if time_range is not None:
        request_payload["time_range"] = read_enum(time_range, VALID_TIME_RANGES, "")
        if not request_payload["time_range"]:
            raise ToolError("INVALID_ARGUMENT", "time_range 必须是 day/week/month/year 或 d/w/m/y。")

    start_date = validate_date(payload.get("start_date"), "start_date")
    end_date = validate_date(payload.get("end_date"), "end_date")
    if start_date:
        request_payload["start_date"] = start_date
    if end_date:
        request_payload["end_date"] = end_date

    include_domains = normalize_domains(payload.get("include_domains"), 300, "include_domains")
    exclude_domains = normalize_domains(payload.get("exclude_domains"), 150, "exclude_domains")
    if include_domains:
        request_payload["include_domains"] = include_domains
    if exclude_domains:
        request_payload["exclude_domains"] = exclude_domains
    return request_payload, timeout


def http_post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: int,
) -> tuple[int, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolError(
            "INVALID_URL",
            "Tavily API 地址无效。",
            config_guidance_details(["tavily.base_url"], "请检查配置文件中的 tavily.base_url。"),
        )
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    try:
        connection = connection_cls(parsed.netloc, timeout=timeout)
        connection.request("POST", path, body=body, headers=headers)
        response = connection.getresponse()
        try:
            response_body = response.read()
            return response.status, response_body.decode("utf-8", errors="replace")
        finally:
            response.close()
            connection.close()
    except OSError as exc:
        raise ToolError(
            "HTTP_REQUEST_FAILED",
            f"请求 Tavily 失败：{exc}",
            config_guidance_details(CONFIG_FIELDS, "如果网络正常，请检查 Tavily API Key 和 base_url。"),
        ) from exc


def parse_tavily_response(status_code: int, text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except ValueError as exc:
        details: dict[str, Any] = {"status_code": status_code, "text_preview": text[:500]}
        if status_code >= 400:
            details.update(
                config_guidance_details(
                    ["tavily.api_key"],
                    "Tavily 接口返回错误但不是有效 JSON，请检查 API Key、base_url、权限和额度。",
                )
            )
        raise ToolError(
            "TAVILY_INVALID_JSON",
            f"Tavily 返回了无效 JSON，HTTP {status_code}。",
            details,
        ) from exc
    if not isinstance(payload, dict):
        details = {"status_code": status_code, "payload": safe_payload(payload)}
        if status_code >= 400:
            details.update(
                config_guidance_details(
                    ["tavily.api_key"],
                    "Tavily 接口返回错误结构异常，请检查 API Key、base_url、权限和额度。",
                )
            )
        raise ToolError("TAVILY_INVALID_RESPONSE", "Tavily 返回结构异常。", details)
    if status_code >= 400 or payload.get("error"):
        message = error_message_from_payload(payload, text)
        details: dict[str, Any] = {"status_code": status_code, "payload": safe_payload(payload)}
        details.update(
            config_guidance_details(
                ["tavily.api_key"],
                "Tavily 接口请求失败，请检查 API Key 是否正确、是否过期、权限或额度是否可用。",
            )
        )
        raise ToolError("TAVILY_HTTP_ERROR", f"Tavily 请求失败，HTTP {status_code}：{message}", details)
    return payload


def error_message_from_payload(payload: dict[str, Any], text: str) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        for key in ("message", "detail", "msg"):
            value = error.get(key)
            if value:
                return str(value)
    for key in ("message", "detail", "msg"):
        value = payload.get(key)
        if value:
            return str(value)
    return text[:500]


def safe_payload(value: Any) -> Any:
    if isinstance(value, dict):
        copied: dict[str, Any] = {}
        for key, item in value.items():
            if any(token in str(key).lower() for token in ("token", "key", "authorization")):
                copied[str(key)] = "***"
            else:
                copied[str(key)] = safe_payload(item)
        return copied
    if isinstance(value, list):
        return [safe_payload(item) for item in value]
    return value


def truncate_text(value: Any, max_chars: int, warnings: list[str], label: str) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= max_chars:
        return text
    warnings.append(f"{label} 内容超过 {max_chars} 字符，已截断。")
    return text[:max_chars].rstrip() + "\n...[truncated]"


def normalize_result_item(item: Any, index: int, config: ToolConfig, warnings: list[str]) -> dict[str, Any]:
    source = item if isinstance(item, dict) else {}
    raw_content = truncate_text(
        source.get("raw_content"),
        config.max_raw_content_chars,
        warnings,
        f"第 {index} 条 raw_content",
    )
    return {
        "index": index,
        "title": str(source.get("title") or ""),
        "url": str(source.get("url") or ""),
        "content": truncate_text(source.get("content"), config.max_content_chars, warnings, f"第 {index} 条 content"),
        "score": source.get("score"),
        "published_date": source.get("published_date"),
        "raw_content": raw_content,
        "favicon": source.get("favicon"),
        "images": source.get("images") if isinstance(source.get("images"), list) else [],
    }


def build_output(response_payload: dict[str, Any], request_payload: dict[str, Any], config: ToolConfig) -> dict[str, Any]:
    warnings: list[str] = []
    raw_results = response_payload.get("results") if isinstance(response_payload.get("results"), list) else []
    results = [
        normalize_result_item(item, index, config, warnings)
        for index, item in enumerate(raw_results, start=1)
    ]
    data = {
        "query": response_payload.get("query") or request_payload.get("query"),
        "answer": response_payload.get("answer"),
        "results": results,
        "images": response_payload.get("images") if isinstance(response_payload.get("images"), list) else [],
        "response_time": response_payload.get("response_time"),
        "request_id": response_payload.get("request_id"),
        "usage": response_payload.get("usage") if isinstance(response_payload.get("usage"), dict) else None,
        "auto_parameters": response_payload.get("auto_parameters") if isinstance(response_payload.get("auto_parameters"), dict) else None,
        "request": {
            "search_depth": request_payload.get("search_depth"),
            "topic": request_payload.get("topic"),
            "max_results": request_payload.get("max_results"),
            "time_range": request_payload.get("time_range"),
            "include_raw_content": request_payload.get("include_raw_content"),
            "include_domains": request_payload.get("include_domains"),
            "exclude_domains": request_payload.get("exclude_domains"),
        },
    }
    summary = f"Tavily 搜索完成：{data['query']}，返回 {len(results)} 条结果。"
    return ok(summary, data, warnings)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        config = load_tool_config()
        ensure_tool_config(config)
        request_payload, timeout = build_search_payload(payload, config)
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }
        if config.project_id:
            headers["X-Project-ID"] = config.project_id
        status_code, text = http_post_json(
            f"{config.base_url.rstrip('/')}/search",
            headers,
            request_payload,
            timeout,
        )
        response_payload = parse_tavily_response(status_code, text)
        return build_output(response_payload, request_payload, config)
    except ToolError as exc:
        return fail(exc.code, exc.message, exc.details)
    except Exception as exc:
        return fail("UNEXPECTED_ERROR", str(exc) or exc.__class__.__name__)


if __name__ == "__main__":
    run_tool(run)
