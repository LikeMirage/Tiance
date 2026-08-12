from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from webpage_reader import PageReadResult


def workspace_root() -> Path:
    raw = os.environ.get("TIANCE_WORKSPACE_ROOT") or os.environ.get("WORKSPACE_ROOT") or os.getcwd()
    return Path(raw).expanduser().resolve(strict=False)


def create_batch_directory(root: Path) -> Path:
    output_root = (root / "web_searches").resolve(strict=False)
    _require_within_workspace(output_root, root)
    output_root.mkdir(parents=True, exist_ok=True)
    name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    batch_dir = output_root / name
    batch_dir.mkdir(parents=False, exist_ok=False)
    return batch_dir


def numbered_directory(parent: Path, index: int, label: str) -> Path:
    folder = parent / f"{index:03d}-{slugify(label)}"
    folder.mkdir(parents=True, exist_ok=False)
    return folder


def save_page_result(
    folder: Path,
    page: PageReadResult,
    *,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    content_file: str | None = None
    binary_file: str | None = None
    if page.content:
        target = folder / "content.md"
        atomic_write_text(target, page.content + "\n")
        content_file = target.name
    if page.binary_content is not None and page.binary_extension:
        target = folder / f"resource{page.binary_extension}"
        atomic_write_bytes(target, page.binary_content)
        binary_file = target.name
    metadata = {
        "status": "saved" if page.ok else "failed",
        "requested_url": page.requested_url,
        "final_url": page.final_url,
        "title": page.title,
        "content_type": page.content_type,
        "status_code": page.status_code,
        "byte_count": page.byte_count,
        "character_count": page.character_count,
        "truncated": page.truncated,
        "extraction_method": page.extraction_method,
        "content_file": content_file,
        "binary_file": binary_file,
        "error_code": page.error_code,
        "error": page.error,
        "warnings": list(page.warnings),
        "source": source or {},
        "fetched_at": datetime.now().astimezone().isoformat(),
    }
    atomic_write_json(folder / "metadata.json", metadata)
    return metadata


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def relative_path(path: Path, root: Path) -> str:
    return path.resolve(strict=False).relative_to(root.resolve(strict=False)).as_posix()


def slugify(value: str) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", str(value or "").strip(), flags=re.UNICODE)
    text = re.sub(r"-+", "-", text).strip("-_.")
    return (text[:48] or "item").rstrip("-_.") or "item"


def _require_within_workspace(path: Path, root: Path) -> None:
    try:
        path.relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise ValueError("搜索结果目录必须位于当前工作区内。") from exc
