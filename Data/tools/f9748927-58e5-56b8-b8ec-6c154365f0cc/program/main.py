from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import http.client
import json
import mimetypes
import os
from pathlib import Path
import re
import threading
from typing import Any
from urllib.parse import urlparse

from tiance_runtime import run_tool


TOOL_DIR = Path(__file__).resolve().parent
CONFIG_PATH = TOOL_DIR / "config.json"
DEFAULT_BASE_URL = "https://www.dmxapi.cn/v1"
DEFAULT_MODEL = "doubao-seed-1-6-flash-250828"
SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp"}
THINKING_TYPES = {"disabled", "auto", "enabled"}
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

SYSTEM_PROMPT = """你是高精度图片视觉解析助手，具备文字识别、版面还原和图像理解能力。

任务：
1. 识别并转录图片中的所有可见文字。
2. 使用 Markdown 输出，尽可能保持原始结构、段落、标题层级、列表、表格和公式。
3. 如果图片是文档页面，按从上到下、从左到右的顺序提取标题、正文、表格、图表说明、注释、页眉页脚、水印等内容。
4. 如果图片包含插图、照片、流程图、架构图、图表或界面截图，在对应位置用简洁文字描述其内容、位置关系、可见文字和关键信息。
5. 如果图片不是文档页面，而是普通照片或截图，描述图中真实可见的主体、布局、文字、颜色、状态和位置关系。

格式规则：
- 只输出 Markdown 内容，不添加无关寒暄。
- 表格尽量还原为 Markdown 表格。
- 数学公式尽量用 LaTeX/Markdown 表达。
- 手写或模糊内容尽力识别，无法确认时标注“无法可靠识别”。
- 非中文字符、数字、单位、专有名词保持原样。
- 页眉、页脚、页码、水印等边缘信息如可见，放在文末“其他信息”小节。

禁止：
- 不添加个人解读、总结、推测或评论。
- 不省略可见文字。
- 不把表格扩写成主观分析。
- 不编造看不清的文字、数字或图中不存在的信息。"""

DEFAULT_USER_PROMPT = "请提取并还原这张图片中的可见内容，使用 Markdown 输出。"


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
    image_paths: list[Any]
    user_prompt: str
    save_results: bool
    output_dir: Path | None
    overwrite: bool
    concurrency: int
    thinking_type: str
    temperature: float
    top_p: float
    max_output_tokens: int
    timeout_seconds: int
    max_image_bytes: int
    max_return_chars_per_image: int
    allow_source_outside_workspace: bool
    workspace_root: Path


def ok(summary: str, data: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    return {"ok": True, "summary": summary, "data": data, "warnings": warnings or []}


def fail(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    safe_details = details or {}
    error_text = f"{code}: {message}"
    if safe_details.get("status_code") is not None:
        error_text += f"\n上游状态：{safe_details['status_code']}"
    if safe_details.get("config_path"):
        error_text += f"\n配置文件：{safe_details['config_path']}"
    if safe_details.get("fields"):
        error_text += f"\n需检查字段：{', '.join(str(item) for item in safe_details['fields'])}"
    if safe_details.get("ai_instruction"):
        error_text += f"\nAI操作：{safe_details['ai_instruction']}"
    return {
        "ok": False,
        "error": error_text,
        "error_info": {"code": code, "message": message, "details": safe_details},
        "warnings": [],
    }


def workspace_root() -> Path:
    raw = os.environ.get("TIANCE_WORKSPACE_ROOT") or os.environ.get("WORKSPACE_ROOT") or os.getcwd()
    return Path(raw).expanduser().resolve(strict=False)


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
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def read_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def resolve_path(value: Any, root: Path) -> Path:
    raw = str(value or "").strip()
    if not raw:
        return root
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve(strict=False)


def is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def ensure_inside(path: Path, root: Path, code: str, message: str) -> None:
    if not is_inside(path, root):
        raise ToolError(code, message, {"path": str(path), "workspace_root": str(root)})


def relative_or_absolute(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def sanitize_stem(stem: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(stem or "")).strip(" .")
    if not cleaned:
        cleaned = "image"
    if cleaned.upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"{cleaned}_"
    return cleaned[:120]


def default_config_payload() -> dict[str, Any]:
    return {
        "dmxapi": {
            "base_url": DEFAULT_BASE_URL,
            "api_key": "",
            "model": DEFAULT_MODEL,
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
        "ai_instruction": (
            "请让用户提供 DMXAPI Key 或确认模型可用性。用户提供后，使用文件编辑能力修改 config_path 指向的 JSON 文件；"
            "不要在最终回复中回显密钥原文。"
        ),
        "expected_config": default_config_payload(),
    }


def load_config() -> ToolConfig:
    ensure_config_file_exists()
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        details = config_guidance_details(["dmxapi.base_url", "dmxapi.api_key", "dmxapi.model"], "请修复配置文件 JSON 格式。")
        details["parse_error"] = str(exc)
        raise ToolError("CONFIG_INVALID", "工具配置文件不是有效 JSON。", details) from exc
    if not isinstance(payload, dict):
        raise ToolError(
            "CONFIG_INVALID",
            "工具配置文件根节点必须是 JSON 对象。",
            config_guidance_details(["dmxapi.base_url", "dmxapi.api_key", "dmxapi.model"], "请按 expected_config 重写配置文件。"),
        )
    dmxapi = payload.get("dmxapi") if isinstance(payload.get("dmxapi"), dict) else {}
    base_url = str(dmxapi.get("base_url") or DEFAULT_BASE_URL).strip()
    api_key = str(dmxapi.get("api_key") or "").strip()
    model = str(dmxapi.get("model") or DEFAULT_MODEL).strip()
    missing = []
    if not base_url:
        missing.append("dmxapi.base_url")
    if not api_key:
        missing.append("dmxapi.api_key")
    if not model:
        missing.append("dmxapi.model")
    if missing:
        raise ToolError(
            "CONFIG_MISSING",
            "豆包视觉解析运行配置不完整。",
            config_guidance_details(missing, "请补齐缺失配置后重试本工具。"),
        )
    return ToolConfig(base_url=base_url, api_key=api_key, model=model)


def prepare_options(payload: dict[str, Any]) -> Options:
    root = workspace_root()
    image_paths = payload.get("image_paths")
    if not isinstance(image_paths, list) or not image_paths:
        raise ToolError("INVALID_ARGUMENT", "image_paths 必须是非空数组。")
    output_dir = None
    if str(payload.get("output_dir") or "").strip():
        output_dir = resolve_path(payload.get("output_dir"), root)
        ensure_inside(output_dir, root, "OUTPUT_OUTSIDE_WORKSPACE", "保存目录必须在工作区内。")
    thinking_type = str(payload.get("thinking_type") or "disabled").strip().lower()
    if thinking_type not in THINKING_TYPES:
        raise ToolError("INVALID_ARGUMENT", "thinking_type 只能是 disabled、auto 或 enabled。", {"thinking_type": thinking_type})
    return Options(
        image_paths=image_paths,
        user_prompt=str(payload.get("user_prompt") or DEFAULT_USER_PROMPT).strip() or DEFAULT_USER_PROMPT,
        save_results=read_bool(payload.get("save_results"), False),
        output_dir=output_dir,
        overwrite=read_bool(payload.get("overwrite"), False),
        concurrency=read_int(payload.get("concurrency"), 8, 1, 100),
        thinking_type=thinking_type,
        temperature=read_float(payload.get("temperature"), 0.1, 0, 2),
        top_p=read_float(payload.get("top_p"), 1, 0, 1),
        max_output_tokens=read_int(payload.get("max_output_tokens"), 4096, 1, 32768),
        timeout_seconds=read_int(payload.get("timeout_seconds"), 120, 10, 600),
        max_image_bytes=read_int(payload.get("max_image_bytes"), 20 * 1024 * 1024, 1024, 100 * 1024 * 1024),
        max_return_chars_per_image=read_int(payload.get("max_return_chars_per_image"), 20000, 0, 200000),
        allow_source_outside_workspace=read_bool(payload.get("allow_source_outside_workspace"), False),
        workspace_root=root,
    )


def validate_image_path(raw_path: Any, index: int, options: Options) -> dict[str, Any]:
    display_path = str(raw_path or "")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return image_error(index, display_path, "INVALID_IMAGE_PATH", "图片路径必须是非空字符串。")
    image_path = resolve_path(raw_path, options.workspace_root)
    if not options.allow_source_outside_workspace and not is_inside(image_path, options.workspace_root):
        return image_error(index, display_path, "PATH_OUTSIDE_WORKSPACE", "图片不在工作区内。", {"path": str(image_path)})
    if not image_path.exists():
        return image_error(index, display_path, "FILE_NOT_FOUND", "图片文件不存在。", {"path": str(image_path)})
    if not image_path.is_file():
        return image_error(index, display_path, "NOT_A_FILE", "图片路径必须指向文件。", {"path": str(image_path)})
    if image_path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
        return image_error(
            index,
            display_path,
            "UNSUPPORTED_IMAGE_TYPE",
            "当前工具只支持常见图片格式。",
            {"extension": image_path.suffix.lower(), "supported_extensions": sorted(SUPPORTED_IMAGE_EXTENSIONS)},
        )
    size_bytes = image_path.stat().st_size
    if size_bytes > options.max_image_bytes:
        return image_error(
            index,
            display_path,
            "IMAGE_TOO_LARGE",
            f"图片超过 max_image_bytes={options.max_image_bytes}，已跳过。",
            {"path": str(image_path), "size_bytes": size_bytes},
        )
    return {
        "ok": True,
        "index": index,
        "input_path": display_path,
        "image_path": str(image_path),
        "relative_image_path": relative_or_absolute(image_path, options.workspace_root),
        "path_obj": image_path,
        "size_bytes": size_bytes,
    }


def image_error(index: int, input_path: str, code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "index": index,
        "input_path": input_path,
        "error": f"{code}: {message}",
        "error_info": {"code": code, "message": message, "details": details or {}},
    }


def safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if "token" in lowered or "key" in lowered or "authorization" in lowered:
                cleaned[key] = "***"
            else:
                cleaned[key] = safe_value(item)
        return cleaned
    if isinstance(value, list):
        return [safe_value(item) for item in value[:100]]
    if isinstance(value, str):
        if value.startswith("data:image/"):
            return "data:image/...;base64,***"
        if len(value) > 2000:
            return f"{value[:2000]}...[truncated]"
    return value


def http_request(method: str, url: str, *, headers: dict[str, str], body: bytes | None, timeout: int) -> tuple[int, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolError(
            "INVALID_URL",
            "DMXAPI请求地址无效。",
            config_guidance_details(["dmxapi.base_url"], "请检查 base_url 是否为有效 HTTP/HTTPS 地址。"),
        )
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
            text = response_body.decode("utf-8", errors="replace")
            return response.status, text
        finally:
            response.close()
            connection.close()
    except OSError as exc:
        details = config_guidance_details(
            ["dmxapi.base_url", "dmxapi.api_key", "dmxapi.model"],
            "DMXAPI接口连接失败；如果网络正常，请检查 API Key、模型和接口地址。",
        )
        raise ToolError("HTTP_REQUEST_FAILED", f"请求DMXAPI失败：{exc}", details) from exc


def build_user_text(image_path: Path, options: Options) -> str:
    return "\n".join(
        [
            f"图片文件名：{image_path.name}",
            f"用户要求：{options.user_prompt}",
        ]
    )


def call_vision_api(image_path: Path, config: ToolConfig, options: Options) -> dict[str, Any]:
    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/png"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    data_url = f"data:{mime_type};base64,{encoded}"
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": build_user_text(image_path, options)},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        "temperature": options.temperature,
        "top_p": options.top_p,
        "max_completion_tokens": options.max_output_tokens,
    }
    if options.thinking_type != "disabled":
        payload["thinking"] = {"type": options.thinking_type}
    headers = {"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"}
    url = f"{config.base_url.rstrip('/')}/chat/completions"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    status_code, text = http_request("POST", url, headers=headers, body=body, timeout=options.timeout_seconds)
    try:
        response_payload = json.loads(text)
    except ValueError as exc:
        details = config_guidance_details(
            ["dmxapi.api_key", "dmxapi.model"],
            "DMXAPI返回异常，请检查 API Key、模型 ID、权限或额度。",
        )
        details.update({"status_code": status_code, "text_preview": text[:500]})
        raise ToolError("DMXAPI_INVALID_JSON", f"DMXAPI返回了无效 JSON，HTTP {status_code}。", details) from exc
    if not isinstance(response_payload, dict):
        details = config_guidance_details(
            ["dmxapi.api_key", "dmxapi.model"],
            "DMXAPI返回结构异常，请检查 API Key、模型 ID、权限或额度。",
        )
        details.update({"status_code": status_code, "payload": safe_value(response_payload)})
        raise ToolError("DMXAPI_INVALID_RESPONSE", "DMXAPI返回结构异常。", details)
    if status_code >= 400:
        error_payload = response_payload.get("error")
        message = str(error_payload.get("message") if isinstance(error_payload, dict) else response_payload.get("message") or text[:500])
        details = config_guidance_details(
            ["dmxapi.api_key", "dmxapi.model"],
            "DMXAPI接口请求失败，请检查 API Key 是否正确、是否过期、是否有权限或额度，模型 ID 是否可用。",
        )
        details.update({"status_code": status_code, "upstream_payload": safe_value(response_payload)})
        raise ToolError("DMXAPI_HTTP_ERROR", f"DMXAPI请求失败，HTTP {status_code}：{message}", details)
    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        details = config_guidance_details(
            ["dmxapi.api_key", "dmxapi.model"],
            "DMXAPI未返回可用结果，请检查模型是否支持视觉输入、账号是否有权限或额度。",
        )
        details.update({"status_code": status_code, "upstream_payload": safe_value(response_payload)})
        raise ToolError("DMXAPI_EMPTY_RESULT", "DMXAPI未返回可用结果。", details)
    message = choices[0].get("message") if isinstance(choices[0], dict) else {}
    content = message.get("content") if isinstance(message, dict) else ""
    if isinstance(content, list):
        text_parts = [str(item.get("text") or "") for item in content if isinstance(item, dict)]
        content = "\n".join(part for part in text_parts if part)
    content_text = str(content or "").strip()
    if not content_text:
        details = config_guidance_details(
            ["dmxapi.api_key", "dmxapi.model"],
            "DMXAPI返回空内容，请检查模型是否支持视觉输入、账号是否有权限或额度。",
        )
        details.update({"status_code": status_code, "upstream_payload": safe_value(response_payload)})
        raise ToolError("DMXAPI_EMPTY_CONTENT", "DMXAPI返回内容为空。", details)
    return {
        "content": content_text,
        "mime_type": mime_type,
        "usage": response_payload.get("usage") if isinstance(response_payload.get("usage"), dict) else None,
        "request_id": response_payload.get("id") or response_payload.get("request_id"),
    }


def output_dir_for_image(image_path: Path, options: Options) -> Path:
    if options.output_dir is not None:
        return options.output_dir
    if is_inside(image_path.parent, options.workspace_root):
        return image_path.parent
    return options.workspace_root


def allocate_output_path(image_path: Path, options: Options, allocated: set[str]) -> Path:
    out_dir = output_dir_for_image(image_path, options)
    ensure_inside(out_dir.resolve(strict=False), options.workspace_root, "OUTPUT_OUTSIDE_WORKSPACE", "保存目录必须在工作区内。")
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = sanitize_stem(image_path.stem)
    candidate = out_dir / f"{stem}.md"
    key = str(candidate.resolve(strict=False)).lower()
    if options.overwrite and key not in allocated:
        allocated.add(key)
        return candidate
    counter = 2
    while key in allocated or candidate.exists():
        candidate = out_dir / f"{stem}_{counter}.md"
        key = str(candidate.resolve(strict=False)).lower()
        counter += 1
    allocated.add(key)
    return candidate


def clip_content(content: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(content) <= max_chars:
        return content, False
    return f"{content[:max_chars]}\n\n...[内容已截断]", True


def analyze_one(
    item: dict[str, Any],
    config: ToolConfig,
    options: Options,
    allocated_paths: set[str],
    allocation_lock: threading.Lock,
) -> dict[str, Any]:
    image_path = item["path_obj"]
    try:
        api_result = call_vision_api(image_path, config, options)
        full_content = api_result["content"]
        saved_path = None
        if options.save_results:
            with allocation_lock:
                target_path = allocate_output_path(image_path, options, allocated_paths)
            target_path.write_text(full_content.rstrip() + "\n", encoding="utf-8")
            saved_path = str(target_path)
        returned_content, truncated = clip_content(full_content, options.max_return_chars_per_image)
        return {
            "ok": True,
            "index": item["index"],
            "input_path": item["input_path"],
            "image_path": item["image_path"],
            "relative_image_path": item["relative_image_path"],
            "size_bytes": item["size_bytes"],
            "mime_type": api_result["mime_type"],
            "model": config.model,
            "content": returned_content,
            "content_truncated": truncated,
            "full_content_chars": len(full_content),
            "saved_path": saved_path,
            "relative_saved_path": relative_or_absolute(Path(saved_path), options.workspace_root) if saved_path else None,
            "usage": api_result["usage"],
            "request_id": api_result["request_id"],
        }
    except ToolError as exc:
        return {
            "ok": False,
            "index": item["index"],
            "input_path": item["input_path"],
            "image_path": item["image_path"],
            "relative_image_path": item["relative_image_path"],
            "error": f"{exc.code}: {exc.message}",
            "error_info": {"code": exc.code, "message": exc.message, "details": exc.details},
        }
    except Exception as exc:
        return {
            "ok": False,
            "index": item["index"],
            "input_path": item["input_path"],
            "image_path": item["image_path"],
            "relative_image_path": item["relative_image_path"],
            "error": f"UNEXPECTED_ERROR: {str(exc) or exc.__class__.__name__}",
            "error_info": {"code": "UNEXPECTED_ERROR", "message": str(exc) or exc.__class__.__name__, "details": {}},
        }


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        options = prepare_options(payload)
        prepared = [validate_image_path(raw_path, index + 1, options) for index, raw_path in enumerate(options.image_paths)]
        valid_items = [item for item in prepared if item.get("ok")]
        results: list[dict[str, Any] | None] = [None] * len(prepared)
        for item in prepared:
            if not item.get("ok"):
                results[item["index"] - 1] = item
        warnings: list[str] = []
        if not valid_items:
            data = {
                "total": len(prepared),
                "success": 0,
                "failed": len(prepared),
                "results": [item for item in results if item is not None],
            }
            response = ok("没有可解析的有效图片。", data, warnings)
            response["ok"] = False
            response["error"] = "NO_VALID_IMAGES: 没有可解析的有效图片。"
            response["error_info"] = {"code": "NO_VALID_IMAGES", "message": "没有可解析的有效图片。", "details": {}}
            return response

        config = load_config()
        worker_count = max(1, min(options.concurrency, len(valid_items), 100))
        allocated_paths: set[str] = set()
        allocation_lock = threading.Lock()
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                executor.submit(analyze_one, item, config, options, allocated_paths, allocation_lock): item
                for item in valid_items
            }
            for future in as_completed(future_map):
                result = future.result()
                results[result["index"] - 1] = result
        final_results = [item for item in results if item is not None]
        success_count = sum(1 for item in final_results if item.get("ok"))
        failed_count = len(final_results) - success_count
        if failed_count:
            warnings.append(f"{failed_count} 张图片解析失败。")
        data = {
            "total": len(final_results),
            "success": success_count,
            "failed": failed_count,
            "model": config.model,
            "thinking_type": options.thinking_type,
            "saved": options.save_results,
            "concurrency": worker_count,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "results": final_results,
        }
        response = ok(f"豆包视觉解析完成：成功 {success_count} 张，失败 {failed_count} 张。", data, warnings)
        if success_count == 0:
            response["ok"] = False
            response["error"] = "VISION_ALL_FAILED: 全部图片解析失败。"
            response["error_info"] = {"code": "VISION_ALL_FAILED", "message": "全部图片解析失败。", "details": {"failed": failed_count}}
        return response
    except ToolError as exc:
        return fail(exc.code, exc.message, exc.details)
    except Exception as exc:
        return fail("UNEXPECTED_ERROR", str(exc) or exc.__class__.__name__)


if __name__ == "__main__":
    run_tool(run)
