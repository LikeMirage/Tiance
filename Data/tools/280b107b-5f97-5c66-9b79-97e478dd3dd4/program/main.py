from __future__ import annotations

from dataclasses import dataclass
import http.client
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlencode, urlparse

from tiance_runtime import run_tool


CONFIG_PATH = Path(__file__).with_name("config.json")
API_KEY_URL = "https://serpapi.com/manage-api-key"
ENGINE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
VALID_DEVICES = {"desktop", "tablet", "mobile"}
RESERVED_EXTRA_KEYS = {"api_key", "output"}
CONFIG_FIELDS = [
    "serpapi.base_url",
    "serpapi.api_key",
    "serpapi.defaults.engine",
    "serpapi.defaults.device",
    "serpapi.defaults.hl",
    "serpapi.defaults.num",
]

RESULT_SECTION_KEYS = [
    "organic_results",
    "news_results",
    "top_stories",
    "images_results",
    "videos_results",
    "shopping_results",
    "ads_results",
    "inline_images",
    "inline_videos",
    "local_results",
    "places_results",
    "recipes_results",
    "events_results",
    "jobs_results",
    "related_questions",
    "questions_and_answers",
    "people_also_ask",
]
SINGLE_RESULT_SECTION_KEYS = ["answer_box", "knowledge_graph", "sports_results", "weather_result"]


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
    engine: str
    device: str
    hl: str
    num: int
    no_cache: bool
    async_search: bool
    zero_trace: bool
    include_raw_response: bool
    max_result_items: int
    request_timeout_seconds: int
    max_text_chars: int
    max_raw_response_chars: int


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
        "serpapi": {
            "base_url": "https://serpapi.com",
            "api_key": "",
            "defaults": {
                "engine": "google",
                "device": "desktop",
                "hl": "zh-cn",
                "num": 10,
                "no_cache": False,
                "async": False,
                "zero_trace": False,
                "include_raw_response": False,
                "max_result_items": 20,
                "request_timeout_seconds": 60,
                "max_text_chars": 1200,
                "max_raw_response_chars": 12000,
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
            "请指导用户到 SerpAPI 平台获取 API Key。用户提供后，按 expected_config 格式修改 config_path 指向的 JSON 文件；"
            "至少填写 serpapi.api_key，不要在最终回复中回显密钥原文。"
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

    serpapi = payload.get("serpapi") if isinstance(payload.get("serpapi"), dict) else {}
    defaults = serpapi.get("defaults") if isinstance(serpapi.get("defaults"), dict) else {}
    return ToolConfig(
        base_url=str(serpapi.get("base_url") or "").strip(),
        api_key=str(serpapi.get("api_key") or "").strip(),
        engine=read_engine(defaults.get("engine"), "google"),
        device=read_enum(defaults.get("device"), VALID_DEVICES, "desktop"),
        hl=str(defaults.get("hl") or "zh-cn").strip() or "zh-cn",
        num=read_int(defaults.get("num"), 10, 1, 100),
        no_cache=read_bool(defaults.get("no_cache"), False),
        async_search=read_bool(defaults.get("async"), False),
        zero_trace=read_bool(defaults.get("zero_trace"), False),
        include_raw_response=read_bool(defaults.get("include_raw_response"), False),
        max_result_items=read_int(defaults.get("max_result_items"), 20, 1, 100),
        request_timeout_seconds=read_int(defaults.get("request_timeout_seconds"), 60, 10, 300),
        max_text_chars=read_int(defaults.get("max_text_chars"), 1200, 200, 8000),
        max_raw_response_chars=read_int(defaults.get("max_raw_response_chars"), 12000, 1000, 60000),
    )


def ensure_tool_config(config: ToolConfig) -> None:
    missing: list[str] = []
    if not config.base_url:
        missing.append("serpapi.base_url")
    if not config.api_key:
        missing.append("serpapi.api_key")
    if missing:
        raise ToolError(
            "CONFIG_MISSING",
            "SerpAPI 搜索工具运行配置不完整。",
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


def read_engine(value: Any, default: str) -> str:
    text = str(value or "").strip().lower()
    if ENGINE_PATTERN.match(text):
        return text
    return default


def read_payload_int(payload: dict[str, Any], key: str, default: int, minimum: int, maximum: int) -> int:
    return read_int(payload.get(key), default, minimum, maximum) if key in payload else default


def append_scalar_param(params: dict[str, Any], payload: dict[str, Any], key: str, target_key: str | None = None) -> None:
    if key not in payload:
        return
    value = payload.get(key)
    if value is None:
        return
    if isinstance(value, str) and not value.strip():
        return
    params[target_key or key] = value


def append_bool_param(params: dict[str, Any], payload: dict[str, Any], key: str, default: bool | None = None) -> bool:
    if key in payload:
        value = read_bool(payload.get(key), False)
    elif default is not None:
        value = default
    else:
        return False
    params[key] = value
    return value


def build_search_params(payload: dict[str, Any], config: ToolConfig) -> tuple[dict[str, Any], int, dict[str, Any], list[str]]:
    warnings: list[str] = []
    engine = read_engine(payload.get("engine"), config.engine)
    query = str(payload.get("query") or "").strip()
    cites = str(payload.get("cites") or "").strip()
    cluster = str(payload.get("cluster") or "").strip()
    extra_parameters = normalize_extra_parameters(payload.get("extra_parameters"), warnings)

    if not query and not cites and not cluster and not extra_parameters:
        raise ToolError("INVALID_ARGUMENT", "query 必须是非空字符串；Google Scholar 的 cites 或 cluster 查询可不填 query。")
    if cluster and (query or cites):
        raise ToolError("INVALID_ARGUMENT", "Google Scholar 使用 cluster 时不要同时传 query 或 cites。")

    no_cache = append_bool_value(payload.get("no_cache"), config.no_cache)
    async_search = append_bool_value(payload.get("async"), config.async_search)
    if no_cache and async_search:
        raise ToolError("INVALID_ARGUMENT", "no_cache 和 async 不能同时为 true。")

    params: dict[str, Any] = {
        "engine": engine,
        "api_key": config.api_key,
        "output": "json",
        "device": read_enum(payload.get("device"), VALID_DEVICES, config.device),
    }
    if query:
        params["q"] = query
    if no_cache:
        params["no_cache"] = True
    if async_search:
        params["async"] = True
    if append_bool_value(payload.get("zero_trace"), config.zero_trace):
        params["zero_trace"] = True

    num = read_payload_int(payload, "num", config.num, 1, 100)
    if "num" in payload or config.num:
        params["num"] = num

    for key in (
        "location",
        "uule",
        "lat",
        "lon",
        "radius",
        "hl",
        "gl",
        "lr",
        "cr",
        "google_domain",
        "tbm",
        "tbs",
        "safe",
        "nfpr",
        "filter",
        "start",
        "cites",
        "cluster",
        "as_sdt",
        "scisbd",
        "mkt",
        "cc",
        "first",
        "safeSearch",
        "filters",
        "ct",
        "pn",
        "rn",
        "gpc",
        "q5",
        "q6",
        "bs",
        "oq",
        "f",
    ):
        append_scalar_param(params, payload, key)

    if "hl" not in params and config.hl:
        params["hl"] = config.hl
    append_scalar_param(params, payload, "year_from", "as_ylo")
    append_scalar_param(params, payload, "year_to", "as_yhi")
    append_scalar_param(params, payload, "author", "as_sauthors")
    append_scalar_param(params, payload, "publication", "as_publication")

    if "scisbd" not in params and payload.get("sort_by") == "date":
        params["scisbd"] = "2"
    if "as_sdt" not in params and "include_patents" in payload:
        params["as_sdt"] = "7" if read_bool(payload.get("include_patents"), False) else "0"

    params.update(extra_parameters)
    timeout = read_payload_int(payload, "request_timeout_seconds", config.request_timeout_seconds, 10, 300)
    output_options = {
        "include_raw_response": read_bool(payload.get("include_raw_response"), config.include_raw_response),
        "max_result_items": read_payload_int(payload, "max_result_items", config.max_result_items, 1, 100),
    }
    return params, timeout, output_options, warnings


def append_bool_value(value: Any, default: bool) -> bool:
    return read_bool(value, default) if value is not None else default


def normalize_extra_parameters(value: Any, warnings: list[str]) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ToolError("INVALID_ARGUMENT", "extra_parameters 必须是 JSON 对象。")
    params: dict[str, Any] = {}
    for key, item in value.items():
        text_key = str(key or "").strip()
        if not text_key:
            continue
        if text_key in RESERVED_EXTRA_KEYS:
            warnings.append(f"extra_parameters.{text_key} 已忽略；该字段由工具配置或输出模式控制。")
            continue
        if item is None:
            continue
        if isinstance(item, (str, int, float, bool)):
            params[text_key] = item
        elif isinstance(item, list):
            params[text_key] = [str(part) for part in item if part is not None]
        else:
            params[text_key] = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
    return params


def http_get_json(base_url: str, params: dict[str, Any], timeout: int) -> tuple[int, str]:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolError(
            "INVALID_URL",
            "SerpAPI 地址无效。",
            config_guidance_details(["serpapi.base_url"], "请检查配置文件中的 serpapi.base_url。"),
        )
    query = urlencode(encode_query_params(params), doseq=True)
    base_path = parsed.path.rstrip("/")
    path = f"{base_path}/search.json" if base_path else "/search.json"
    if parsed.query:
        path = f"{path}?{parsed.query}&{query}"
    else:
        path = f"{path}?{query}"
    connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    try:
        connection = connection_cls(parsed.netloc, timeout=timeout)
        connection.request("GET", path, headers={"Accept": "application/json"})
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
            f"请求 SerpAPI 失败：{exc}",
            config_guidance_details(CONFIG_FIELDS, "如果网络正常，请检查 SerpAPI API Key、base_url、权限和额度。"),
        ) from exc


def encode_query_params(params: dict[str, Any]) -> dict[str, Any]:
    encoded: dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, bool):
            encoded[key] = "true" if value else "false"
        elif isinstance(value, list):
            encoded[key] = ["true" if item is True else "false" if item is False else item for item in value]
        else:
            encoded[key] = value
    return encoded


def parse_serpapi_response(status_code: int, text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except ValueError as exc:
        details: dict[str, Any] = {"status_code": status_code, "text_preview": text[:500]}
        if status_code >= 400:
            details.update(
                config_guidance_details(
                    ["serpapi.api_key"],
                    "SerpAPI 接口返回错误但不是有效 JSON，请检查 API Key、base_url、权限和额度。",
                )
            )
        raise ToolError(
            "SERPAPI_INVALID_JSON",
            f"SerpAPI 返回了无效 JSON，HTTP {status_code}。",
            details,
        ) from exc
    if not isinstance(payload, dict):
        details = {"status_code": status_code, "payload": safe_payload(payload)}
        if status_code >= 400:
            details.update(
                config_guidance_details(
                    ["serpapi.api_key"],
                    "SerpAPI 接口返回错误结构异常，请检查 API Key、base_url、权限和额度。",
                )
            )
        raise ToolError("SERPAPI_INVALID_RESPONSE", "SerpAPI 返回结构异常。", details)
    if status_code >= 400 or payload.get("error"):
        message = str(payload.get("error") or text[:500])
        details: dict[str, Any] = {"status_code": status_code, "payload": safe_payload(payload)}
        details.update(
            config_guidance_details(
                ["serpapi.api_key"],
                "SerpAPI 接口请求失败，请检查 API Key 是否正确、是否过期、权限或额度是否可用。",
            )
        )
        raise ToolError("SERPAPI_HTTP_ERROR", f"SerpAPI 请求失败，HTTP {status_code}：{message}", details)
    return payload


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
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        text = str(value)
    if len(text) <= max_chars:
        return text
    warnings.append(f"{label} 内容超过 {max_chars} 字符，已截断。")
    return text[:max_chars].rstrip() + "\n...[truncated]"


def first_text(source: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, dict):
            for nested_key in ("text", "title", "name", "visible", "link"):
                nested_value = value.get(nested_key)
                if nested_value:
                    return str(nested_value)
        if isinstance(value, list):
            parts = [str(item) for item in value if item is not None]
            if parts:
                return " ".join(parts)
    return ""


def normalize_result_item(
    item: Any,
    section: str,
    index: int,
    max_text_chars: int,
    warnings: list[str],
) -> dict[str, Any]:
    source = item if isinstance(item, dict) else {}
    link = first_text(source, ["link", "url", "serpapi_link", "original", "thumbnail"])
    snippet = truncate_text(
        first_text(source, ["snippet", "description", "summary", "content", "rich_snippet"]),
        max_text_chars,
        warnings,
        f"{section} 第 {index} 条摘要",
    )
    return {
        "index": index,
        "section": section,
        "position": source.get("position"),
        "title": first_text(source, ["title", "name", "question", "displayed_title"]),
        "link": link,
        "displayed_link": first_text(source, ["displayed_link", "source", "domain"]),
        "snippet": snippet,
        "date": first_text(source, ["date", "published_date"]),
        "thumbnail": first_text(source, ["thumbnail", "thumbnail_link", "image"]),
        "rating": source.get("rating"),
        "price": source.get("price"),
        "publication_info": safe_payload(source.get("publication_info")) if isinstance(source.get("publication_info"), dict) else None,
        "inline_links": safe_payload(source.get("inline_links")) if isinstance(source.get("inline_links"), dict) else None,
        "resources": safe_payload(source.get("resources")) if isinstance(source.get("resources"), list) else [],
    }


def collect_results(
    response_payload: dict[str, Any],
    max_items: int,
    max_text_chars: int,
    warnings: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    results: list[dict[str, Any]] = []
    sections: list[str] = []
    for section in RESULT_SECTION_KEYS:
        raw_items = response_payload.get(section)
        if not isinstance(raw_items, list) or not raw_items:
            continue
        sections.append(section)
        for item in raw_items:
            if len(results) >= max_items:
                warnings.append(f"结果超过 {max_items} 条，已停止继续归一化输出。")
                return results, sections
            results.append(normalize_result_item(item, section, len(results) + 1, max_text_chars, warnings))

    for section in SINGLE_RESULT_SECTION_KEYS:
        raw_item = response_payload.get(section)
        if not isinstance(raw_item, dict) or not raw_item:
            continue
        sections.append(section)
        if len(results) >= max_items:
            warnings.append(f"结果超过 {max_items} 条，已停止继续归一化输出。")
            return results, sections
        results.append(normalize_result_item(raw_item, section, len(results) + 1, max_text_chars, warnings))
    return results, sections


def build_output(
    response_payload: dict[str, Any],
    request_params: dict[str, Any],
    config: ToolConfig,
    output_options: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    results, sections = collect_results(
        response_payload,
        int(output_options["max_result_items"]),
        config.max_text_chars,
        warnings,
    )
    metadata = response_payload.get("search_metadata") if isinstance(response_payload.get("search_metadata"), dict) else {}
    information = response_payload.get("search_information") if isinstance(response_payload.get("search_information"), dict) else {}
    data: dict[str, Any] = {
        "engine": request_params.get("engine"),
        "query": request_params.get("q"),
        "search_metadata": safe_payload(metadata),
        "search_information": safe_payload(information),
        "sections": sections,
        "results": results,
        "answer_box": safe_payload(response_payload.get("answer_box")) if isinstance(response_payload.get("answer_box"), dict) else None,
        "knowledge_graph": safe_payload(response_payload.get("knowledge_graph")) if isinstance(response_payload.get("knowledge_graph"), dict) else None,
        "related_searches": safe_payload(response_payload.get("related_searches")) if isinstance(response_payload.get("related_searches"), list) else [],
        "search_parameters": safe_payload(response_payload.get("search_parameters")) if isinstance(response_payload.get("search_parameters"), dict) else {},
        "request": safe_request_params(request_params),
    }
    if output_options["include_raw_response"]:
        raw_json = json.dumps(safe_payload(response_payload), ensure_ascii=False, separators=(",", ":"))
        data["raw_response_json"] = truncate_text(
            raw_json,
            config.max_raw_response_chars,
            warnings,
            "raw_response_json",
        )
    status = metadata.get("status") if isinstance(metadata, dict) else None
    summary = f"SerpAPI 搜索完成：engine={request_params.get('engine')}，返回 {len(results)} 条归一化结果。"
    if status:
        summary += f" 状态：{status}。"
    return ok(summary, data, warnings)


def safe_request_params(params: dict[str, Any]) -> dict[str, Any]:
    safe = safe_payload(params)
    if isinstance(safe, dict):
        safe.pop("api_key", None)
    return safe if isinstance(safe, dict) else {}


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        config = load_tool_config()
        ensure_tool_config(config)
        request_params, timeout, output_options, warnings = build_search_params(payload, config)
        status_code, text = http_get_json(config.base_url.rstrip("/"), request_params, timeout)
        response_payload = parse_serpapi_response(status_code, text)
        return build_output(response_payload, request_params, config, output_options, warnings)
    except ToolError as exc:
        return fail(exc.code, exc.message, exc.details)
    except Exception as exc:
        return fail("UNEXPECTED_ERROR", str(exc) or exc.__class__.__name__)


if __name__ == "__main__":
    run_tool(run)
