from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
import http.client
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlparse

from tiance_runtime import run_tool


TOOL_DIR = Path(__file__).resolve().parent
CONFIG_PATH = TOOL_DIR / "config.json"
DEFAULT_BASE_URL = "https://www.dmxapi.cn"
DEFAULT_MODEL = "gpt-image-2-03"
DEFAULT_OUTPUT_DIR = "generated/images"
API_KEY_URL = "https://www.dmxapi.cn/register"
IMAGE_ENDPOINT = "/v1/images/generations"
OUTPUT_FORMATS = {"png", "jpeg", "webp"}
RESERVED_EXTRA_KEYS = {"api_key", "authorization", "headers", "output_path", "input_path"}
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}


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
    model: str


@dataclass(frozen=True)
class Options:
    prompt: str
    api_key: str
    base_url: str
    model: str
    output_path: Path
    output_format: str
    size: str
    n: int
    quality: str
    background: str
    timeout_seconds: int
    extra: dict[str, Any]
    workspace_root: Path


def ok(summary: str, data: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    return {"ok": True, "summary": summary, "data": data, "warnings": warnings or []}


def fail(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    safe_details = details or {}
    error_text = f"{code}: {message}"
    if safe_details.get("config_path"):
        error_text += f"\n配置文件：{safe_details['config_path']}"
    if safe_details.get("fields"):
        error_text += f"\n需检查字段：{', '.join(str(item) for item in safe_details['fields'])}"
    if safe_details.get("api_key_url"):
        error_text += f"\n获取 Key：{safe_details['api_key_url']}"
    if safe_details.get("ai_instruction"):
        error_text += f"\nAI操作：{safe_details['ai_instruction']}"
    if safe_details.get("status_code") is not None:
        error_text += f"\n上游状态：{safe_details['status_code']}"
    return {
        "ok": False,
        "error": error_text,
        "error_info": {"code": code, "message": message, "details": safe_details},
        "warnings": [],
    }


def workspace_root() -> Path:
    raw = os.environ.get("TIANCE_WORKSPACE_ROOT") or os.environ.get("WORKSPACE_ROOT") or os.getcwd()
    return Path(raw).expanduser().resolve(strict=False)


def default_config_payload() -> dict[str, Any]:
    return {
        "dmxapi": {
            "base_url": DEFAULT_BASE_URL,
            "api_key": "",
            "model": DEFAULT_MODEL,
        }
    }


def config_guidance_details(fields: list[str], message: str) -> dict[str, Any]:
    return {
        "config_path": str(CONFIG_PATH.resolve(strict=False)),
        "fields": fields,
        "message": message,
        "api_key_url": API_KEY_URL,
        "expected_config": default_config_payload(),
        "ai_instruction": (
            "当前没有可用 DMXAPI API Key。请向用户索要 DMXAPI Key；用户提供后，修改 config_path 指向的 config.json，"
            "把密钥写入 dmxapi.api_key；不要把密钥作为绘图参数传入，也不要在最终回复中回显密钥原文。"
        ),
    }


def load_config() -> ToolConfig:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(default_config_payload(), ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        details = config_guidance_details(["dmxapi.base_url", "dmxapi.api_key", "dmxapi.model"], "请修复配置文件 JSON 格式。")
        details["parse_error"] = str(exc)
        raise ToolError("CONFIG_INVALID", "DMXAPI 绘图工具配置文件不是有效 JSON。", details) from exc
    if not isinstance(payload, dict):
        raise ToolError(
            "CONFIG_INVALID",
            "DMXAPI 绘图工具配置根节点必须是 JSON 对象。",
            config_guidance_details(["dmxapi.base_url", "dmxapi.api_key", "dmxapi.model"], "请按 expected_config 重写配置文件。"),
        )
    dmxapi = payload.get("dmxapi") if isinstance(payload.get("dmxapi"), dict) else {}
    return ToolConfig(
        base_url=str(dmxapi.get("base_url") or DEFAULT_BASE_URL).strip(),
        api_key=str(dmxapi.get("api_key") or "").strip(),
        model=str(dmxapi.get("model") or DEFAULT_MODEL).strip(),
    )


def prepare_options(payload: dict[str, Any]) -> Options:
    root = workspace_root()
    config = load_config()
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise ToolError("INVALID_ARGUMENT", "prompt 必须是非空字符串。")

    api_key = str(os.environ.get("DMXAPI_API_KEY") or "").strip() or config.api_key
    if not api_key:
        raise ToolError(
            "DMXAPI_API_KEY_MISSING",
            "缺少 DMXAPI API Key。",
            config_guidance_details(["dmxapi.api_key 或环境变量 DMXAPI_API_KEY"], "请提供 DMXAPI API Key 后重试。"),
        )

    output_format = str(payload.get("output_format") or "png").strip().lower()
    if output_format not in OUTPUT_FORMATS:
        raise ToolError("INVALID_ARGUMENT", "output_format 只支持 png、jpeg、webp。", {"output_format": output_format})

    output_path = resolve_output_path(payload.get("output_path"), root, output_format)
    base_url = str(payload.get("base_url") or config.base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    if not base_url:
        raise ToolError("INVALID_ARGUMENT", "base_url 不能为空。")

    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    safe_extra = {
        str(key): value
        for key, value in extra.items()
        if str(key).strip().lower() not in RESERVED_EXTRA_KEYS
    }
    return Options(
        prompt=prompt,
        api_key=api_key,
        base_url=base_url,
        model=str(payload.get("model") or config.model or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        output_path=output_path,
        output_format=output_format,
        size=str(payload.get("size") or "1024x1024").strip() or "1024x1024",
        n=read_int(payload.get("n"), 1, 1, 1),
        quality=str(payload.get("quality") or "").strip(),
        background=str(payload.get("background") or "").strip(),
        timeout_seconds=read_int(payload.get("timeout_seconds"), 300, 30, 600),
        extra=safe_extra,
        workspace_root=root,
    )


def resolve_output_path(value: Any, root: Path, output_format: str) -> Path:
    raw = str(value or "").strip()
    if raw:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = root / path
        resolved = path.resolve(strict=False)
        ensure_inside(resolved, root, "OUTPUT_OUTSIDE_WORKSPACE", "输出图片路径必须位于工作区内。")
        if resolved.suffix.lower().lstrip(".") not in OUTPUT_FORMATS:
            resolved = resolved.with_suffix(f".{output_format}")
        return unique_path(resolved)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = sanitize_stem(f"dmxapi_image_{timestamp}") + f".{output_format}"
    return unique_path((root / DEFAULT_OUTPUT_DIR / filename).resolve(strict=False))


def ensure_inside(path: Path, root: Path, code: str, message: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ToolError(code, message, {"path": str(path), "workspace_root": str(root)}) from exc


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 2
    while True:
        candidate = parent / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def sanitize_stem(stem: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(stem or "")).strip(" .")
    if not cleaned:
        cleaned = "image"
    if cleaned.upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"{cleaned}_"
    return cleaned[:120]


def read_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def build_payload(options: Options) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": options.model,
        "prompt": options.prompt,
        "n": options.n,
        "size": options.size,
    }
    if options.quality:
        payload["quality"] = options.quality
    if options.background:
        payload["background"] = options.background
    if options.output_format:
        payload["output_format"] = options.output_format
    payload.update(options.extra)
    return payload


def call_dmxapi(options: Options) -> dict[str, Any]:
    url = f"{options.base_url}{IMAGE_ENDPOINT}"
    headers = {
        "Authorization": f"Bearer {options.api_key}",
        "Accept": "application/json",
        "User-Agent": "DMXAPI/1.0.0 (https://www.dmxapi.cn)",
        "Content-Type": "application/json",
    }
    body = json.dumps(build_payload(options), ensure_ascii=False).encode("utf-8")
    status_code, text = http_request("POST", url, headers=headers, body=body, timeout=options.timeout_seconds)
    try:
        response_payload = json.loads(text)
    except ValueError as exc:
        raise ToolError(
            "DMXAPI_INVALID_JSON",
            f"DMXAPI 返回了无效 JSON，HTTP {status_code}。",
            {"status_code": status_code, "text_preview": text[:500]},
        ) from exc
    if not isinstance(response_payload, dict):
        raise ToolError(
            "DMXAPI_INVALID_RESPONSE",
            "DMXAPI 返回结构异常。",
            {"status_code": status_code, "payload_type": type(response_payload).__name__},
        )
    if status_code >= 400:
        message = extract_error_message(response_payload, text)
        details = {
            "status_code": status_code,
            "upstream_payload": safe_payload(response_payload),
            "ai_instruction": "请检查 DMXAPI Key 是否正确、账号是否有额度、模型名是否可用；如果是 429，请稍后重试，不要并发连续调用。",
        }
        raise ToolError("DMXAPI_HTTP_ERROR", f"DMXAPI 请求失败，HTTP {status_code}：{message}", details)
    return response_payload


def http_request(method: str, url: str, headers: dict[str, str], body: bytes, timeout: int) -> tuple[int, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolError("INVALID_BASE_URL", "base_url 不是有效 HTTP 地址。", {"base_url": url})
    connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    try:
        connection = connection_cls(parsed.netloc, timeout=timeout)
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        try:
            response_body = response.read()
            return response.status, response_body.decode("utf-8", errors="replace")
        finally:
            response.close()
            connection.close()
    except OSError as exc:
        raise ToolError(
            "DMXAPI_REQUEST_FAILED",
            f"请求 DMXAPI 失败：{exc}",
            {
                "ai_instruction": "请检查网络、DMXAPI base_url、账号权限和额度。",
                "base_url": parsed.netloc,
            },
        ) from exc


def extract_error_message(payload: dict[str, Any], fallback: str) -> str:
    error = payload.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    if payload.get("message"):
        return str(payload["message"])
    return fallback[:500]


def save_first_image(response_payload: dict[str, Any], options: Options) -> dict[str, Any]:
    data = response_payload.get("data")
    if not isinstance(data, list) or not data:
        raise ToolError(
            "DMXAPI_EMPTY_RESULT",
            "DMXAPI 未返回图片结果。",
            {"upstream_payload": safe_payload(response_payload)},
        )
    first = data[0]
    if not isinstance(first, dict):
        raise ToolError("DMXAPI_INVALID_IMAGE_ITEM", "DMXAPI 图片结果结构异常。", {"item_type": type(first).__name__})

    image_bytes: bytes
    source_type: str
    if isinstance(first.get("b64_json"), str) and first["b64_json"].strip():
        try:
            image_bytes = base64.b64decode(first["b64_json"], validate=False)
        except Exception as exc:
            raise ToolError("DMXAPI_INVALID_BASE64", "DMXAPI 返回的 b64_json 无法解码。") from exc
        source_type = "b64_json"
    elif isinstance(first.get("url"), str) and first["url"].strip():
        image_bytes = download_image(first["url"].strip(), options.timeout_seconds)
        source_type = "url"
    else:
        raise ToolError(
            "DMXAPI_IMAGE_MISSING",
            "DMXAPI 返回结果中没有 b64_json 或 url。",
            {"image_item": safe_payload(first)},
        )

    if not image_bytes:
        raise ToolError("DMXAPI_EMPTY_IMAGE_BYTES", "DMXAPI 图片内容为空。")
    options.output_path.parent.mkdir(parents=True, exist_ok=True)
    options.output_path.write_bytes(image_bytes)
    return {
        "output_path": relative_or_absolute(options.output_path, options.workspace_root),
        "absolute_output_path": str(options.output_path),
        "bytes": len(image_bytes),
        "source_type": source_type,
        "mime_type": mimetypes.guess_type(str(options.output_path))[0] or f"image/{options.output_format}",
    }


def download_image(url: str, timeout: int) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolError("DMXAPI_INVALID_IMAGE_URL", "DMXAPI 返回的图片 URL 无效。", {"url": url[:200]})
    connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    try:
        connection = connection_cls(parsed.netloc, timeout=timeout)
        connection.request("GET", path, headers={"User-Agent": "DMXAPI/1.0.0 (https://www.dmxapi.cn)"})
        response = connection.getresponse()
        try:
            data = response.read()
            if response.status >= 400:
                raise ToolError(
                    "DMXAPI_IMAGE_DOWNLOAD_FAILED",
                    f"下载生成图片失败，HTTP {response.status}。",
                    {"status_code": response.status, "url": url[:200]},
                )
            return data
        finally:
            response.close()
            connection.close()
    except ToolError:
        raise
    except OSError as exc:
        raise ToolError("DMXAPI_IMAGE_DOWNLOAD_FAILED", f"下载生成图片失败：{exc}", {"url": url[:200]}) from exc


def relative_or_absolute(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def safe_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): safe_payload(item)
            for key, item in value.items()
            if str(key).lower() not in {"authorization", "api_key", "key", "token"}
        }
    if isinstance(value, list):
        return [safe_payload(item) for item in value[:5]]
    if isinstance(value, str):
        return value[:1000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(type(value).__name__)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        options = prepare_options(payload)
        response_payload = call_dmxapi(options)
        image_data = save_first_image(response_payload, options)
        data = {
            **image_data,
            "model": options.model,
            "size": options.size,
            "output_format": options.output_format,
            "request_id": response_payload.get("id") or response_payload.get("request_id"),
            "created": response_payload.get("created"),
            "usage": response_payload.get("usage") if isinstance(response_payload.get("usage"), dict) else None,
        }
        return ok(f"DMXAPI 图片生成完成：{image_data['output_path']}。", data)
    except ToolError as exc:
        return fail(exc.code, exc.message, exc.details)
    except Exception as exc:
        return fail("DMXAPI_IMAGE_GENERATE_FAILED", str(exc) or type(exc).__name__)


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    run_tool(run)
