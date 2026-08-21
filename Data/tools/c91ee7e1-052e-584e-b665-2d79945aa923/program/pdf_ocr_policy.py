from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any, Callable


OCR_MODES = {"auto", "always", "never"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp"}
MIN_MEANINGFUL_PAGE_CHARS = 30
SCAN_PAGE_RATIO_TRIGGER = 0.20
CONSECUTIVE_SCAN_PAGE_TRIGGER = 3


class OcrDependencyMissingError(RuntimeError):
    pass


@dataclass(frozen=True)
class OcrDecision:
    mode: str
    applicable: bool
    enabled: bool
    reason: str
    page_count: int = 0
    text_page_count: int = 0
    scan_candidate_count: int = 0
    unknown_page_count: int = 0
    meaningful_char_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def decide_ocr(
    source_file: Path,
    mode: str,
    *,
    reader_factory: Callable[[str], Any] | None = None,
) -> OcrDecision:
    normalized_mode = str(mode or "auto").strip().lower()
    if normalized_mode not in OCR_MODES:
        raise ValueError(f"不支持的 OCR 模式：{mode}")

    suffix = source_file.suffix.lower()
    applicable = suffix == ".pdf" or suffix in IMAGE_SUFFIXES
    if not applicable:
        return OcrDecision(normalized_mode, False, False, "当前文件类型不需要 OCR 决策。")
    if normalized_mode == "always":
        return OcrDecision(normalized_mode, True, True, "用户要求强制开启 OCR。")
    if normalized_mode == "never":
        return OcrDecision(normalized_mode, True, False, "用户要求关闭 OCR。")
    if suffix in IMAGE_SUFFIXES:
        return OcrDecision(normalized_mode, True, True, "图片文件默认使用 OCR。", page_count=1, scan_candidate_count=1)

    return _inspect_pdf(source_file, reader_factory=reader_factory)


def _inspect_pdf(
    source_file: Path,
    *,
    reader_factory: Callable[[str], Any] | None = None,
) -> OcrDecision:
    if reader_factory is None:
        try:
            from pypdf import PdfReader
        except ModuleNotFoundError as exc:
            raise OcrDependencyMissingError(
                "缺少 pypdf，无法自动判断扫描型 PDF；请安装 program/requirements.txt。"
            ) from exc
        reader_factory = PdfReader

    reader = reader_factory(str(source_file))
    pages = list(reader.pages)
    scan_candidates: list[int] = []
    text_page_count = 0
    unknown_page_count = 0
    meaningful_char_count = 0

    for page_index, page in enumerate(pages):
        try:
            text = str(page.extract_text() or "")
            page_char_count = _meaningful_char_count(text)
            has_raster = _page_has_raster_image(page)
        except Exception:
            unknown_page_count += 1
            continue
        meaningful_char_count += page_char_count
        if page_char_count >= MIN_MEANINGFUL_PAGE_CHARS:
            text_page_count += 1
        elif has_raster:
            scan_candidates.append(page_index)

    page_count = len(pages)
    scan_candidate_count = len(scan_candidates)
    if page_count == 0:
        return OcrDecision("auto", True, True, "PDF 没有可检查页面，按安全策略开启 OCR。")
    if scan_candidate_count == 0 and unknown_page_count == 0:
        return OcrDecision(
            "auto",
            True,
            False,
            "未发现缺少文字层的图片页面。",
            page_count,
            text_page_count,
            0,
            0,
            meaningful_char_count,
        )

    ratio = scan_candidate_count / page_count
    longest_run = _longest_consecutive_run(scan_candidates)
    has_interior_scan_page = any(0 < index < page_count - 1 for index in scan_candidates)
    enabled = (
        unknown_page_count > 0
        or (page_count <= 2 and scan_candidate_count > 0)
        or ratio >= SCAN_PAGE_RATIO_TRIGGER
        or longest_run >= CONSECUTIVE_SCAN_PAGE_TRIGGER
        or has_interior_scan_page
    )
    if enabled:
        reason = "检测到缺少可用文字层的图片页面。"
    else:
        reason = "仅封面或封底疑似图片页，保留 PDF 原生文字解析。"
    return OcrDecision(
        "auto",
        True,
        enabled,
        reason,
        page_count,
        text_page_count,
        scan_candidate_count,
        unknown_page_count,
        meaningful_char_count,
    )


def _meaningful_char_count(text: str) -> int:
    compact = re.sub(r"\s+", "", text)
    return sum(1 for character in compact if character.isalnum())


def _dereference(value: Any) -> Any:
    get_object = getattr(value, "get_object", None)
    return get_object() if callable(get_object) else value


def _page_has_raster_image(page: Any) -> bool:
    resources = _dereference(page.get("/Resources"))
    if not hasattr(resources, "get"):
        return False
    xobjects = _dereference(resources.get("/XObject"))
    if not hasattr(xobjects, "values"):
        return False
    for raw_object in xobjects.values():
        image_object = _dereference(raw_object)
        if hasattr(image_object, "get") and str(image_object.get("/Subtype")) == "/Image":
            return True
    return False


def _longest_consecutive_run(indexes: list[int]) -> int:
    longest = 0
    current = 0
    previous: int | None = None
    for index in indexes:
        current = current + 1 if previous is not None and index == previous + 1 else 1
        longest = max(longest, current)
        previous = index
    return longest
