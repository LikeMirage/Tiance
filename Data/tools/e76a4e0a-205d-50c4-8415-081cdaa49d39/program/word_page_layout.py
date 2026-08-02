from __future__ import annotations

from docx.enum.section import WD_ORIENT
from docx.shared import Inches, Mm

from word_template_model import SectionProfile


PORTRAIT = "portrait"
LANDSCAPE = "landscape"
DEFAULT_PAGE_ORIENTATION = PORTRAIT
PAGE_ORIENTATIONS = frozenset({PORTRAIT, LANDSCAPE})
A4 = "a4"
LETTER = "letter"
DEFAULT_PAGE_SIZE = LETTER
PAGE_SIZES = frozenset({A4, LETTER})


def apply_document_page_layout(
    document,
    orientation: str,
    page_size: str = DEFAULT_PAGE_SIZE,
    *,
    template_section: SectionProfile | None = None,
) -> None:
    """Applies one explicit orientation and margin policy to the whole document."""
    if orientation not in PAGE_ORIENTATIONS:
        raise ValueError("不支持的页面方向。")
    if page_size not in PAGE_SIZES:
        raise ValueError("不支持的纸张规格。")
    for section in document.sections:
        if template_section is not None:
            _apply_template_section(section, template_section)
            continue
        _apply_page_size(section, page_size)
        _apply_orientation(section, orientation)
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)


def _apply_template_section(section, template: SectionProfile) -> None:
    section.page_width = Mm(template.page_width_mm)
    section.page_height = Mm(template.page_height_mm)
    _apply_orientation(section, template.orientation)
    section.top_margin = Mm(template.top_margin_mm)
    section.bottom_margin = Mm(template.bottom_margin_mm)
    section.left_margin = Mm(template.left_margin_mm)
    section.right_margin = Mm(template.right_margin_mm)
    section.gutter = Mm(template.gutter_mm)
    section.header_distance = Mm(template.header_distance_mm)
    section.footer_distance = Mm(template.footer_distance_mm)
    section.different_first_page_header_footer = template.different_first_page
    _replace_part_text(section.header, template.header_text)
    _replace_part_text(section.footer, template.footer_text)


def _replace_part_text(part, paragraphs: list[str]) -> None:
    if not paragraphs:
        return
    first = part.paragraphs[0]
    first.text = paragraphs[0]
    for text in paragraphs[1:]:
        part.add_paragraph(text)


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
