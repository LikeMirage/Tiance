from __future__ import annotations

from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from .word_xml import get_or_add_ordered_child


EMU_PER_TWIP = 635
TWIPS_PER_POINT = 20
CELL_MARGIN_TOP_TWIPS = 80
CELL_MARGIN_BOTTOM_TWIPS = 80
CELL_MARGIN_LEFT_TWIPS = 100
CELL_MARGIN_RIGHT_TWIPS = 100
CELL_HORIZONTAL_PADDING_POINTS = (
    CELL_MARGIN_LEFT_TWIPS + CELL_MARGIN_RIGHT_TWIPS
) / TWIPS_PER_POINT


def apply_column_widths(table, percentages: list[float], document) -> None:
    if not percentages:
        return
    available_twips = document_available_width_twips(document)
    if available_twips <= 0:
        return
    widths = _percentages_to_twips(percentages, available_twips)
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _set_fixed_table_layout(table)
    _set_table_width(table, available_twips)
    _set_table_grid(table, widths)
    for row in table.rows:
        for index, cell in enumerate(row.cells):
            if index < len(widths):
                _set_cell_width(cell, widths[index])


def set_cell_margins(table) -> None:
    properties = table._tbl.tblPr
    margins = get_or_add_ordered_child(properties, "w:tblCellMar")
    for side, value in {
        "top": CELL_MARGIN_TOP_TWIPS,
        "bottom": CELL_MARGIN_BOTTOM_TWIPS,
        "left": CELL_MARGIN_LEFT_TWIPS,
        "right": CELL_MARGIN_RIGHT_TWIPS,
    }.items():
        margin = margins.find(qn(f"w:{side}"))
        if margin is None:
            margin = OxmlElement(f"w:{side}")
            margins.append(margin)
        margin.set(qn("w:w"), str(value))
        margin.set(qn("w:type"), "dxa")


def set_cell_shading(cell, color: str) -> None:
    properties = cell._tc.get_or_add_tcPr()
    shading = get_or_add_ordered_child(properties, "w:shd")
    shading.set(qn("w:fill"), color)


def set_repeat_header(row) -> None:
    properties = row._tr.get_or_add_trPr()
    header = properties.find(qn("w:tblHeader"))
    if header is None:
        header = OxmlElement("w:tblHeader")
        properties.append(header)
    header.set(qn("w:val"), "true")


def document_available_width_twips(document) -> int:
    section = document.sections[-1]
    available_emu = int(section.page_width) - int(section.left_margin) - int(section.right_margin)
    return max(1, round(available_emu / EMU_PER_TWIP))


def document_available_width_points(document) -> float:
    return document_available_width_twips(document) / TWIPS_PER_POINT


def _percentages_to_twips(percentages: list[float], total_twips: int) -> list[int]:
    widths: list[int] = []
    used = 0
    for index, percent in enumerate(percentages):
        if index == len(percentages) - 1:
            width = max(1, total_twips - used)
        else:
            width = max(1, round(total_twips * percent / 100.0))
            used += width
        widths.append(width)
    return widths


def _set_fixed_table_layout(table) -> None:
    properties = table._tbl.tblPr
    layout = get_or_add_ordered_child(properties, "w:tblLayout")
    layout.set(qn("w:type"), "fixed")


def _set_table_width(table, width_twips: int) -> None:
    properties = table._tbl.tblPr
    width = get_or_add_ordered_child(properties, "w:tblW")
    width.set(qn("w:type"), "dxa")
    width.set(qn("w:w"), str(width_twips))


def _set_table_grid(table, widths: list[int]) -> None:
    grid = table._tbl.tblGrid
    if grid is None:
        grid = OxmlElement("w:tblGrid")
        table._tbl.insert(table._tbl.index(table._tbl.tblPr) + 1, grid)
    for child in list(grid):
        grid.remove(child)
    for width in widths:
        column = OxmlElement("w:gridCol")
        column.set(qn("w:w"), str(width))
        grid.append(column)


def _set_cell_width(cell, width_twips: int) -> None:
    properties = cell._tc.get_or_add_tcPr()
    width = get_or_add_ordered_child(properties, "w:tcW")
    width.set(qn("w:type"), "dxa")
    width.set(qn("w:w"), str(width_twips))
