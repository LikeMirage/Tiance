from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from converter import convert_markdown_to_docx
from template_commands import extract_template_result, list_template_result
from word_formatting import (
    DEFAULT_CHINESE_FONT,
    DEFAULT_ENGLISH_FONT,
    DEFAULT_MATH_FONT,
    FontSettings,
)
from tiance_runtime import run_tool
from word_template_model import WordTemplateProfile
from word_template_store import WordTemplateStore
from word_page_layout import (
    DEFAULT_PAGE_ORIENTATION,
    DEFAULT_PAGE_SIZE,
    PAGE_ORIENTATIONS,
    PAGE_SIZES,
)

Payload = dict[str, Any]
ToolResult = dict[str, Any]

MARKDOWN_SUFFIXES = {".md", ".markdown"}
DOCX_SUFFIX = ".docx"
TOOL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = TOOL_ROOT / "assets" / "templates"
ACTIONS = frozenset({"convert", "extract_template", "list_templates"})


@dataclass(frozen=True, slots=True)
class Md2DocxRequest:
    markdown: str
    output_path: Path
    base_path: Path
    overwrite: bool
    input_path: Path
    fonts: FontSettings
    page_orientation: str
    page_size: str
    template: WordTemplateProfile | None


def run(payload: Payload) -> ToolResult:
    action = "convert"
    try:
        action = _action(payload.get("action"))
        store = WordTemplateStore(TEMPLATES_DIR)
        if action == "list_templates":
            return list_template_result(store)
        if action == "extract_template":
            return extract_template_result(
                payload,
                store=store,
                path_base=_default_path_base(),
            )
        request = _read_request(payload, store=store)
        output_exists = request.output_path.exists()
        if output_exists and not request.overwrite:
            return _failure(
                action="convert",
                input_path=str(request.input_path),
                output_path=str(request.output_path),
                error="目标文件已存在；如需覆盖请设置 overwrite=true。",
            )
        warnings = convert_markdown_to_docx(
            request.markdown,
            request.output_path,
            base_path=request.base_path,
            fonts=request.fonts,
            page_orientation=request.page_orientation,
            page_size=request.page_size,
            template=request.template,
            overwrite=request.overwrite,
        )
        return {
            "ok": True,
            "action": "convert",
            "input_path": str(request.input_path),
            "output_path": str(request.output_path),
            "overwritten": output_exists,
            "message": "转换完成。",
            "warnings": warnings,
            "template_id": (
                request.template.template_id if request.template is not None else "builtin-default"
            ),
            "template_name": (
                request.template.name if request.template is not None else "内置默认样式"
            ),
        }
    except Exception as exc:
        return _failure(action=action, error=str(exc) or exc.__class__.__name__)


def _read_request(payload: Payload, *, store: WordTemplateStore) -> Md2DocxRequest:
    path_base = _default_path_base()
    raw_input_path = _read_string(payload.get("input_path"))
    if not raw_input_path:
        raise ValueError("input_path 不能为空。")

    overwrite = payload.get("overwrite") if isinstance(payload.get("overwrite"), bool) else False
    output_value = _read_string(payload.get("output_path"))
    template_id = _read_string(payload.get("template_id"))
    template = (
        store.load(template_id)
        if template_id and template_id != "builtin-default"
        else None
    )
    template_body = template.style_for("body") if template is not None else None
    template_run = template_body.run if template_body is not None else None
    fonts = FontSettings(
        chinese=_font_value(
            payload.get("chinese_font"),
            template_run.east_asia_font
            if template_run is not None and template_run.east_asia_font
            else DEFAULT_CHINESE_FONT,
        ),
        english=_font_value(
            payload.get("english_font"),
            template_run.latin_font
            if template_run is not None and template_run.latin_font
            else DEFAULT_ENGLISH_FONT,
        ),
        math=_font_value(payload.get("math_font"), DEFAULT_MATH_FONT),
    )
    page_orientation = _page_orientation(payload.get("page_orientation"))
    page_size = _page_size(payload.get("page_size"))

    input_path = _resolve_path(raw_input_path, base_path=path_base)
    if not input_path.is_file():
        raise ValueError("input_path 指向的 Markdown 文件不存在。")
    if input_path.suffix.lower() not in MARKDOWN_SUFFIXES:
        raise ValueError("input_path 必须指向 .md 或 .markdown 文件。")
    markdown = input_path.read_text(encoding="utf-8-sig")
    output_path = (
        _resolve_path(output_value, base_path=path_base)
        if output_value
        else input_path.with_suffix(DOCX_SUFFIX)
    )

    if output_path.suffix.lower() != DOCX_SUFFIX:
        raise ValueError("output_path 必须以 .docx 结尾。")
    if output_path.exists() and not output_path.is_file():
        raise ValueError("output_path 已存在但不是文件。")

    return Md2DocxRequest(
        markdown=markdown,
        output_path=output_path,
        base_path=input_path.parent,
        overwrite=overwrite,
        input_path=input_path,
        fonts=fonts,
        page_orientation=page_orientation,
        page_size=page_size,
        template=template,
    )


def _default_path_base() -> Path:
    raw_root = os.environ.get("TIANCE_WORKSPACE_ROOT") or os.environ.get("WORKSPACE_ROOT") or os.getcwd()
    return Path(raw_root).expanduser().resolve(strict=False)


def _resolve_path(value: str, *, base_path: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_path / path
    return path.resolve(strict=False)


def _read_string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _action(value: object) -> str:
    action = (_read_string(value) or "convert").lower()
    if action not in ACTIONS:
        raise ValueError("action 必须为 convert、extract_template 或 list_templates。")
    return action


def _font_value(value: object, default: str) -> str:
    return _read_string(value) or default


def _page_orientation(value: object) -> str:
    orientation = (_read_string(value) or DEFAULT_PAGE_ORIENTATION).lower()
    if orientation not in PAGE_ORIENTATIONS:
        raise ValueError("page_orientation 必须为 portrait 或 landscape。")
    return orientation


def _page_size(value: object) -> str:
    page_size = (_read_string(value) or DEFAULT_PAGE_SIZE).lower()
    if page_size not in PAGE_SIZES:
        raise ValueError("page_size 必须为 a4 或 letter。")
    return page_size


def _failure(
    *,
    action: str,
    error: str,
    input_path: str = "",
    output_path: str = "",
) -> ToolResult:
    return {
        "ok": False,
        "action": action,
        "input_path": input_path,
        "output_path": output_path,
        "overwritten": False,
        "message": "",
        "warnings": [],
        "error": error,
    }


if __name__ == "__main__":
    run_tool(run)
