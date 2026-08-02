from __future__ import annotations

from pathlib import Path
from typing import Any

from word_template_extractor import extract_word_template
from word_template_store import WordTemplateStore


DOCX_SUFFIX = ".docx"


def list_template_result(store: WordTemplateStore) -> dict[str, Any]:
    templates = store.list_templates()
    return {
        "ok": True,
        "action": "list_templates",
        "message": f"共找到 {len(templates)} 个模板，包含内置默认样式。",
        "templates": templates,
    }


def extract_template_result(
    payload: dict[str, Any],
    *,
    store: WordTemplateStore,
    path_base: Path,
) -> dict[str, Any]:
    raw_path = _read_string(payload.get("template_source_path"))
    if not raw_path:
        raise ValueError("extract_template 操作需要 template_source_path。")
    source_path = _resolve_path(raw_path, base_path=path_base)
    if not source_path.is_file():
        raise ValueError("template_source_path 指向的 Word 文件不存在。")
    if source_path.suffix.lower() != DOCX_SUFFIX:
        raise ValueError("模板来源目前仅支持 .docx 文件。")

    name = _read_string(payload.get("template_name")) or source_path.stem
    if len(name) > 100:
        raise ValueError("template_name 不能超过 100 个字符。")
    template_payload = extract_word_template(
        source_path,
        template_name=name,
    )
    profile = store.save(template_payload)
    return {
        "ok": True,
        "action": "extract_template",
        "message": "Word 模板信息已提取并保存。",
        "template": {
            "template_id": profile.template_id,
            "name": profile.name,
            "source_file_name": profile.source_file_name,
            "created_at": profile.created_at,
            "builtin": False,
            "json_path": str(store.json_path(profile.template_id).resolve()),
            "source_summary": dict(profile.source_summary),
            "extracted_roles": sorted(profile.role_styles),
        },
    }


def _resolve_path(value: str, *, base_path: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_path / path
    return path.resolve(strict=False)


def _read_string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
