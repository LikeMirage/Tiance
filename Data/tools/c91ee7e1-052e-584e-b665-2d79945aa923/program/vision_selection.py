from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from typing import Any


FULL_PAGE_MIN_WIDTH = 850
FULL_PAGE_MIN_HEIGHT = 750
FULL_PAGE_MIN_AREA_RATIO = 0.72


@dataclass(frozen=True)
class VisionSelection:
    selected_paths: tuple[str, ...]
    skipped_full_page_paths: tuple[str, ...]
    page_count: int
    full_page_image_count: int
    mass_full_page_pattern: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["selected_paths"] = list(self.selected_paths)
        payload["skipped_full_page_paths"] = list(self.skipped_full_page_paths)
        return payload


def select_vision_images(
    relative_paths: list[str],
    *,
    content_list_path: Path | None,
    known_page_count: int,
    source_suffix: str,
    analyze_full_page_images: bool,
) -> VisionSelection:
    normalized_paths = tuple(dict.fromkeys(_normalize_path(path) for path in relative_paths if path))
    entries = _read_content_list(content_list_path)
    page_count = max(known_page_count, _page_count(entries))
    full_page_paths = _match_full_page_images(normalized_paths, entries)

    if not full_page_paths and page_count > 0 and len(normalized_paths) >= math.ceil(page_count * 0.8):
        full_page_paths = set(normalized_paths)

    full_page_count = len(full_page_paths)
    mass_pattern = _is_mass_full_page_pattern(page_count, full_page_count)
    should_skip = source_suffix.lower() == ".pdf" and mass_pattern and not analyze_full_page_images
    skipped = tuple(path for path in normalized_paths if should_skip and path in full_page_paths)
    skipped_set = set(skipped)
    selected = tuple(path for path in normalized_paths if path not in skipped_set)
    if skipped:
        reason = "检测到批量整页图片，已从 DMX 二次分析中排除。"
    elif analyze_full_page_images and mass_pattern:
        reason = "已明确允许分析整页图片。"
    else:
        reason = "未检测到需要批量排除的整页扫描图。"
    return VisionSelection(selected, skipped, page_count, full_page_count, mass_pattern, reason)


def should_force_ocr_rerun(
    *,
    selection: VisionSelection,
    markdown_text_chars: int,
    ocr_mode: str,
    ocr_enabled: bool,
) -> bool:
    if ocr_mode != "auto" or ocr_enabled or not selection.mass_full_page_pattern:
        return False
    minimum_expected_chars = max(100, selection.page_count * 20)
    return markdown_text_chars < minimum_expected_chars


def _read_content_list(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _page_count(entries: list[dict[str, Any]]) -> int:
    indexes = [item.get("page_idx") for item in entries if isinstance(item.get("page_idx"), int)]
    return max(indexes, default=-1) + 1


def _match_full_page_images(relative_paths: tuple[str, ...], entries: list[dict[str, Any]]) -> set[str]:
    matched: set[str] = set()
    for item in entries:
        if str(item.get("type") or "").lower() not in {"image", "chart"}:
            continue
        image_path = _normalize_path(str(item.get("img_path") or ""))
        if not image_path or not _is_full_page_bbox(item.get("bbox")):
            continue
        for relative_path in relative_paths:
            if relative_path == image_path or relative_path.endswith(f"/{image_path}"):
                matched.add(relative_path)
    return matched


def _is_full_page_bbox(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 4:
        return False
    try:
        x0, y0, x1, y1 = (float(item) for item in value)
    except (TypeError, ValueError):
        return False
    width = max(0.0, x1 - x0)
    height = max(0.0, y1 - y0)
    return (
        width >= FULL_PAGE_MIN_WIDTH
        and height >= FULL_PAGE_MIN_HEIGHT
        and (width * height) / 1_000_000 >= FULL_PAGE_MIN_AREA_RATIO
    )


def _is_mass_full_page_pattern(page_count: int, full_page_count: int) -> bool:
    if page_count <= 0 or full_page_count <= 0:
        return False
    if page_count <= 2:
        return full_page_count == page_count
    return full_page_count >= 3 and full_page_count / page_count >= 0.5


def _normalize_path(value: str) -> str:
    return str(value or "").replace("\\", "/").lstrip("./")
