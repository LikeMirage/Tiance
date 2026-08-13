from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import http.client
import io
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import time
from typing import Any
from urllib.parse import unquote, urlparse
from zipfile import ZipFile

from mineru_result_download import ResultDownloadError, download_result_bytes
from tiance_runtime import run_tool


CONFIG_PATH = Path(__file__).with_name("config.json")

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".html",
    ".htm",
    ".png",
    ".jpg",
    ".jpeg",
    ".jp2",
    ".webp",
    ".gif",
    ".bmp",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp"}
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)]\(([^)]+)\)")
MINERU_CONFIG_FIELDS = ["mineru.base_url", "mineru.api_key", "mineru.model_version", "mineru.html_model_version"]
DMXAPI_CONFIG_FIELDS = [
    "dmxapi.base_url",
    "dmxapi.api_key",
    "dmxapi.model",
    "dmxapi.temperature",
    "dmxapi.top_p",
    "dmxapi.max_output_tokens",
    "dmxapi.thinking.enabled",
    "dmxapi.thinking.type",
    "dmxapi.system_prompt",
    "dmxapi.user_prompt",
]
ALL_CONFIG_FIELDS = [*MINERU_CONFIG_FIELDS, *DMXAPI_CONFIG_FIELDS]
DMXAPI_THINKING_TYPES = {"disabled", "auto", "enabled"}
STRUCTURED_ARTIFACTS = (
    ("content_list_v2", "_content_list_v2.json", "content_list_v2.json"),
    ("content_list", "_content_list.json", "content_list.json"),
    ("middle", "_middle.json", "middle.json"),
    ("model", "_model.json", "model.json"),
)


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class ParseOptions:
    source_file: Path
    workspace_root: Path
    output_root: Path
    output_dir: Path
    overwrite: bool
    analyze_images: bool
    max_images: int
    image_concurrency: int
    parse_timeout_seconds: int
    poll_interval_seconds: int
    request_timeout_seconds: int
    vision_timeout_seconds: int


@dataclass(frozen=True)
class ToolConfig:
    mineru_base_url: str
    mineru_api_key: str
    mineru_model_version: str
    mineru_html_model_version: str
    dmxapi_base_url: str
    dmxapi_api_key: str
    dmxapi_model: str
    dmxapi_temperature: float | None
    dmxapi_top_p: float | None
    dmxapi_max_output_tokens: int | None
    dmxapi_thinking_enabled: bool | None
    dmxapi_thinking_type: str
    dmxapi_system_prompt: str
    dmxapi_user_prompt: str


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


def read_bool(value: Any, default: bool = False) -> bool:
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


def read_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return None


def read_optional_int(value: Any, minimum: int = 1) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= minimum else None


def read_optional_float(value: Any, minimum: float = 0) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= minimum else None


def read_prompt_text(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value).strip()
    return str(value or "").strip()


def resolve_path(value: Any, root: Path) -> Path:
    raw = str(value or "").strip()
    if not raw:
        return root
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve(strict=False)


def ensure_inside(path: Path, root: Path, code: str, message: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ToolError(code, message, {"path": str(path), "workspace_root": str(root)}) from exc


def sanitize_folder_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" .")
    return cleaned or "parsed_document"


def prepare_options(payload: dict[str, Any]) -> ParseOptions:
    root = workspace_root()
    file_path = payload.get("file_path")
    if not isinstance(file_path, str) or not file_path.strip():
        raise ToolError("INVALID_ARGUMENT", "file_path 必须是非空字符串。")

    source_file = resolve_path(file_path, root)
    allow_outside = read_bool(payload.get("allow_source_outside_workspace"), False)
    if not allow_outside:
        ensure_inside(source_file, root, "PATH_OUTSIDE_WORKSPACE", "源文件不在工作区内。")
    if not source_file.exists():
        raise ToolError("FILE_NOT_FOUND", "源文件不存在。", {"file_path": str(source_file)})
    if not source_file.is_file():
        raise ToolError("NOT_A_FILE", "file_path 必须指向文件。", {"file_path": str(source_file)})
    if source_file.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ToolError(
            "UNSUPPORTED_FILE_TYPE",
            "当前工具只支持 MinerU 可解析的文档和图片格式。",
            {"extension": source_file.suffix.lower(), "supported_extensions": sorted(SUPPORTED_EXTENSIONS)},
        )

    output_root = resolve_path(payload.get("output_root"), root)
    ensure_inside(output_root, root, "OUTPUT_OUTSIDE_WORKSPACE", "输出根目录必须在工作区内。")
    output_name = str(payload.get("output_folder_name") or "").strip()
    folder_name = sanitize_folder_name(output_name or source_file.stem)
    output_dir = (output_root / folder_name).resolve(strict=False)
    ensure_inside(output_dir, root, "OUTPUT_OUTSIDE_WORKSPACE", "输出目录必须在工作区内。")

    return ParseOptions(
        source_file=source_file,
        workspace_root=root,
        output_root=output_root,
        output_dir=output_dir,
        overwrite=read_bool(payload.get("overwrite"), False),
        analyze_images=read_bool(payload.get("analyze_images"), True),
        max_images=read_int(payload.get("max_images"), 50, 0, 200),
        image_concurrency=read_int(payload.get("image_concurrency"), 4, 1, 12),
        parse_timeout_seconds=read_int(payload.get("parse_timeout_seconds"), 1800, 60, 7200),
        poll_interval_seconds=read_int(payload.get("poll_interval_seconds"), 3, 1, 30),
        request_timeout_seconds=read_int(payload.get("request_timeout_seconds"), 60, 10, 300),
        vision_timeout_seconds=read_int(payload.get("vision_timeout_seconds"), 120, 10, 600),
    )


def default_config_payload() -> dict[str, Any]:
    return {
        "mineru": {
            "base_url": "https://mineru.net",
            "api_key": "",
            "model_version": "pipeline",
            "html_model_version": "MinerU-HTML",
        },
        "dmxapi": {
            "base_url": "https://www.dmxapi.cn/v1",
            "api_key": "",
            "model": "doubao-seed-1-6-flash-250828",
            "temperature": 0.1,
            "top_p": 1,
            "max_output_tokens": 1200,
            "thinking": {
                "enabled": False,
                "type": "disabled",
            },
            "system_prompt": [
                "你是文档视觉补全助手，用于补充 MinerU 文档解析结果中图片、截图、表格图、流程图、公式图等无法直接还原的内容。",
                "",
                "你的任务不是写作、总结、分析论文，也不是自由发挥；你的任务是把当前图片中真实可见的信息还原成一段可直接插入 Markdown 文档的内容。",
                "",
                "通用规则：",
                "1. 只输出 Markdown 片段，不要输出“图片解析”“以下是”等外层标题。",
                "2. 只描述图片中真实可见的信息，不添加趋势、结论、应用场景、论文写作建议、主观评价或延伸分析。",
                "3. 如果内容无法可靠识别，明确写“无法可靠识别：xxx”，不要猜测。",
                "4. 保持原图信息结构，优先还原原始标题、层级、顺序、字段、编号、单位。",
                "5. 如果图片中有文字，尽量逐字转录；标点、数字、单位、专有名词要保持原样。",
                "6. 如果图片只是一张普通插图或照片，简洁描述关键对象、位置关系、可见文字和图中表达的信息。",
                "",
                "按图片类型处理：",
                "- 表格或表格截图：优先输出 Markdown 表格。只保留表头和单元格内容，不额外解释表格含义。若部分单元格看不清，用“无法识别”占位。",
                "- 流程图、结构图、架构图：用分层列表还原节点、箭头方向、上下级关系和可见文字。",
                "- 图表、柱状图、折线图、饼图：先列出图表标题、坐标轴/图例/单位，再列出能读出的关键数值或趋势；不能读准数值时不要编造。",
                "- 公式或数学内容：尽量用 LaTeX/Markdown 还原；看不清的部分标注“无法识别”。",
                "- 页面截图、软件截图：描述界面区域、按钮、表单、状态、可见文字和它们的位置关系。",
                "- 印章、签名、水印、页眉页脚：如能看到，简洁记录其内容和位置。",
                "",
                "输出格式要求：",
                "- 表格：直接输出 Markdown 表格。",
                "- 流程/结构：使用项目符号或编号列表。",
                "- 普通图片：使用 2-5 条简短要点。",
                "- 不要生成长篇解释。",
                "- 不要把一个表格扩写成段落分析。",
                "- 不要输出与图片无关的内容。"
            ],
            "user_prompt": "请根据图片内容，按系统规则输出可直接插入原 Markdown 文档当前位置的片段。",
        },
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
            "请指导用户获取缺失配置。用户提供后，使用文件编辑能力修改 config_path 指向的 JSON 文件；"
            "不要在最终回复中回显密钥原文。"
        ),
        "expected_config": default_config_payload(),
    }


def load_tool_config() -> ToolConfig:
    ensure_config_file_exists()
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        details = config_guidance_details(
            ALL_CONFIG_FIELDS,
            "请修复配置文件 JSON 格式。",
        )
        details["parse_error"] = str(exc)
        raise ToolError(
            "CONFIG_INVALID",
            "工具配置文件不是有效 JSON。",
            details,
        ) from exc
    if not isinstance(payload, dict):
        raise ToolError(
            "CONFIG_INVALID",
            "工具配置文件根节点必须是 JSON 对象。",
            config_guidance_details(
                ALL_CONFIG_FIELDS,
                "请按 expected_config 重写配置文件。",
            ),
        )

    mineru = payload.get("mineru") if isinstance(payload.get("mineru"), dict) else {}
    dmxapi = payload.get("dmxapi") if isinstance(payload.get("dmxapi"), dict) else {}
    thinking = dmxapi.get("thinking") if isinstance(dmxapi.get("thinking"), dict) else {}
    return ToolConfig(
        mineru_base_url=str(mineru.get("base_url") or "").strip(),
        mineru_api_key=str(mineru.get("api_key") or "").strip(),
        mineru_model_version=str(mineru.get("model_version") or "").strip(),
        mineru_html_model_version=str(mineru.get("html_model_version") or "").strip(),
        dmxapi_base_url=str(dmxapi.get("base_url") or "").strip(),
        dmxapi_api_key=str(dmxapi.get("api_key") or "").strip(),
        dmxapi_model=str(dmxapi.get("model") or "").strip(),
        dmxapi_temperature=read_optional_float(dmxapi.get("temperature")),
        dmxapi_top_p=read_optional_float(dmxapi.get("top_p")),
        dmxapi_max_output_tokens=read_optional_int(dmxapi.get("max_output_tokens")),
        dmxapi_thinking_enabled=read_optional_bool(thinking.get("enabled")),
        dmxapi_thinking_type=str(thinking.get("type") or "").strip(),
        dmxapi_system_prompt=read_prompt_text(dmxapi.get("system_prompt")),
        dmxapi_user_prompt=read_prompt_text(dmxapi.get("user_prompt")),
    )


def ensure_tool_config(options: ParseOptions) -> ToolConfig:
    config = load_tool_config()
    missing: list[str] = []
    if not config.mineru_base_url:
        missing.append("mineru.base_url")
    if not config.mineru_api_key:
        missing.append("mineru.api_key")
    if not config.mineru_model_version:
        missing.append("mineru.model_version")
    if options.source_file.suffix.lower() in {".html", ".htm"} and not config.mineru_html_model_version:
        missing.append("mineru.html_model_version")
    if options.analyze_images:
        if not config.dmxapi_base_url:
            missing.append("dmxapi.base_url")
        if not config.dmxapi_api_key:
            missing.append("dmxapi.api_key")
        if not config.dmxapi_model:
            missing.append("dmxapi.model")
        if config.dmxapi_temperature is None:
            missing.append("dmxapi.temperature")
        if config.dmxapi_top_p is None:
            missing.append("dmxapi.top_p")
        if config.dmxapi_max_output_tokens is None:
            missing.append("dmxapi.max_output_tokens")
        if config.dmxapi_thinking_enabled is None:
            missing.append("dmxapi.thinking.enabled")
        if config.dmxapi_thinking_enabled and not config.dmxapi_thinking_type:
            missing.append("dmxapi.thinking.type")
        if not config.dmxapi_system_prompt:
            missing.append("dmxapi.system_prompt")
        if not config.dmxapi_user_prompt:
            missing.append("dmxapi.user_prompt")
    if missing:
        raise ToolError(
            "CONFIG_MISSING",
            "工具运行配置不完整。",
            config_guidance_details(
                missing,
                "请让用户提供缺失配置，然后修改配置文件后重试本工具。",
            ),
        )
    if (
        options.analyze_images
        and config.dmxapi_thinking_enabled
        and config.dmxapi_thinking_type not in DMXAPI_THINKING_TYPES
    ):
        raise ToolError(
            "CONFIG_INVALID",
            "dmxapi.thinking.type 只能是 disabled、auto 或 enabled。",
            config_guidance_details(
                ["dmxapi.thinking.type"],
                "请把 dmxapi.thinking.type 改为 disabled、auto 或 enabled。",
            ),
        )
    return config


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def update_status(output_dir: Path, step: str, message: str, extra: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {
        "step": step,
        "message": message,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        payload.update(extra)
    write_json(output_dir / "status.json", payload)


def append_log(output_dir: Path, message: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {message}\n"
    with (output_dir / "run.log").open("a", encoding="utf-8") as handle:
        handle.write(line)


def prepare_output_dir(options: ParseOptions) -> str | None:
    options.output_root.mkdir(parents=True, exist_ok=True)
    backup_dir: str | None = None
    if options.output_dir.exists():
        if not options.overwrite:
            raise ToolError(
                "OUTPUT_EXISTS",
                "结果文件夹已存在；如需重新生成请传 overwrite=true。",
                {"output_dir": str(options.output_dir)},
            )
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = options.output_dir.with_name(f"{options.output_dir.name}.__backup_{stamp}")
        counter = 2
        while backup_path.exists():
            backup_path = options.output_dir.with_name(f"{options.output_dir.name}.__backup_{stamp}_{counter}")
            counter += 1
        shutil.move(str(options.output_dir), str(backup_path))
        backup_dir = str(backup_path)
    options.output_dir.mkdir(parents=True, exist_ok=False)
    (options.output_dir / "source").mkdir(parents=True, exist_ok=True)
    (options.output_dir / "mineru_extracted").mkdir(parents=True, exist_ok=True)
    (options.output_dir / "images").mkdir(parents=True, exist_ok=True)
    return backup_dir


def model_version_for(source_file: Path, config: ToolConfig) -> str:
    if source_file.suffix.lower() in {".html", ".htm"}:
        return config.mineru_html_model_version
    return config.mineru_model_version


def mineru_headers(config: ToolConfig) -> dict[str, str]:
    return {"Authorization": f"Bearer {config.mineru_api_key}", "Content-Type": "application/json"}


def post_json(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: int, service_name: str) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    status_code, text = http_request("POST", url, headers=headers, body=body, timeout=timeout, service_name=service_name)
    return parse_api_json(status_code, text, service_name)


def get_json(url: str, headers: dict[str, str], timeout: int, service_name: str) -> dict[str, Any]:
    status_code, text = http_request("GET", url, headers=headers, body=None, timeout=timeout, service_name=service_name)
    return parse_api_json(status_code, text, service_name)


def http_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: bytes | None,
    timeout: int,
    service_name: str,
) -> tuple[int, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolError("INVALID_URL", f"{service_name} 请求地址无效。", {"url": url})
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
        details: dict[str, Any] = {}
        if service_name == "MinerU":
            details.update(
                config_guidance_details(
                    MINERU_CONFIG_FIELDS,
                    "MinerU 接口连接失败；如果网络正常，请检查配置文件中的 MinerU API Key。",
                )
            )
        elif service_name == "DMXAPI":
            details.update(
                config_guidance_details(
                    DMXAPI_CONFIG_FIELDS,
                    "DMXAPI接口连接失败；如果网络正常，请检查配置文件中的 API Key 和模型 ID。",
                )
            )
        raise ToolError("HTTP_REQUEST_FAILED", f"请求 {service_name} 失败：{exc}", details) from exc


def parse_api_json(status_code: int, text: str, service_name: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise ToolError(
            "INVALID_JSON",
            f"{service_name} 返回了无效 JSON，HTTP {status_code}。",
            {"status_code": status_code, "text_preview": text[:500]},
        ) from exc
    if not isinstance(payload, dict):
        raise ToolError("INVALID_RESPONSE", f"{service_name} 返回结构异常。", {"status_code": status_code})
    if status_code >= 400:
        message = str(payload.get("msg") or payload.get("message") or payload.get("detail") or text[:500])
        details: dict[str, Any] = {"status_code": status_code}
        if service_name == "MinerU":
            details.update(
                config_guidance_details(
                    MINERU_CONFIG_FIELDS,
                    "MinerU 接口请求失败，请检查配置文件中的 MinerU API Key 是否正确、是否过期或额度是否可用。",
                )
            )
        raise ToolError("HTTP_ERROR", f"{service_name} 请求失败，HTTP {status_code}：{message}", details)
    if payload.get("code") not in (None, 0):
        message = str(payload.get("msg") or payload.get("message") or payload.get("detail") or f"{service_name} 返回错误。")
        details = {"service": service_name, "payload": safe_payload(payload)}
        if service_name == "MinerU":
            details.update(
                config_guidance_details(
                    MINERU_CONFIG_FIELDS,
                    "MinerU 返回业务错误，请检查配置文件中的 MinerU API Key、账号额度和文件限制。",
                )
            )
        raise ToolError("SERVICE_ERROR", message, details)
    return payload


def safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    copied = dict(payload)
    for key in list(copied.keys()):
        if "token" in key.lower() or "key" in key.lower() or "authorization" in key.lower():
            copied[key] = "***"
    return copied


def submit_mineru_task(options: ParseOptions, config: ToolConfig) -> tuple[str, str, str, str]:
    model_version = model_version_for(options.source_file, config)
    data_id = f"tiance-{int(time.time())}-{os.urandom(4).hex()}"
    payload = {"files": [{"name": options.source_file.name, "data_id": data_id}], "model_version": model_version}
    url = f"{config.mineru_base_url.rstrip('/')}/api/v4/file-urls/batch"
    response_payload = post_json(url, mineru_headers(config), payload, options.request_timeout_seconds, "MinerU")
    data = response_payload.get("data") if isinstance(response_payload.get("data"), dict) else {}
    task_ref = str(data.get("batch_id") or "").strip()
    file_urls = data.get("file_urls") if isinstance(data.get("file_urls"), list) else []
    upload_url = str(file_urls[0] if file_urls else "").strip()
    if not task_ref or not upload_url:
        raise ToolError("MINERU_INVALID_TASK", "MinerU 未返回有效任务信息。", {"payload": safe_payload(response_payload)})
    return task_ref, upload_url, data_id, model_version


def upload_to_mineru(upload_url: str, source_file: Path, timeout: int) -> None:
    parsed = urlparse(upload_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolError("MINERU_UPLOAD_FAILED", "MinerU 上传地址无效。")
    connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    try:
        connection = connection_cls(parsed.netloc, timeout=timeout)
        connection.putrequest("PUT", path)
        connection.putheader("Content-Length", str(source_file.stat().st_size))
        connection.endheaders()
        with source_file.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                connection.send(chunk)
        response = connection.getresponse()
        try:
            if response.status not in {200, 201}:
                raise ToolError("MINERU_UPLOAD_FAILED", f"上传文件到 MinerU 失败，HTTP {response.status}。")
        finally:
            response.close()
            connection.close()
    except ToolError:
        raise
    except OSError as exc:
        raise ToolError("MINERU_UPLOAD_FAILED", f"上传文件到 MinerU 失败：{exc}") from exc


def poll_mineru_result(options: ParseOptions, task_ref: str, data_id: str, config: ToolConfig) -> tuple[str, dict[str, Any]]:
    deadline = time.monotonic() + options.parse_timeout_seconds
    status_url = f"{config.mineru_base_url.rstrip('/')}/api/v4/extract-results/batch/{task_ref}"
    last_payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        payload = get_json(status_url, mineru_headers(config), options.request_timeout_seconds, "MinerU")
        last_payload = payload
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        results = data.get("extract_result") if isinstance(data.get("extract_result"), list) else []
        match = match_mineru_result(results, data_id=data_id, file_name=options.source_file.name)
        if not match:
            time.sleep(options.poll_interval_seconds)
            continue
        state = str(match.get("state") or "").strip().lower()
        progress = match.get("extract_progress") if isinstance(match.get("extract_progress"), dict) else {}
        if state == "done":
            result_url = str(match.get("full_zip_url") or "").strip()
            if not result_url:
                raise ToolError("MINERU_RESULT_MISSING", "MinerU 完成但未返回 full_zip_url。", {"status": match})
            return result_url, match
        if state in {"failed", "error"}:
            message = str(match.get("err_msg") or match.get("message") or "MinerU 解析失败。")
            raise ToolError("MINERU_PARSE_FAILED", message, {"status": match})
        extracted = progress.get("extracted_pages")
        total = progress.get("total_pages")
        update_status(
            options.output_dir,
            "mineru_polling",
            f"MinerU 解析中：{extracted or 0}/{total or '?'} 页",
            {"task_ref": task_ref, "state": state},
        )
        time.sleep(options.poll_interval_seconds)
    raise ToolError("MINERU_TIMEOUT", "MinerU 解析超时。", {"last_payload": safe_payload(last_payload)})


def match_mineru_result(results: list[Any], data_id: str, file_name: str) -> dict[str, Any] | None:
    dict_items = [item for item in results if isinstance(item, dict)]
    for item in dict_items:
        if str(item.get("data_id") or "") == data_id:
            return item
    for item in dict_items:
        if str(item.get("file_name") or item.get("name") or "") == file_name:
            return item
    return dict_items[0] if dict_items else None


def extract_zip_safely(zip_bytes: bytes, target_root: Path) -> list[str]:
    extracted: list[str] = []
    with ZipFile(io.BytesIO(zip_bytes)) as archive:
        for member in archive.infolist():
            member_path = PurePosixPath(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ToolError("UNSAFE_ZIP_ENTRY", "解析结果压缩包包含不安全路径。", {"entry": member.filename})
            target = (target_root / Path(*member_path.parts)).resolve(strict=False)
            ensure_inside(target, target_root.resolve(strict=False), "UNSAFE_ZIP_ENTRY", "解析结果压缩包包含越界路径。")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as dest:
                shutil.copyfileobj(source, dest)
            extracted.append(str(target.relative_to(target_root).as_posix()))
    return extracted


def find_artifact(root: Path, filename_hint: str) -> Path | None:
    lowered = filename_hint.lower()
    for path in root.rglob("*"):
        if path.is_file() and path.name.lower() == lowered:
            return path
    return None


def find_artifact_by_suffix(root: Path, filename_suffix: str) -> Path | None:
    lowered = filename_suffix.lower()
    candidates = sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and path.name.lower().endswith(lowered)
        ),
        key=lambda path: path.relative_to(root).as_posix().lower(),
    )
    return candidates[0] if candidates else None


def preserve_structured_artifacts(extracted_root: Path, output_dir: Path) -> dict[str, Path]:
    preserved: dict[str, Path] = {}
    structure_dir = output_dir / "structure"
    for key, source_suffix, output_name in STRUCTURED_ARTIFACTS:
        source_path = find_artifact_by_suffix(extracted_root, source_suffix)
        if source_path is None:
            continue
        structure_dir.mkdir(parents=True, exist_ok=True)
        destination = structure_dir / output_name
        shutil.copy2(source_path, destination)
        preserved[key] = destination
    return preserved


def read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def markdown_to_plain_text(markdown: str) -> str:
    text = re.sub(r"```.*?```", "", markdown, flags=re.S)
    text = re.sub(r"!\[[^\]]*]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)]\([^)]*\)", r"\1", text)
    text = re.sub(r"[#>*_`~|-]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def discover_all_images(root: Path) -> list[Path]:
    images = [path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS]
    return sorted(images, key=lambda item: item.relative_to(root).as_posix().lower())


def discover_images(root: Path, limit: int, relative_paths: list[str] | None = None) -> tuple[list[Path], bool]:
    if relative_paths is None:
        images = discover_all_images(root)
    else:
        images = resolve_relative_image_paths(root, relative_paths)
    return images[:limit], len(images) > limit


def analyze_images(
    options: ParseOptions,
    extracted_root: Path,
    warnings: list[str],
    config: ToolConfig,
    relative_paths: list[str],
) -> list[dict[str, Any]]:
    if not options.analyze_images or options.max_images <= 0:
        return []
    images, truncated = discover_images(extracted_root, options.max_images, relative_paths)
    if truncated:
        warnings.append(f"正文图片数量超过 max_images={options.max_images}，只分析前 {options.max_images} 张。")
    if not images:
        return []
    worker_count = max(1, min(options.image_concurrency, len(images)))
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {
            executor.submit(analyze_single_image, image_path, extracted_root, options.vision_timeout_seconds, config): image_path
            for image_path in images
        }
        completed = 0
        for future in as_completed(future_map):
            image_path = future_map[future]
            completed += 1
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "ok": False,
                    "image_path": image_path.relative_to(extracted_root).as_posix(),
                    "error": str(exc) or exc.__class__.__name__,
                }
                warnings.append(f"图片分析失败：{result['image_path']}：{result['error']}")
            results.append(result)
            update_status(
                options.output_dir,
                "vision_analysis",
                f"图片分析中：{completed}/{len(images)}",
                {"completed": completed, "total": len(images)},
            )
    return sorted(results, key=lambda item: str(item.get("image_path") or ""))


def analyze_single_image(image_path: Path, extracted_root: Path, timeout: int, config: ToolConfig) -> dict[str, Any]:
    stat = image_path.stat()
    relative_path = image_path.relative_to(extracted_root).as_posix()
    if stat.st_size > MAX_IMAGE_BYTES:
        return {
            "ok": False,
            "image_path": relative_path,
            "size_bytes": stat.st_size,
            "error": f"图片超过 {MAX_IMAGE_BYTES} 字节，已跳过。",
        }
    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/png"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    data_url = f"data:{mime_type};base64,{encoded}"
    payload = {
        "model": config.dmxapi_model,
        "messages": [
            {
                "role": "system",
                "content": config.dmxapi_system_prompt,
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": config.dmxapi_user_prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
    }
    if config.dmxapi_temperature is not None:
        payload["temperature"] = config.dmxapi_temperature
    if config.dmxapi_top_p is not None:
        payload["top_p"] = config.dmxapi_top_p
    if config.dmxapi_max_output_tokens is not None:
        payload["max_completion_tokens"] = config.dmxapi_max_output_tokens
    if config.dmxapi_thinking_enabled:
        payload["thinking"] = {"type": config.dmxapi_thinking_type}
    headers = {"Authorization": f"Bearer {config.dmxapi_api_key}", "Content-Type": "application/json"}
    url = f"{config.dmxapi_base_url.rstrip('/')}/chat/completions"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    status_code, text = http_request("POST", url, headers=headers, body=body, timeout=timeout, service_name="DMXAPI")
    try:
        response_payload = json.loads(text)
    except ValueError as exc:
        raise ToolError(
            "DMXAPI_INVALID_JSON",
            f"DMXAPI返回了无效 JSON，HTTP {status_code}。",
            config_guidance_details(
                DMXAPI_CONFIG_FIELDS,
                "DMXAPI返回异常，请检查配置文件中的 API Key 和模型 ID，或稍后重试。",
            ),
        ) from exc
    if not isinstance(response_payload, dict):
        raise ToolError(
            "DMXAPI_INVALID_RESPONSE",
            "DMXAPI返回结构异常。",
            config_guidance_details(
                DMXAPI_CONFIG_FIELDS,
                "DMXAPI返回结构异常，请检查配置文件中的 API Key 和模型 ID，或稍后重试。",
            ),
        )
    if status_code >= 400:
        error_payload = response_payload.get("error")
        message = str(error_payload.get("message") if isinstance(error_payload, dict) else response_payload.get("message") or text[:500])
        raise ToolError(
            "DMXAPI_HTTP_ERROR",
            f"DMXAPI请求失败，HTTP {status_code}：{message}",
            config_guidance_details(
                DMXAPI_CONFIG_FIELDS,
                "DMXAPI接口请求失败，请检查配置文件中的 API Key 和模型 ID 是否正确、是否有权限或额度。",
            ),
        )
    choices = response_payload.get("choices") if isinstance(response_payload, dict) else None
    if not isinstance(choices, list) or not choices:
        details = {"payload": safe_payload(response_payload)}
        details.update(
            config_guidance_details(
                DMXAPI_CONFIG_FIELDS,
                "DMXAPI未返回可用结果，请检查模型 ID 是否支持视觉输入、账号是否有权限或额度。",
            )
        )
        raise ToolError("DMXAPI_EMPTY_RESULT", "DMXAPI未返回可用结果。", details)
    message = choices[0].get("message") if isinstance(choices[0], dict) else {}
    content = message.get("content") if isinstance(message, dict) else ""
    if isinstance(content, list):
        text_parts = [str(item.get("text") or "") for item in content if isinstance(item, dict)]
        content = "\n".join(part for part in text_parts if part)
    content_text = str(content or "").strip()
    if not content_text:
        raise ToolError(
            "DMXAPI_EMPTY_CONTENT",
            "DMXAPI返回内容为空。",
            config_guidance_details(
                DMXAPI_CONFIG_FIELDS,
                "DMXAPI返回空内容，请检查模型 ID 是否支持视觉输入，或换一个可用模型。",
            ),
        )
    return {
        "ok": True,
        "image_path": relative_path,
        "size_bytes": stat.st_size,
        "mime_type": mime_type,
        "model": config.dmxapi_model,
        "analysis": content_text,
        "usage": response_payload.get("usage") if isinstance(response_payload.get("usage"), dict) else None,
    }


def safe_image_filename(name: str, fallback: str) -> str:
    path = Path(str(name or ""))
    stem = sanitize_folder_name(path.stem or fallback)
    suffix = path.suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        suffix = ".png"
    return f"{stem}{suffix}"


def unique_filename(name: str, used_names: set[str]) -> str:
    path = Path(name)
    stem = path.stem
    suffix = path.suffix
    candidate = f"{stem}{suffix}"
    counter = 2
    while candidate.lower() in used_names:
        candidate = f"{stem}_{counter}{suffix}"
        counter += 1
    used_names.add(candidate.lower())
    return candidate


def copy_images_to_output(extracted_root: Path, output_images_dir: Path, relative_paths: list[str]) -> dict[str, str]:
    output_images_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    used_names: set[str] = set()
    for index, image_path in enumerate(resolve_relative_image_paths(extracted_root, relative_paths), start=1):
        relative_path = image_path.relative_to(extracted_root).as_posix()
        file_name = unique_filename(safe_image_filename(image_path.name, f"image_{index}"), used_names)
        target = output_images_dir / file_name
        shutil.copy2(image_path, target)
        mapping[relative_path] = f"images/{file_name}"
    return mapping


def normalize_markdown_image_reference(
    source_markdown_path: Path,
    extracted_root: Path,
    reference: str,
) -> str | None:
    raw_reference = str(reference or "").strip()
    if raw_reference.startswith("<") and raw_reference.endswith(">"):
        raw_reference = raw_reference[1:-1].strip()
    if not raw_reference:
        return None

    parsed = urlparse(raw_reference)
    if parsed.scheme or parsed.netloc:
        return None

    decoded_path = unquote(parsed.path or raw_reference).replace("\\", "/").strip()
    if not decoded_path or decoded_path.startswith("#"):
        return None

    candidate_paths: list[Path] = []
    raw_path = Path(decoded_path)
    if raw_path.is_absolute():
        candidate_paths.append(raw_path)
    else:
        candidate_paths.append(source_markdown_path.parent / raw_path)
        candidate_paths.append(extracted_root / raw_path)

    resolved_root = extracted_root.resolve(strict=False)
    for candidate in candidate_paths:
        resolved = candidate.resolve(strict=False)
        try:
            relative_path = resolved.relative_to(resolved_root).as_posix()
        except ValueError:
            continue
        if resolved.exists() and resolved.is_file():
            return relative_path
    return decoded_path


def collect_markdown_image_references(markdown: str, source_markdown_path: Path, extracted_root: Path) -> list[str]:
    references: list[str] = []
    seen: set[str] = set()
    for match in MARKDOWN_IMAGE_PATTERN.finditer(markdown):
        normalized_path = normalize_markdown_image_reference(source_markdown_path, extracted_root, match.group(2))
        if not normalized_path or normalized_path in seen:
            continue
        candidate = (extracted_root / normalized_path).resolve(strict=False)
        try:
            candidate.relative_to(extracted_root.resolve(strict=False))
        except ValueError:
            continue
        if candidate.exists() and candidate.is_file() and candidate.suffix.lower() in IMAGE_EXTENSIONS:
            references.append(normalized_path)
            seen.add(normalized_path)
    return references


def resolve_relative_image_paths(root: Path, relative_paths: list[str]) -> list[Path]:
    resolved_root = root.resolve(strict=False)
    images: list[Path] = []
    seen: set[str] = set()
    for relative_path in relative_paths:
        candidate = (root / relative_path).resolve(strict=False)
        try:
            normalized = candidate.relative_to(resolved_root).as_posix()
        except ValueError:
            continue
        if normalized in seen:
            continue
        if candidate.exists() and candidate.is_file() and candidate.suffix.lower() in IMAGE_EXTENSIONS:
            images.append(candidate)
            seen.add(normalized)
    return images


def build_image_analysis_block(item: dict[str, Any] | None) -> str:
    if not item:
        return ""
    if item.get("ok"):
        content = str(item.get("analysis") or "").strip()
    else:
        content = f"图片分析失败：{item.get('error') or '未知错误'}"
    if not content:
        return ""
    return f"\n\n**视觉解析：**\n\n{content.strip()}\n"


def build_vision_markdown(
    markdown: str,
    image_results: list[dict[str, Any]],
    source_markdown_path: Path,
    extracted_root: Path,
    image_link_mapping: dict[str, str],
) -> str:
    image_results_by_path = {
        str(item.get("image_path") or ""): item
        for item in image_results
        if str(item.get("image_path") or "")
    }
    output_parts: list[str] = []
    cursor = 0
    for match in MARKDOWN_IMAGE_PATTERN.finditer(markdown):
        output_parts.append(markdown[cursor:match.start()])
        alt_text = match.group(1)
        reference = match.group(2)
        normalized_path = normalize_markdown_image_reference(source_markdown_path, extracted_root, reference)
        link_path = image_link_mapping.get(normalized_path or "")
        if link_path:
            output_parts.append(f"![{alt_text}]({link_path})")
        else:
            output_parts.append(match.group(0))
        output_parts.append(build_image_analysis_block(image_results_by_path.get(normalized_path or "")))
        cursor = match.end()

    output_parts.append(markdown[cursor:])
    return "".join(output_parts).rstrip() + "\n"


def relative_or_absolute(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def cleanup_success_outputs(options: ParseOptions, files: list[Path | None], dirs: list[Path], warnings: list[str]) -> None:
    for file_path in files:
        if file_path is None:
            continue
        try:
            if file_path.exists() and file_path.is_file():
                file_path.unlink()
        except OSError as exc:
            warnings.append(f"清理中间文件失败：{relative_or_absolute(file_path, options.workspace_root)}：{exc}")

    for dir_path in dirs:
        try:
            if dir_path.exists() and dir_path.is_dir():
                shutil.rmtree(dir_path)
        except OSError as exc:
            warnings.append(f"清理中间目录失败：{relative_or_absolute(dir_path, options.workspace_root)}：{exc}")


def run(payload: dict[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    try:
        options = prepare_options(payload)
        config = ensure_tool_config(options)
        backup_dir = prepare_output_dir(options)
        update_status(options.output_dir, "started", "开始文档解析")
        append_log(options.output_dir, f"source={options.source_file}")

        copied_source = options.output_dir / "source" / options.source_file.name
        shutil.copy2(options.source_file, copied_source)

        update_status(options.output_dir, "mineru_submit", "向 MinerU 申请上传地址")
        task_ref, upload_url, data_id, model_version = submit_mineru_task(options, config)
        append_log(options.output_dir, f"mineru_task_ref={task_ref}")

        update_status(options.output_dir, "mineru_upload", "上传源文件到 MinerU", {"task_ref": task_ref})
        upload_to_mineru(upload_url, options.source_file, options.request_timeout_seconds)

        update_status(options.output_dir, "mineru_polling", "等待 MinerU 解析完成", {"task_ref": task_ref})
        result_url, mineru_status = poll_mineru_result(options, task_ref, data_id, config)
        append_log(options.output_dir, f"mineru_result_host={urlparse(result_url).hostname or 'unknown'}")

        update_status(options.output_dir, "mineru_download", "下载 MinerU 结果包", {"task_ref": task_ref})
        try:
            zip_bytes = download_result_bytes(result_url, options.request_timeout_seconds)
        except ResultDownloadError as exc:
            raise ToolError(exc.code, exc.message, exc.details) from exc
        zip_path = options.output_dir / "mineru_result.zip"
        zip_path.write_bytes(zip_bytes)

        extracted_root = options.output_dir / "mineru_extracted"
        extracted_files = extract_zip_safely(zip_bytes, extracted_root)
        full_md_path = find_artifact(extracted_root, "full.md")
        if full_md_path is None:
            raise ToolError("FULL_MARKDOWN_MISSING", "MinerU 解析结果中未找到 full.md。", {"extracted_files": extracted_files[:200]})
        markdown = full_md_path.read_text(encoding="utf-8", errors="replace")
        referenced_image_paths = collect_markdown_image_references(markdown, full_md_path, extracted_root)
        raw_markdown_path = options.output_dir / "full.md"
        raw_markdown_path.write_text(markdown, encoding="utf-8")

        structured_artifacts = preserve_structured_artifacts(extracted_root, options.output_dir)

        update_status(options.output_dir, "vision_analysis", "分析解析结果中的图片")
        image_results = analyze_images(options, extracted_root, warnings, config, referenced_image_paths)
        image_analysis_path = options.output_dir / "image_analysis.json"
        write_json(image_analysis_path, image_results)

        image_dir = options.output_dir / "images"
        image_link_mapping = copy_images_to_output(extracted_root, image_dir, referenced_image_paths)
        document_markdown = build_vision_markdown(markdown, image_results, full_md_path, extracted_root, image_link_mapping)
        document_markdown_path = options.output_dir / f"{sanitize_folder_name(options.source_file.stem)}.md"
        document_markdown_path.write_text(document_markdown, encoding="utf-8")

        plain_text = markdown_to_plain_text(document_markdown)
        plain_text_path = options.output_dir / "plain_text.txt"
        plain_text_path.write_text(plain_text, encoding="utf-8")

        metadata = {
            "schema_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_file": str(options.source_file),
            "copied_source": str(copied_source),
            "workspace_root": str(options.workspace_root),
            "output_dir": str(options.output_dir),
            "backup_dir": backup_dir,
            "mineru": {
                "base_url": config.mineru_base_url,
                "model_version": model_version,
                "task_ref": task_ref,
                "data_id": data_id,
                "status": mineru_status,
            },
            "dmxapi": {
                "base_url": config.dmxapi_base_url,
                "model": config.dmxapi_model,
                "temperature": config.dmxapi_temperature,
                "top_p": config.dmxapi_top_p,
                "max_output_tokens": config.dmxapi_max_output_tokens,
                "thinking": {
                    "enabled": config.dmxapi_thinking_enabled,
                    "type": config.dmxapi_thinking_type,
                },
                "analyze_images": options.analyze_images,
                "referenced_image_count": len(referenced_image_paths),
                "image_count": len(image_results),
                "image_success_count": sum(1 for item in image_results if item.get("ok")),
                "image_failed_count": sum(1 for item in image_results if not item.get("ok")),
            },
            "files": {
                "main_markdown": str(document_markdown_path),
                "vision_markdown": str(document_markdown_path),
                "image_dir": str(image_dir),
                "structure_dir": str(options.output_dir / "structure") if structured_artifacts else None,
                "structured_data": {key: str(path) for key, path in structured_artifacts.items()},
            },
            "page_location": {
                "field": "page_idx",
                "index_base": 0,
                "display_page_formula": "page_idx + 1",
                "preferred_file": str(
                    structured_artifacts.get("content_list_v2")
                    or structured_artifacts.get("content_list")
                    or ""
                ) or None,
            },
        }
        metadata_path = options.output_dir / "metadata.json"
        write_json(metadata_path, metadata)
        update_status(options.output_dir, "done", "文档解析完成", {"task_ref": task_ref})

        cleanup_success_outputs(
            options,
            [
                raw_markdown_path,
                plain_text_path,
                image_analysis_path,
                zip_path,
                options.output_dir / "status.json",
                options.output_dir / "run.log",
            ],
            [extracted_root, options.output_dir / "source"],
            warnings,
        )

        data = {
            "output_dir": str(options.output_dir),
            "backup_dir": backup_dir,
            "source_file": str(options.source_file),
            "main_markdown": str(document_markdown_path),
            "vision_markdown": str(document_markdown_path),
            "image_dir": str(image_dir),
            "metadata_path": str(metadata_path),
            "structure_dir": str(options.output_dir / "structure") if structured_artifacts else None,
            "structured_data": {
                **{key: str(path) for key, path in structured_artifacts.items()},
                "page_index_field": "page_idx",
                "page_index_base": 0,
                "display_page_formula": "page_idx + 1",
            },
            "relative_output_dir": relative_or_absolute(options.output_dir, options.workspace_root),
            "mineru": {
                "task_ref": task_ref,
                "data_id": data_id,
                "model_version": model_version,
            },
            "image_analysis": {
                "total": len(image_results),
                "success": sum(1 for item in image_results if item.get("ok")),
                "failed": sum(1 for item in image_results if not item.get("ok")),
            },
        }
        return ok(f"文档解析完成：{options.output_dir.name}", data, warnings)
    except ToolError as exc:
        return fail(exc.code, exc.message, exc.details)
    except Exception as exc:
        return fail("UNEXPECTED_ERROR", str(exc) or exc.__class__.__name__)


if __name__ == "__main__":
    run_tool(run)
