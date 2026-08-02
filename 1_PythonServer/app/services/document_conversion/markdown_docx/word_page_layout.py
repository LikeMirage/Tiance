from __future__ import annotations

from docx.enum.section import WD_ORIENT
from docx.shared import Inches, Mm


PORTRAIT = "portrait"
LANDSCAPE = "landscape"
DEFAULT_PAGE_ORIENTATION = PORTRAIT
PAGE_ORIENTATIONS = frozenset({PORTRAIT, LANDSCAPE})
A4 = "a4"
LETTER = "letter"
DEFAULT_PAGE_SIZE = LETTER
PAGE_SIZES = frozenset({A4, LETTER})


def apply_document_page_layout(document, orientation: str, page_size: str = DEFAULT_PAGE_SIZE) -> None:
    """Applies one explicit orientation and margin policy to the whole document."""
    if orientation not in PAGE_ORIENTATIONS:
        raise ValueError("不支持的页面方向。")
    if page_size not in PAGE_SIZES:
        raise ValueError("不支持的纸张规格。")
    for section in document.sections:
        _apply_page_size(section, page_size)
        _apply_orientation(section, orientation)
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)


def _apply_page_size(section, page_size: str) -> None:
    if page_size == A4:
        section.page_width = Mm(210)
        section.page_height = Mm(297)
        return
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)


def _apply_orientation(section, orientation: str) -> None:
    width = section.page_width
    height = section.page_height
    if orientation == LANDSCAPE:
        section.orientation = WD_ORIENT.LANDSCAPE
        if width < height:
            section.page_width = height
            section.page_height = width
        return
    section.orientation = WD_ORIENT.PORTRAIT
    if width > height:
        section.page_width = height
        section.page_height = width
